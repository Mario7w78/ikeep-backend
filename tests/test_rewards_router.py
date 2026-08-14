"""Completar actividades, racha y progreso.

Sin el evento "termine esto" no hay ciclo: ni racha, ni progreso, ni nada que
la mascota pueda celebrar.
"""

from datetime import date, timedelta
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
from domain.ports.outbound.completion_repository_port import ConteosPorArea
from domain.services.rewards.completion import EstadoCompletado, OrigenCompletado
from infrastructure.adapters.inbound.api.v1.rewards_router import (
    get_completions_repository,
    router,
)
from infrastructure.adapters.inbound.api.v1.stored_schedule_router import (
    get_energia_repository,
)

USUARIO = AuthenticatedUser(id="usuario-1", email="alguien@ejemplo.com")
TOKEN = "el-jwt"

# Las fechas son relativas a hoy y no fijas. Una constante clavada
# —"2026-08-11"— funciona el dia que se escribe y falla sola tres dias
# despues, cuando cae fuera de la ventana de gracia: el test empieza a
# reprobar sin que nadie haya tocado el codigo.
HOY = date.today()
HOY_ISO = HOY.isoformat()
NOMBRE_DEL_DIA = [
    "Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo",
][HOY.weekday()]
def dias_atras(*cuantos: int) -> set:
    """Dias de presencia contados desde hoy.

    Fechas fijas volverian estos tests dependientes de cuando se corren: una
    racha se mide contra hoy, y {9, 10, 11 de agosto} deja de ser una racha
    el 14.
    """
    return {HOY - timedelta(days=n) for n in cuantos}


OTRO_DIA = [
    "Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo",
][(HOY.weekday() + 3) % 7]


def actividad(id_="act-1", dias=(NOMBRE_DEL_DIA,), opcional=False):
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
def energia():
    repo = Mock()
    repo.dias_con_registro.return_value = set()
    return repo


@pytest.fixture
def actividades():
    repo = Mock()
    repo.list_all.return_value = []
    return repo


@pytest.fixture
def client(completados, actividades, energia):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: USUARIO
    app.dependency_overrides[get_access_token] = lambda: TOKEN
    app.dependency_overrides[get_completions_repository] = lambda: completados
    app.dependency_overrides[get_repository] = lambda: actividades
    app.dependency_overrides[get_energia_repository] = lambda: energia

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
                json={"activity_id": "act-1", "fecha": HOY_ISO},
            )

        assert respuesta.status_code == 401


class TestCompletar:
    def test_marca_con_el_dueno_del_token(self, client, completados):
        # El dueno no puede salir del cuerpo: seria escribir en la cuenta ajena.
        client.post(
            "/api/v1/logros/completar",
            json={"activity_id": "act-1", "fecha": HOY_ISO},
        )

        completados.marcar.assert_called_once_with(
            TOKEN, "usuario-1", "act-1", HOY, EstadoCompletado.HECHA,
            OrigenCompletado.MANUAL,
        )

    def test_descompletar_deshace(self, client, completados):
        client.post(
            "/api/v1/logros/descompletar",
            json={"activity_id": "act-1", "fecha": HOY_ISO},
        )

        completados.desmarcar.assert_called_once_with(
            TOKEN, "act-1", HOY
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
            actividad("act-1", dias=(NOMBRE_DEL_DIA,)),
            actividad("act-2", dias=(OTRO_DIA,)),
        ]

        cuerpo = client.get(f"/api/v1/logros/resumen?fecha={HOY_ISO}").json()

        assert cuerpo["progreso"]["total"] == 1

    def test_las_de_dia_opcional_cuentan_una_vez(self, client, actividades):
        # El solver elige el dia: sumarlas en cada dia habilitado inflaria el
        # total de toda la semana.
        actividades.list_all.return_value = [
            actividad("act-1", dias=("Lunes", "Martes", "Jueves"), opcional=True)
        ]

        cuerpo = client.get(f"/api/v1/logros/resumen?fecha={HOY_ISO}").json()

        assert cuerpo["progreso"]["total"] == 1

    def test_devuelve_que_se_completo_para_marcarlo_en_la_lista(
        self, client, completados, actividades
    ):
        actividades.list_all.return_value = [actividad("act-1")]
        completados.del_dia.return_value = ["act-1"]

        cuerpo = client.get(f"/api/v1/logros/resumen?fecha={HOY_ISO}").json()

        assert cuerpo["progreso"]["completados_ids"] == ["act-1"]
        assert cuerpo["progreso"]["terminado"] is True

    def test_la_racha_sale_de_los_dias_en_que_aparecio(self, client, energia):
        # Presencia, no rendimiento: cuenta los dias en que dijo como estaba.
        # Incluye hoy, asi que la racha no esta en riesgo: en riesgo significa
        # justamente que todavia no aparecio hoy.
        energia.dias_con_registro.return_value = dias_atras(0, 1, 2)

        cuerpo = client.get(f"/api/v1/logros/resumen?fecha={HOY_ISO}").json()

        assert cuerpo["racha"]["actual"] == 3
        assert cuerpo["racha"]["en_riesgo"] is False

    def test_un_dia_sin_nada_programado_esta_completo(self, client):
        # Mostrar 0% a quien no tenia nada lo haria sentir en falta por un dia
        # libre.
        cuerpo = client.get(f"/api/v1/logros/resumen?fecha={HOY_ISO}").json()

        assert cuerpo["progreso"]["fraccion"] == 1.0
        assert cuerpo["progreso"]["terminado"] is False

    def test_racha_y_progreso_van_juntos_en_un_viaje(self, client):
        # Se muestran en la misma pantalla; separarlos serian dos llamadas
        # contra un servidor que tarda en despertar.
        cuerpo = client.get(f"/api/v1/logros/resumen?fecha={HOY_ISO}").json()

        assert "racha" in cuerpo and "progreso" in cuerpo


