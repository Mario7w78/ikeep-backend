"""Tests del horario guardado y del historial de energia."""

from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain.entities.energy_record import RegistroEnergia
from domain.entities.stored_schedule import HorarioGuardado
from infrastructure.adapters.inbound.api.auth import (
    AuthenticatedUser,
    get_current_user,
)
from infrastructure.adapters.inbound.api.v1.activities_router import get_access_token
from infrastructure.adapters.inbound.api.v1.stored_schedule_router import (
    get_energia_repository,
    get_horario_repository,
    router,
)

USUARIO = AuthenticatedUser(id="usuario-1", email="alguien@ejemplo.com")
TOKEN = "el-jwt-del-usuario"


@pytest.fixture
def horarios():
    return Mock()


@pytest.fixture
def energia():
    return Mock()


@pytest.fixture
def client(horarios, energia):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: USUARIO
    app.dependency_overrides[get_access_token] = lambda: TOKEN
    app.dependency_overrides[get_horario_repository] = lambda: horarios
    app.dependency_overrides[get_energia_repository] = lambda: energia

    with TestClient(app) as c:
        yield c


class TestHorario:
    def test_devuelve_el_horario_guardado(self, client, horarios):
        horarios.get.return_value = HorarioGuardado(
            propietario_id="usuario-1",
            estado="OPTIMO",
            actividades_programadas=[{"day": 0}],
        )

        respuesta = client.get("/api/v1/horario")

        assert respuesta.status_code == 200
        assert respuesta.json()["estado"] == "OPTIMO"
        assert respuesta.json()["scheduled_activities"] == [{"day": 0}]

    def test_sin_horario_devuelve_uno_vacio_no_404(self, client, horarios):
        """Una cuenta nueva no genero horario todavia; no es un error."""
        horarios.get.return_value = None

        respuesta = client.get("/api/v1/horario")

        assert respuesta.status_code == 200
        assert respuesta.json()["scheduled_activities"] == []

    def test_guardar_usa_el_usuario_del_token(self, client, horarios):
        horarios.save.return_value = HorarioGuardado(propietario_id="usuario-1")

        client.put("/api/v1/horario", json={"estado": "OPTIMO"})

        assert horarios.save.call_args[0][1].propietario_id == "usuario-1"

    def test_conserva_las_actividades_sin_interpretarlas(self, client, horarios):
        """El backend no le da forma a la salida del solver."""
        anidado = [{"activity": {"id": "a", "daysConfig": {"lunes": {"x": 1}}}}]
        horarios.save.return_value = HorarioGuardado(
            propietario_id="usuario-1", actividades_programadas=anidado
        )

        respuesta = client.put(
            "/api/v1/horario", json={"scheduled_activities": anidado}
        )

        assert respuesta.json()["scheduled_activities"] == anidado

    def test_borrar_responde_sin_contenido(self, client, horarios):
        respuesta = client.delete("/api/v1/horario")

        assert respuesta.status_code == 204
        horarios.delete.assert_called_once_with(TOKEN)

    def test_exige_token(self, horarios):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_horario_repository] = lambda: horarios

        with TestClient(app) as c:
            assert c.get("/api/v1/horario").status_code == 401


class TestEnergia:
    def test_devuelve_el_historial(self, client, energia):
        energia.history.return_value = [
            RegistroEnergia(
                propietario_id="usuario-1",
                momento="2026-08-03T10:00:00+00:00",
                nivel=3,
                dia_semana=0,
            )
        ]

        respuesta = client.get("/api/v1/energia")

        assert respuesta.status_code == 200
        assert respuesta.json()[0]["nivel"] == 3
        energia.history.assert_called_once_with(TOKEN, 14)

    def test_acepta_una_ventana_distinta(self, client, energia):
        energia.history.return_value = []

        client.get("/api/v1/energia?dias=30")

        energia.history.assert_called_once_with(TOKEN, 30)

    def test_rechaza_una_ventana_absurda(self, client, energia):
        assert client.get("/api/v1/energia?dias=5000").status_code == 422
        energia.history.assert_not_called()

    def test_registrar_deriva_el_dia_de_la_semana(self, client, energia):
        """2026-08-03 es lunes -> 0. No se acepta del cliente para que no
        pueda contradecir al timestamp."""
        energia.add.side_effect = lambda _t, r: r

        respuesta = client.post(
            "/api/v1/energia",
            json={"nivel": 2, "timestamp": "2026-08-03T10:00:00+00:00"},
        )

        assert respuesta.status_code == 201
        assert respuesta.json()["dia_semana"] == 0

    def test_registrar_sin_timestamp_usa_la_hora_de_recepcion(self, client, energia):
        energia.add.side_effect = lambda _t, r: r

        respuesta = client.post("/api/v1/energia", json={"nivel": 1})

        assert respuesta.status_code == 201
        assert respuesta.json()["timestamp"]

    def test_rechaza_un_nivel_invalido(self, client, energia):
        assert client.post("/api/v1/energia", json={"nivel": 7}).status_code == 422
        energia.add.assert_not_called()

    def test_dice_si_ya_reporto_hoy(self, client, energia):
        energia.reported_today.return_value = True

        respuesta = client.get("/api/v1/energia/hoy")

        assert respuesta.status_code == 200
        assert respuesta.json() == {"reportado": True}

    def test_exige_token(self, energia):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_energia_repository] = lambda: energia

        with TestClient(app) as c:
            assert c.get("/api/v1/energia").status_code == 401


class TestElDiaDelUsuario:
    """"Hoy" es una afirmacion sobre el dia de quien pregunta.

    Con medianoche UTC, alguien en Lima que reporta su energia a las 20:00 del
    lunes queda registrado el martes: a las 19:00 locales el servidor ya cree
    que cambio el dia. Es el mismo error que ya se corrigio en /aplicar y en
    /logros, y el comentario del repositorio lo anticipaba —"el dia que
    importe, viaja como parametro".
    """

    def test_el_desfase_del_cliente_llega_al_repositorio(self, client, energia):
        energia.reported_today.return_value = False

        client.get("/api/v1/energia/hoy?desfase_utc_minutos=-300")

        energia.reported_today.assert_called_once_with(TOKEN, -300)

    def test_sin_desfase_se_asume_UTC(self, client, energia):
        # Compatible con clientes viejos que no lo mandan.
        energia.reported_today.return_value = False

        client.get("/api/v1/energia/hoy")

        energia.reported_today.assert_called_once_with(TOKEN, 0)

    def test_un_desfase_imposible_se_rechaza(self, client):
        assert (
            client.get("/api/v1/energia/hoy?desfase_utc_minutos=5000").status_code
            == 422
        )
