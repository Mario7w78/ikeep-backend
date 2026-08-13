"""El endpoint del calendario."""

from datetime import date
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain.entities.user_activity import ActividadUsuario
from domain.services.calendar.expansion import Excepcion
from infrastructure.adapters.inbound.api.auth import (
    AuthenticatedUser,
    get_current_user,
)
from infrastructure.adapters.inbound.api.v1.activities_router import (
    get_access_token,
    get_repository,
)
from infrastructure.adapters.inbound.api.v1.calendar_router import (
    get_exceptions_repository,
    router,
)

USUARIO = AuthenticatedUser(id="usuario-1", email="alguien@ejemplo.com")
TOKEN = "el-jwt"
RUTA = "/api/v1/calendario"


def actividad(**over):
    base = dict(
        id="act-1", propietario_id="usuario-1", nombre="Cálculo", tipo="FIXED",
        dias_habilitados=["Martes"], config_por_dia={"Martes": {"partitions": []}},
    )
    base.update(over)
    return ActividadUsuario(**base)


@pytest.fixture
def actividades():
    repo = Mock()
    repo.list_all.return_value = [actividad()]
    return repo


@pytest.fixture
def excepciones():
    repo = Mock()
    repo.del_rango.return_value = []
    return repo


@pytest.fixture
def client(actividades, excepciones):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: USUARIO
    app.dependency_overrides[get_access_token] = lambda: TOKEN
    app.dependency_overrides[get_repository] = lambda: actividades
    app.dependency_overrides[get_exceptions_repository] = lambda: excepciones
    with TestClient(app) as c:
        yield c


class TestAutenticacion:
    def test_exige_token(self, actividades, excepciones):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_repository] = lambda: actividades
        app.dependency_overrides[get_exceptions_repository] = lambda: excepciones

        with TestClient(app) as c:
            r = c.get(f"{RUTA}?desde=2026-08-03&hasta=2026-08-09")

        assert r.status_code == 401


class TestVerElCalendario:
    def test_devuelve_las_ocurrencias_con_fecha(self, client):
        cuerpo = client.get(f"{RUTA}?desde=2026-08-03&hasta=2026-08-16").json()

        assert [o["fecha"] for o in cuerpo["ocurrencias"]] == ["2026-08-04", "2026-08-11"]

    def test_cada_ocurrencia_trae_su_actividad(self, client):
        cuerpo = client.get(f"{RUTA}?desde=2026-08-03&hasta=2026-08-09").json()

        assert cuerpo["ocurrencias"][0]["actividad"]["title"] == "Cálculo"

    def test_un_evento_unico_aparece_marcado(self, client, actividades):
        actividades.list_all.return_value = [
            actividad(id="p", nombre="Parcial", fecha_unica="2026-08-06", dias_habilitados=[])
        ]

        cuerpo = client.get(f"{RUTA}?desde=2026-08-03&hasta=2026-08-09").json()

        assert cuerpo["ocurrencias"][0]["es_unica"] is True

    def test_una_cancelacion_saca_ese_dia(self, client, excepciones):
        excepciones.del_rango.return_value = [
            Excepcion("act-1", date(2026, 8, 4), "cancelada")
        ]

        cuerpo = client.get(f"{RUTA}?desde=2026-08-03&hasta=2026-08-09").json()

        assert cuerpo["ocurrencias"] == []

    def test_una_movida_dice_de_donde_viene(self, client, excepciones):
        excepciones.del_rango.return_value = [
            Excepcion("act-1", date(2026, 8, 4), "movida", date(2026, 8, 6))
        ]

        o = client.get(f"{RUTA}?desde=2026-08-03&hasta=2026-08-09").json()["ocurrencias"][0]

        assert o["fecha"] == "2026-08-06"
        assert o["movida_desde"] == "2026-08-04"


class TestLimitesDelRango:
    def test_un_rango_invertido_se_rechaza(self, client):
        r = client.get(f"{RUTA}?desde=2026-08-09&hasta=2026-08-03")

        assert r.status_code == 422

    def test_un_rango_enorme_se_rechaza(self, client):
        # Un año entero en una respuesta es un payload que el teléfono no
        # puede dibujar igual.
        r = client.get(f"{RUTA}?desde=2026-01-01&hasta=2026-12-31")

        assert r.status_code == 422

    def test_un_trimestre_entra(self, client):
        r = client.get(f"{RUTA}?desde=2026-08-01&hasta=2026-10-30")

        assert r.status_code == 200


class TestExcepciones:
    def test_cancelar_guarda_la_excepcion(self, client, excepciones):
        r = client.put(
            f"{RUTA}/excepciones",
            json={"activity_id": "act-1", "fecha": "2026-08-11", "tipo": "cancelada"},
        )

        assert r.status_code == 204
        guardada = excepciones.guardar.call_args[0][2]
        assert guardada.tipo == "cancelada"
        assert guardada.fecha == date(2026, 8, 11)

    def test_mover_sin_destino_se_rechaza(self, client):
        r = client.put(
            f"{RUTA}/excepciones",
            json={"activity_id": "act-1", "fecha": "2026-08-11", "tipo": "movida"},
        )

        assert r.status_code == 422

    def test_cancelar_con_destino_se_rechaza(self, client):
        # Es una contradiccion: o se cancela o se mueve.
        r = client.put(
            f"{RUTA}/excepciones",
            json={
                "activity_id": "act-1", "fecha": "2026-08-11",
                "tipo": "cancelada", "nueva_fecha": "2026-08-13",
            },
        )

        assert r.status_code == 422

    def test_el_dueno_sale_del_token(self, client, excepciones):
        client.put(
            f"{RUTA}/excepciones",
            json={"activity_id": "act-1", "fecha": "2026-08-11", "tipo": "cancelada"},
        )

        assert excepciones.guardar.call_args[0][1] == "usuario-1"

    def test_deshacer_borra(self, client, excepciones):
        r = client.delete(f"{RUTA}/excepciones?activity_id=act-1&fecha=2026-08-11")

        assert r.status_code == 204
        excepciones.borrar.assert_called_once_with(TOKEN, "act-1", date(2026, 8, 11))