class TestHistorial:
    def test_devuelve_los_dias_con_algo_hecho(self, client, completados):
        # Van en la misma respuesta que la racha porque el calculo de la
        # racha ya los trajo: pedirlos aparte repetiria la consulta.
        completados.dias_con_actividad.return_value = {
            date(2026, 8, 10),
            date(2026, 8, 11),
        }

        cuerpo = client.get(f"/api/v1/logros/resumen?fecha={HOY_ISO}").json()

        assert cuerpo["dias_completados"] == ["2026-08-10", "2026-08-11"]

    def test_vienen_ordenados(self, client, completados):
        completados.dias_con_actividad.return_value = {
            date(2026, 8, 11),
            date(2026, 8, 1),
            date(2026, 8, 5),
        }

        cuerpo = client.get(f"/api/v1/logros/resumen?fecha={HOY_ISO}").json()

        assert cuerpo["dias_completados"] == ["2026-08-01", "2026-08-05", "2026-08-11"]

    def test_sin_historial_es_una_lista_vacia(self, client):
        cuerpo = client.get(f"/api/v1/logros/resumen?fecha={HOY_ISO}").json()

        assert cuerpo["dias_completados"] == []


class TestLaRachaEsPresencia:
    """Aparecer y decir como estas, no cumplir.

    Antes contaba dias con al menos un completado, y se rompia justo en la
    semana de examenes — el momento en que mas importa que la app no castigue.
    """

    def test_una_semana_sin_completar_nada_conserva_la_racha(self, client, energia, completados):
        energia.dias_con_registro.return_value = dias_atras(1, 2, 3)
        completados.dias_con_actividad.return_value = set()   # no hizo nada

        cuerpo = client.get(f"/api/v1/logros/resumen?fecha={HOY_ISO}").json()

        assert cuerpo["racha"]["actual"] == 3

    def test_completar_sin_aparecer_no_da_racha(self, client, energia, completados):
        # No deberia poder pasar, pero si pasara la racha mide presencia.
        energia.dias_con_registro.return_value = set()
        completados.dias_con_actividad.return_value = dias_atras(1, 2)

        cuerpo = client.get(f"/api/v1/logros/resumen?fecha={HOY_ISO}").json()

        assert cuerpo["racha"]["actual"] == 0

    def test_el_historial_sigue_mostrando_lo_hecho(self, client, energia, completados):
        # Son dos preguntas distintas y la pantalla muestra las dos.
        energia.dias_con_registro.return_value = dias_atras(1)
        completados.dias_con_actividad.return_value = dias_atras(2)

        cuerpo = client.get(f"/api/v1/logros/resumen?fecha={HOY_ISO}").json()

        assert cuerpo["racha"]["actual"] == 1
        assert cuerpo["dias_completados"] == [(HOY - timedelta(days=2)).isoformat()]

    def test_el_desfase_del_cliente_llega_a_la_consulta(self, client, energia):
        client.get(f"/api/v1/logros/resumen?fecha={HOY_ISO}&desfase_utc_minutos=-300")

        assert energia.dias_con_registro.call_args[0][2] == -300


