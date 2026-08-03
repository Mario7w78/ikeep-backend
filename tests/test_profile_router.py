"""Tests del perfil y los ajustes de planificacion."""

from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain.entities.profile import Perfil
from domain.entities.user_settings import AjustesUsuario
from infrastructure.adapters.inbound.api.auth import (
    AuthenticatedUser,
    get_current_user,
)
from infrastructure.adapters.inbound.api.v1.activities_router import get_access_token
from infrastructure.adapters.inbound.api.v1.profile_router import (
    get_ajustes_repository,
    get_perfil_repository,
    router,
)

USUARIO = AuthenticatedUser(id="usuario-1", email="alguien@ejemplo.com")
TOKEN = "el-jwt-del-usuario"

PERFIL_COMPLETO = Perfil(
    id="usuario-1",
    nombre_usuario="Mario",
    nivel_energia=2,
    hora_despertar="07:00",
    hora_dormir="23:00",
)


@pytest.fixture
def perfiles():
    return Mock()


@pytest.fixture
def ajustes():
    return Mock()


@pytest.fixture
def client(perfiles, ajustes):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: USUARIO
    app.dependency_overrides[get_access_token] = lambda: TOKEN
    app.dependency_overrides[get_perfil_repository] = lambda: perfiles
    app.dependency_overrides[get_ajustes_repository] = lambda: ajustes

    with TestClient(app) as c:
        yield c


class TestPerfil:
    def test_devuelve_el_perfil_guardado(self, client, perfiles):
        perfiles.get.return_value = PERFIL_COMPLETO

        respuesta = client.get("/api/v1/perfil")

        assert respuesta.status_code == 200
        assert respuesta.json()["username"] == "Mario"
        assert respuesta.json()["is_complete"] is True

    def test_sin_fila_devuelve_perfil_vacio_no_404(self, client, perfiles):
        """Un onboarding sin terminar es un estado normal, no un error."""
        perfiles.get.return_value = None

        respuesta = client.get("/api/v1/perfil")

        assert respuesta.status_code == 200
        assert respuesta.json()["id"] == "usuario-1"
        assert respuesta.json()["is_complete"] is False

    def test_un_perfil_a_medias_no_esta_completo(self, client, perfiles):
        perfiles.get.return_value = Perfil(id="usuario-1", nombre_usuario="Mario")

        assert client.get("/api/v1/perfil").json()["is_complete"] is False

    def test_guardar_usa_el_id_del_token(self, client, perfiles):
        perfiles.save.return_value = PERFIL_COMPLETO

        client.put(
            "/api/v1/perfil",
            json={
                "username": "Mario",
                "energy_level": 2,
                "wake_up_time": "07:00",
                "sleep_time": "23:00",
            },
        )

        assert perfiles.save.call_args[0][1].id == "usuario-1"

    def test_rechaza_nivel_de_energia_invalido(self, client, perfiles):
        respuesta = client.put("/api/v1/perfil", json={"energy_level": 9})

        assert respuesta.status_code == 422
        perfiles.save.assert_not_called()

    def test_limpiar_vacia_y_devuelve_incompleto(self, client, perfiles):
        respuesta = client.delete("/api/v1/perfil")

        assert respuesta.status_code == 200
        assert respuesta.json()["is_complete"] is False
        assert respuesta.json()["username"] is None
        perfiles.clear.assert_called_once_with(TOKEN)

    def test_exige_token(self, perfiles):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_perfil_repository] = lambda: perfiles

        with TestClient(app) as c:
            assert c.get("/api/v1/perfil").status_code == 401


class TestAjustes:
    def test_devuelve_los_ajustes(self, client, ajustes):
        ajustes.get.return_value = AjustesUsuario(
            propietario_id="usuario-1", inicio_dia=420, fin_dia=1380
        )

        respuesta = client.get("/api/v1/ajustes")

        assert respuesta.status_code == 200
        assert respuesta.json()["start_hour"] == 420
        assert respuesta.json()["end_hour"] == 1380

    def test_sin_fila_devuelve_los_defaults(self, client, ajustes):
        ajustes.get.return_value = AjustesUsuario(propietario_id="usuario-1")

        respuesta = client.get("/api/v1/ajustes")

        assert respuesta.json()["start_hour"] == 240
        assert respuesta.json()["end_hour"] == 1320

    def test_el_patch_solo_manda_lo_recibido(self, client, ajustes):
        """Cambiar la hora de inicio no debe tocar el resto."""
        ajustes.patch.return_value = AjustesUsuario(
            propietario_id="usuario-1", inicio_dia=420
        )

        client.patch("/api/v1/ajustes", json={"start_hour": 420})

        assert ajustes.patch.call_args[0][2] == {"inicio_dia": 420}

    def test_un_null_explicito_si_se_manda(self, client, ajustes):
        """Mandar null borra el override por dia; omitirlo no lo toca."""
        ajustes.patch.return_value = AjustesUsuario(propietario_id="usuario-1")

        client.patch("/api/v1/ajustes", json={"per_day_start_hours": None})

        assert ajustes.patch.call_args[0][2] == {"inicio_por_dia": None}

    def test_un_patch_vacio_no_cambia_nada(self, client, ajustes):
        ajustes.patch.return_value = AjustesUsuario(propietario_id="usuario-1")

        client.patch("/api/v1/ajustes", json={})

        assert ajustes.patch.call_args[0][2] == {}

    def test_rechaza_hora_fuera_de_rango(self, client, ajustes):
        respuesta = client.patch("/api/v1/ajustes", json={"start_hour": 5000})

        assert respuesta.status_code == 422
        ajustes.patch.assert_not_called()

    def test_exige_token(self, ajustes):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_ajustes_repository] = lambda: ajustes

        with TestClient(app) as c:
            assert c.get("/api/v1/ajustes").status_code == 401
