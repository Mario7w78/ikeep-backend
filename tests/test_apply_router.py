"""Tests del endpoint que aplica una propuesta confirmada.

Reemplaza los tres viajes que hacia el cliente —guardar, generar, persistir—
por uno solo, con la compensacion del lado del servidor.
"""

from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain.services.scheduling.apply_proposal import ErrorAlAplicar, ResultadoAplicar
from infrastructure.adapters.inbound.api.auth import (
    AuthenticatedUser,
    get_current_user,
)
from infrastructure.adapters.inbound.api.v1.activities_router import get_access_token
from infrastructure.adapters.inbound.api.v1.assistant_router import (
    get_apply_repos_factory,
    get_conversation_service_factory,
    router,
)

USUARIO = AuthenticatedUser(id="usuario-1", email="alguien@ejemplo.com")
TOKEN = "el-jwt-del-usuario"
RUTA = "/api/v1/asistente/aplicar"

ACTIVIDAD = {
    "id": "1754000000000",
    "title": "Calculo",
    "type": "FIXED",
    "identity": "clase",
    "priority": 3,
    "difficulty": "media",
    "days_enabled": ["Martes"],
    "days_config": {
        "Martes": {
            "groupId": 1,
            "partitions": [
                {
                    "startHour": "2026-08-03T15:00:00.000Z",
                    "endHour": "2026-08-03T17:00:00.000Z",
                    "durationTime": 120,
                }
            ],
        }
    },
}


@pytest.fixture
def repos():
    return Mock()


@pytest.fixture
def client(repos):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: USUARIO
    app.dependency_overrides[get_access_token] = lambda: TOKEN
    app.dependency_overrides[get_conversation_service_factory] = (
        lambda: lambda _t, _m: Mock()
    )
    app.dependency_overrides[get_apply_repos_factory] = (
        lambda: lambda _token, _user, _sched: repos
    )

    with TestClient(app) as c:
        yield c


def _resultado_bueno():
    return ResultadoAplicar(
        estado="OPTIMO",
        mensaje="listo",
        recomendaciones=[],
        tareas_omitidas=[],
        actividades_programadas=[
            {
                "activity": {"id": "1754000000000"},
                "assignedStartTime": "10:00",
                "assignedEndTime": "12:00",
                "day": "Martes",
                "tipo": "clase",
                "nombre": "Calculo",
            }
        ],
    )


class TestAutenticacion:
    def test_exige_token(self, repos):
        # Aca se escribe en la base de otra persona si nadie comprueba quien pide.
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_apply_repos_factory] = (
            lambda: lambda _t, _u, _s: repos
        )

        with TestClient(app) as c:
            respuesta = c.post(RUTA, json={"tipo": "regenerar"})

        assert respuesta.status_code == 401


class TestAplicar:
    def test_devuelve_el_horario_ya_persistido(self, client, monkeypatch):
        import infrastructure.adapters.inbound.api.v1.assistant_router as modulo

        monkeypatch.setattr(modulo, "aplicar", lambda *a, **k: _resultado_bueno())

        respuesta = client.post(RUTA, json={"tipo": "crear", "actividad": ACTIVIDAD})

        assert respuesta.status_code == 200
        assert respuesta.json()["scheduled_activities"][0]["assignedStartTime"] == "10:00"

    def test_el_desfase_del_reloj_llega_al_servicio(self, client, monkeypatch):
        import infrastructure.adapters.inbound.api.v1.assistant_router as modulo

        recibido = {}

        def espia(_repos, **kwargs):
            recibido.update(kwargs)
            return _resultado_bueno()

        monkeypatch.setattr(modulo, "aplicar", espia)

        client.post(
            RUTA,
            json={
                "tipo": "crear",
                "actividad": ACTIVIDAD,
                "desfase_utc_minutos": -300,
            },
        )

        assert recibido["desfase_utc_minutos"] == -300

    def test_el_dueno_sale_del_token_y_no_del_cuerpo(self, client, monkeypatch):
        import infrastructure.adapters.inbound.api.v1.assistant_router as modulo

        recibido = {}

        def espia(_repos, **kwargs):
            recibido.update(kwargs)
            return _resultado_bueno()

        monkeypatch.setattr(modulo, "aplicar", espia)

        client.post(RUTA, json={"tipo": "crear", "actividad": ACTIVIDAD})

        assert recibido["actividad"].propietario_id == "usuario-1"

    def test_un_fallo_del_solver_es_409_y_no_500(self, client, monkeypatch):
        # El servidor funciono. Lo que no se pudo fue dejar un horario bueno,
        # y el cambio ya se deshizo.
        import infrastructure.adapters.inbound.api.v1.assistant_router as modulo

        def revienta(*a, **k):
            raise ErrorAlAplicar("el solver no pudo")

        monkeypatch.setattr(modulo, "aplicar", revienta)

        respuesta = client.post(RUTA, json={"tipo": "crear", "actividad": ACTIVIDAD})

        assert respuesta.status_code == 409


class TestValidacion:
    def test_crear_sin_actividad_se_rechaza(self, client):
        assert client.post(RUTA, json={"tipo": "crear"}).status_code == 422

    def test_eliminar_sin_id_se_rechaza(self, client):
        assert client.post(RUTA, json={"tipo": "eliminar"}).status_code == 422

    def test_regenerar_no_necesita_nada(self, client, monkeypatch):
        import infrastructure.adapters.inbound.api.v1.assistant_router as modulo

        monkeypatch.setattr(modulo, "aplicar", lambda *a, **k: _resultado_bueno())

        assert client.post(RUTA, json={"tipo": "regenerar"}).status_code == 200

    def test_un_desfase_imposible_se_rechaza(self, client):
        respuesta = client.post(
            RUTA, json={"tipo": "regenerar", "desfase_utc_minutos": 5000}
        )

        assert respuesta.status_code == 422