class TestLaVentanaParaAfirmar:
    """Cuando se puede todavia decir algo sobre un dia.

    Marcar una semana entera hacia atras es ficcion, y la ficcion envenena el
    unico dato que esta app puede producir y ninguna app de habitos puede: la
    correlacion entre energia y cumplimiento.
    """

    def test_no_se_puede_marcar_el_futuro(self, client, completados):
        # Es la unica trampa que vale la pena cerrar, y se cierra sola.
        respuesta = client.post(
            "/api/v1/logros/completar",
            json={"activity_id": "act-1", "fecha": "2099-01-01"},
        )

        assert respuesta.status_code == 422
        completados.marcar.assert_not_called()

    def test_fuera_del_plazo_se_rechaza(self, client, completados):
        respuesta = client.post(
            "/api/v1/logros/completar",
            json={"activity_id": "act-1", "fecha": "2020-01-01"},
        )

        assert respuesta.status_code == 422
        completados.marcar.assert_not_called()

    def test_el_rechazo_explica_cual_de_los_dos_fue(self, client):
        # "Ese dia ya cerro" y "todavia no paso" piden mensajes distintos, y
        # el cliente no deberia adivinar cual mostrar.
        cuerpo = client.post(
            "/api/v1/logros/completar",
            json={"activity_id": "act-1", "fecha": "2099-01-01"},
        ).json()

        assert cuerpo["detail"]["motivo"] == "futuro"


class TestDecirQueNo:
    """"No la hice" y "no se" son datos distintos."""

    def test_se_puede_decir_que_no_se_hizo(self, client, completados):
        hoy = date.today().isoformat()

        respuesta = client.post(
            "/api/v1/logros/completar",
            json={"activity_id": "act-1", "fecha": hoy, "estado": "no_hecha"},
        )

        assert respuesta.status_code == 204
        _, _, _, _, estado, _ = completados.marcar.call_args.args
        assert estado.value == "no_hecha"

    def test_por_defecto_lo_que_se_afirma_es_que_si(self, client, completados):
        client.post(
            "/api/v1/logros/completar",
            json={"activity_id": "act-1", "fecha": date.today().isoformat()},
        )

        _, _, _, _, estado, origen = completados.marcar.call_args.args
        assert estado.value == "hecha"
        assert origen.value == "manual"

    def test_no_existe_un_origen_automatico(self, client):
        # Nunca se marca sola. Si el dato se rellena con suposiciones deja de
        # valer, y no hay a quien mentirle mas que a uno mismo.
        respuesta = client.post(
            "/api/v1/logros/completar",
            json={
                "activity_id": "act-1",
                "fecha": date.today().isoformat(),
                "origen": "automatico",
            },
        )

        assert respuesta.status_code == 422


