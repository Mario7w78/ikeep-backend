"""Tests del CRUD de actividades.

Se sustituyen las dependencias de FastAPI en vez de parchear modulos: asi los
tests ejercitan el router tal como lo monta la app, incluidos los codigos de
estado y la validacion de los schemas.
"""

from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain.entities.user_activity import ActividadUsuario
from infrastructure.adapters.inbound.api.auth import (
    AuthenticatedUser,
    get_current_user,
)
from infrastructure.adapters.inbound.api.v1.activities_router import (
    get_access_token,
    get_repository,
    router,
)

USUARIO = AuthenticatedUser(id="usuario-1", email="alguien@ejemplo.com")
TOKEN = "el-jwt-del-usuario"

PAYLOAD = {
    "id": "act-1",
    "title": "Calculo",
    "type": "fija",
    "identity": "clase",
    "priority": 1,
    "difficulty": "alta",
    "deadline": None,
    "days_enabled": ["martes"],
    "days_config": {},
    "optional_day": False,
    "day_from": None,
    "day_to": None,
    "is_anchor": True,
}

ACTIVIDAD = ActividadUsuario(
    id="act-1",
    propietario_id="usuario-1",
    nombre="Calculo",
    tipo="fija",
    identidad="clase",
    prioridad=1,
    dificultad="alta",
    dias_habilitados=["martes"],
    es_ancla=True,
)


@pytest.fixture
def repo():
    return Mock()


@pytest.fixture
def client(repo):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: USUARIO
    app.dependency_overrides[get_access_token] = lambda: TOKEN
    app.dependency_overrides[get_repository] = lambda: repo

    with TestClient(app) as c:
        yield c


@pytest.fixture
def client_sin_auth(repo):
    """Sin sustituir get_current_user, para comprobar que el router exige token."""
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_repository] = lambda: repo

    with TestClient(app) as c:
        yield c


class TestAutenticacion:
    @pytest.mark.parametrize(
        "metodo,ruta",
        [
            ("get", "/api/v1/actividades"),
            ("get", "/api/v1/actividades/act-1"),
            ("put", "/api/v1/actividades/act-1"),
            ("delete", "/api/v1/actividades/act-1"),
        ],
    )
    def test_todas_las_rutas_exigen_token(self, client_sin_auth, metodo, ruta):
        # request() acepta cuerpo en cualquier verbo; los atajos como
        # client.delete() no.
        respuesta = client_sin_auth.request(metodo, ruta, json=PAYLOAD)

        assert respuesta.status_code == 401


class TestListar:
    def test_devuelve_las_actividades_del_usuario(self, client, repo):
        repo.list_all.return_value = [ACTIVIDAD]

        respuesta = client.get("/api/v1/actividades")

        assert respuesta.status_code == 200
        # fecha_unica se agrego con el calendario: null cuando la actividad se
        # repite, que es el caso de esta.
        assert respuesta.json() == [
            {**PAYLOAD, "user_id": "usuario-1", "fecha_unica": None}
        ]
        repo.list_all.assert_called_once_with(TOKEN)

    def test_sin_actividades_devuelve_lista_vacia(self, client, repo):
        repo.list_all.return_value = []

        respuesta = client.get("/api/v1/actividades")

        assert respuesta.status_code == 200
        assert respuesta.json() == []


class TestObtener:
    def test_devuelve_la_actividad(self, client, repo):
        repo.get.return_value = ACTIVIDAD

        respuesta = client.get("/api/v1/actividades/act-1")

        assert respuesta.status_code == 200
        assert respuesta.json()["title"] == "Calculo"
        repo.get.assert_called_once_with(TOKEN, "act-1")

    def test_404_si_no_existe_o_es_de_otro(self, client, repo):
        repo.get.return_value = None

        assert client.get("/api/v1/actividades/act-1").status_code == 404


class TestGuardar:
    def test_crea_y_devuelve_lo_guardado(self, client, repo):
        repo.save.return_value = ACTIVIDAD

        respuesta = client.put("/api/v1/actividades/act-1", json=PAYLOAD)

        assert respuesta.status_code == 200
        assert respuesta.json()["user_id"] == "usuario-1"

    def test_el_dueño_sale_del_token_no_del_cuerpo(self, client, repo):
        """Mandar un user_id ajeno no debe cambiar a nombre de quien se guarda."""
        repo.save.return_value = ACTIVIDAD

        client.put(
            "/api/v1/actividades/act-1",
            json={**PAYLOAD, "user_id": "otro-usuario"},
        )

        guardada = repo.save.call_args[0][1]
        assert guardada.propietario_id == "usuario-1"

    def test_el_id_de_la_url_manda_sobre_el_del_cuerpo(self, client, repo):
        """Evita crear 'act-2' con un PUT a /act-1."""
        repo.save.return_value = ACTIVIDAD

        client.put("/api/v1/actividades/act-1", json={**PAYLOAD, "id": "act-2"})

        assert repo.save.call_args[0][1].id == "act-1"

    def test_rechaza_prioridad_fuera_de_rango(self, client, repo):
        respuesta = client.put(
            "/api/v1/actividades/act-1", json={**PAYLOAD, "priority": 99}
        )

        assert respuesta.status_code == 422
        repo.save.assert_not_called()

    def test_rechaza_titulo_vacio(self, client, repo):
        respuesta = client.put(
            "/api/v1/actividades/act-1", json={**PAYLOAD, "title": ""}
        )

        assert respuesta.status_code == 422
        repo.save.assert_not_called()


class TestBorrar:
    def test_borra_y_responde_sin_contenido(self, client, repo):
        respuesta = client.delete("/api/v1/actividades/act-1")

        assert respuesta.status_code == 204
        repo.delete.assert_called_once_with(TOKEN, "act-1")

    def test_borrar_algo_inexistente_tambien_responde_204(self, client, repo):
        """Es idempotente: el resultado buscado —que no este— ya se cumple."""
        repo.delete.return_value = None

        assert client.delete("/api/v1/actividades/otra").status_code == 204
