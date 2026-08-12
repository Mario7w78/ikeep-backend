"""Completar actividades, racha y progreso.

Sin el evento "termine esto" no hay ciclo: ni racha, ni progreso, ni nada que
la mascota pueda celebrar.
"""

from datetime import date
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
)
from infrastructure.adapters.inbound.api.v1.rewards_router import (
    get_completions_repository,
    router,
)

USUARIO = AuthenticatedUser(id="usuario-1", email="alguien@ejemplo.com")
TOKEN = "el-jwt"
# 2026-08-11 es martes.
MARTES = "2026-08-11"


def actividad(id_="act-1", dias=("Martes",), opcional=False):
    return ActividadUsuario(
        id=id_,
        propietario_id="usuario-1",
        nombre="Calculo",
        tipo="FIXED",
        dias_habilitados=list(dias),
        dia_opcional=opcional,
    )


@pytest.fixture
def completados():
    repo = Mock()
    repo.del_dia.return_value = []
    repo.dias_con_actividad.return_value = set()
    return repo


@pytest.fixture
def actividades():
    repo = Mock()
    repo.list_all.return_value = []
    return repo


@pytest.fixture
def client(completados, actividades):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: USUARIO
    app.dependency_overrides[get_access_token] = lambda: TOKEN
    app.dependency_overrides[get_completions_repository] = lambda: completados
    app.dependency_overrides[get_repository] = lambda: actividades

    with TestClient(app) as c:
        yield c


class TestAutenticacion:
    def test_completar_exige_token(self, completados):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_completions_repository] = lambda: completados

        with TestClient(app) as c:
            respuesta = c.post(
                "/api/v1/logros/completar",
                json={"activity_id": "act-1", "fecha": MARTES},
            )

        assert respuesta.status_code == 401


class TestCompletar:
    def test_marca_con_el_dueno_del_token(self, client, completados):
        # El dueno no puede salir del cuerpo: seria escribir en la cuenta ajena.
        client.post(
            "/api/v1/logros/completar",
            json={"activity_id": "act-1", "fecha": MARTES},
        )

        completados.marcar.assert_called_once_with(
            TOKEN, "usuario-1", "act-1", date(2026, 8, 11)
        )

    def test_descompletar_deshace(self, client, completados):
        client.post(
            "/api/v1/logros/descompletar",
            json={"activity_id": "act-1", "fecha": MARTES},
        )

        completados.desmarcar.assert_called_once_with(
            TOKEN, "act-1", date(2026, 8, 11)
        )

    def test_una_fecha_invalida_se_rechaza(self, client):
        respuesta = client.post(
            "/api/v1/logros/completar",
            json={"activity_id": "act-1", "fecha": "el martes"},
        )

        assert respuesta.status_code == 422


class TestResumen:
    def test_cuenta_las_actividades_del_dia(self, client, actividades):
        actividades.list_all.return_value = [
            actividad("act-1", dias=("Martes",)),
            actividad("act-2", dias=("Jueves",)),
        ]

        cuerpo = client.get(f"/api/v1/logros/resumen?fecha={MARTES}").json()

        assert cuerpo["progreso"]["total"] == 1

    def test_las_de_dia_opcional_cuentan_una_vez(self, client, actividades):
        # El solver elige el dia: sumarlas en cada dia habilitado inflaria el
        # total de toda la semana.
        actividades.list_all.return_value = [
            actividad("act-1", dias=("Lunes", "Martes", "Jueves"), opcional=True)
        ]

        cuerpo = client.get(f"/api/v1/logros/resumen?fecha={MARTES}").json()

        assert cuerpo["progreso"]["total"] == 1

    def test_devuelve_que_se_completo_para_marcarlo_en_la_lista(
        self, client, completados, actividades
    ):
        actividades.list_all.return_value = [actividad("act-1")]
        completados.del_dia.return_value = ["act-1"]

        cuerpo = client.get(f"/api/v1/logros/resumen?fecha={MARTES}").json()

        assert cuerpo["progreso"]["completados_ids"] == ["act-1"]
        assert cuerpo["progreso"]["terminado"] is True

    def test_la_racha_sale_de_los_dias_con_algo_hecho(self, client, completados):
        completados.dias_con_actividad.return_value = {
            date(2026, 8, 9),
            date(2026, 8, 10),
            date(2026, 8, 11),
        }

        cuerpo = client.get(f"/api/v1/logros/resumen?fecha={MARTES}").json()

        assert cuerpo["racha"]["actual"] == 3
        assert cuerpo["racha"]["en_riesgo"] is False

    def test_un_dia_sin_nada_programado_esta_completo(self, client):
        # Mostrar 0% a quien no tenia nada lo haria sentir en falta por un dia
        # libre.
        cuerpo = client.get(f"/api/v1/logros/resumen?fecha={MARTES}").json()

        assert cuerpo["progreso"]["fraccion"] == 1.0
        assert cuerpo["progreso"]["terminado"] is False

    def test_racha_y_progreso_van_juntos_en_un_viaje(self, client):
        # Se muestran en la misma pantalla; separarlos serian dos llamadas
        # contra un servidor que tarda en despertar.
        cuerpo = client.get(f"/api/v1/logros/resumen?fecha={MARTES}").json()

        assert "racha" in cuerpo and "progreso" in cuerpo


class TestHistorial:
    def test_devuelve_los_dias_con_algo_hecho(self, client, completados):
        # Van en la misma respuesta que la racha porque el calculo de la
        # racha ya los trajo: pedirlos aparte repetiria la consulta.
        completados.dias_con_actividad.return_value = {
            date(2026, 8, 10),
            date(2026, 8, 11),
        }

        cuerpo = client.get(f"/api/v1/logros/resumen?fecha={MARTES}").json()

        assert cuerpo["dias_completados"] == ["2026-08-10", "2026-08-11"]

    def test_vienen_ordenados(self, client, completados):
        completados.dias_con_actividad.return_value = {
            date(2026, 8, 11),
            date(2026, 8, 1),
            date(2026, 8, 5),
        }

        cuerpo = client.get(f"/api/v1/logros/resumen?fecha={MARTES}").json()

        assert cuerpo["dias_completados"] == ["2026-08-01", "2026-08-05", "2026-08-11"]

    def test_sin_historial_es_una_lista_vacia(self, client):
        cuerpo = client.get(f"/api/v1/logros/resumen?fecha={MARTES}").json()

        assert cuerpo["dias_completados"] == []