class TestElCierreDelDia:
    """Abrir a las once de la noche con el dia entero sin marcar.

    Es el caso mas frecuente, no el raro. Cuatro casillas para tildar es
    trabajo administrativo; la respuesta correcta es una pregunta con tres
    salidas.
    """

    def test_hice_todo_resuelve_el_dia_de_un_toque(self, client, completados, actividades):
        actividades.list_all.return_value = [
            actividad("act-1", dias=(NOMBRE_DEL_DIA,)),
            actividad("act-2", dias=(NOMBRE_DEL_DIA,)),
        ]

        respuesta = client.post(
            "/api/v1/logros/cerrar-dia",
            json={"fecha": HOY_ISO, "respuesta": "todo"},
        )

        assert respuesta.status_code == 200
        marcadas = {c.args[2] for c in completados.marcar.call_args_list}
        assert marcadas == {"act-1", "act-2"}

    def test_hice_algunas_solo_toca_las_dichas(self, client, completados, actividades):
        actividades.list_all.return_value = [
            actividad("act-1", dias=(NOMBRE_DEL_DIA,)),
            actividad("act-2", dias=(NOMBRE_DEL_DIA,)),
        ]

        client.post(
            "/api/v1/logros/cerrar-dia",
            json={"fecha": HOY_ISO, "respuesta": "algunas", "hechas": ["act-1"]},
        )

        por_id = {c.args[2]: c.args[4].value for c in completados.marcar.call_args_list}
        assert por_id == {"act-1": "hecha", "act-2": "no_hecha"}

    def test_un_dia_dificil_no_pregunta_nada(self, client, completados, actividades):
        # Cero completadas, cero preguntas, cero penalizacion. Es el boton que
        # ninguna app de habitos tiene, y sin el la unica salida honesta es
        # cerrar la app y no volver.
        actividades.list_all.return_value = [actividad("act-1", dias=(NOMBRE_DEL_DIA,))]

        respuesta = client.post(
            "/api/v1/logros/cerrar-dia",
            json={"fecha": HOY_ISO, "respuesta": "dificil"},
        )

        assert respuesta.status_code == 200
        completados.marcar.assert_not_called()

    def test_un_dia_dificil_deja_todo_sin_resolver_no_en_no_hecha(
        self, client, completados, actividades
    ):
        # Sin resolver no rompe la racha ni hace crecer al sapo. No suma, pero
        # tampoco resta: es exactamente lo que un dia dificil merece.
        actividades.list_all.return_value = [actividad("act-1", dias=(NOMBRE_DEL_DIA,))]

        client.post(
            "/api/v1/logros/cerrar-dia",
            json={"fecha": HOY_ISO, "respuesta": "dificil"},
        )

        completados.desmarcar.assert_not_called()

    def test_el_cierre_se_guarda_con_su_origen(self, client, completados, actividades):
        actividades.list_all.return_value = [actividad("act-1", dias=(NOMBRE_DEL_DIA,))]

        client.post(
            "/api/v1/logros/cerrar-dia",
            json={"fecha": HOY_ISO, "respuesta": "todo"},
        )

        assert completados.marcar.call_args.args[5].value == "cierre"

    def test_no_se_puede_cerrar_un_dia_que_no_llego(self, client, completados):
        respuesta = client.post(
            "/api/v1/logros/cerrar-dia",
            json={"fecha": "2099-01-01", "respuesta": "todo"},
        )

        assert respuesta.status_code == 422
        completados.marcar.assert_not_called()


class TestElEquilibrio:
    """Los petalos. Lo que la racha nunca va a decirte."""

    def test_devuelve_las_cinco_areas_aunque_esten_en_cero(self, client, completados):
        # Omitir las vacias dejaria al cliente adivinando si un area falta por
        # no haber datos o porque el usuario nunca la toco — y eso ultimo es
        # justamente lo que la pantalla existe para mostrar.
        completados.conteos_por_area.return_value = ConteosPorArea(
            historico={"estudio": 12}, recientes={"estudio": 4}
        )

        cuerpo = client.get(f"/api/v1/logros/equilibrio?fecha={HOY_ISO}").json()

        assert cuerpo["historico"] == {
            "estudio": 12, "trabajo": 0, "cuerpo": 0, "vinculos": 0, "yo": 0,
        }
        assert cuerpo["recientes"]["estudio"] == 4

    def test_el_tamano_y_la_forma_viajan_por_separado(self, client, completados):
        # El petalo nunca encoge —eso es `historico`— pero la flor si cambia
        # de forma, y eso es `recientes`. Un solo numero responderia mal a
        # las dos preguntas.
        completados.conteos_por_area.return_value = ConteosPorArea(
            historico={"cuerpo": 40}, recientes={}
        )

        cuerpo = client.get(f"/api/v1/logros/equilibrio?fecha={HOY_ISO}").json()

        assert cuerpo["historico"]["cuerpo"] == 40
        assert cuerpo["recientes"]["cuerpo"] == 0

    def test_no_decide_como_se_dibuja_la_flor(self, client, completados):
        # Devuelve conteos, no aperturas: como se abre cada petalo va a
        # cambiar con el arte, y eso no deberia pedir un redespliegue.
        completados.conteos_por_area.return_value = ConteosPorArea(
            historico={"cuerpo": 3}, recientes={"cuerpo": 3}
        )

        cuerpo = client.get(f"/api/v1/logros/equilibrio?fecha={HOY_ISO}").json()

        assert all(isinstance(v, int) for v in cuerpo["recientes"].values())

    def test_mira_una_ventana_acotada_hacia_atras(self, client, completados):
        # Sin ventana, una temporada de examenes de hace dos anos definiria la
        # flor para siempre.
        completados.conteos_por_area.return_value = ConteosPorArea()

        client.get(f"/api/v1/logros/equilibrio?fecha={HOY_ISO}")

        desde = completados.conteos_por_area.call_args.args[1]
        assert (HOY - desde).days == 90
