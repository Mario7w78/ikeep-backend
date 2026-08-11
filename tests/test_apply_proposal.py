"""Aplicar una propuesta confirmada de punta a punta.

Lo que antes eran tres viajes de red orquestados por el cliente, con la
compensacion escrita a mano en un store de Zustand.
"""

import pytest

from domain.entities.user_activity import ActividadUsuario
from domain.entities.user_settings import AjustesUsuario
from domain.services.scheduling.apply_proposal import ErrorAlAplicar, aplicar


class BloqueFalso:
    def __init__(self, id_actividad="1754000000000-1-Martes-0", dia=1, inicio=600, fin=720):
        self.id_actividad = id_actividad
        self.nombre = "Calculo"
        self.tipo = "clase"
        self.dia = dia
        self.hora_inicio = inicio
        self.hora_fin = fin


class ResultadoFalso:
    def __init__(self, bloques=None):
        self.estado = "OPTIMO"
        self.mensaje = "listo"
        self.recomendaciones = []
        self.tareas_omitidas = []
        self.bloques = bloques if bloques is not None else [BloqueFalso()]


def actividad(id_="1754000000000", nombre="Calculo") -> ActividadUsuario:
    return ActividadUsuario(
        id=id_,
        propietario_id="user-1",
        nombre=nombre,
        tipo="FIXED",
        identidad="clase",
        dias_habilitados=["Martes"],
        config_por_dia={
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
    )


class ReposFalsos:
    def __init__(self, existentes=None, generar_falla=False, guardar_falla=False):
        self.guardadas = {a.id: a for a in (existentes or [])}
        self.borradas: list[str] = []
        self.horarios_guardados: list = []
        self.solicitudes: list = []
        self.generar_falla = generar_falla
        self.guardar_falla = guardar_falla

    def actividades(self):
        return list(self.guardadas.values())

    def guardar_actividad(self, act):
        if self.guardar_falla:
            raise RuntimeError("la base dijo que no")
        self.guardadas[act.id] = act

    def borrar_actividad(self, activity_id):
        self.borradas.append(activity_id)
        self.guardadas.pop(activity_id, None)

    def obtener_actividad(self, activity_id):
        return self.guardadas.get(activity_id)

    def ajustes(self):
        return AjustesUsuario(propietario_id="user-1")

    def generar(self, solicitud):
        self.solicitudes.append(solicitud)
        if self.generar_falla:
            raise RuntimeError("el solver no pudo")
        return ResultadoFalso()

    def guardar_horario(self, resultado):
        self.horarios_guardados.append(resultado)


class TestCrear:
    def test_guarda_la_actividad_y_el_horario_en_una_sola_pasada(self):
        repos = ReposFalsos()

        aplicar(repos, tipo="crear", actividad=actividad(), desfase_utc_minutos=-300)

        assert "1754000000000" in repos.guardadas
        assert len(repos.horarios_guardados) == 1

    def test_el_solver_recibe_la_hora_local(self):
        repos = ReposFalsos()

        aplicar(repos, tipo="crear", actividad=actividad(), desfase_utc_minutos=-300)

        fija = repos.solicitudes[0]["actividades_fijas"][0]
        assert fija["hora_inicio"] == 600

    def test_el_bloque_guardado_lleva_la_actividad_original(self):
        repos = ReposFalsos()

        resultado = aplicar(repos, tipo="crear", actividad=actividad())

        programada = resultado.actividades_programadas[0]
        assert programada["activity"]["id"] == "1754000000000"
        assert programada["assignedStartTime"] == "10:00"

    def test_un_id_con_guiones_igual_encuentra_su_actividad(self):
        # El cliente corta en el primer guion. Eso solo funciona mientras los
        # ids sean puros digitos: con UUID cada bloque perderia su actividad.
        repos = ReposFalsos()
        repos.generar = lambda s: ResultadoFalso(
            [BloqueFalso(id_actividad="a1b2-c3d4-1-Martes-0")]
        )

        resultado = aplicar(repos, tipo="crear", actividad=actividad(id_="a1b2-c3d4"))

        assert resultado.actividades_programadas[0]["activity"]["id"] == "a1b2-c3d4"

    def test_un_bloque_de_traslado_va_sin_actividad(self):
        # No corresponde a ninguna definicion del usuario.
        repos = ReposFalsos()
        repos.generar = lambda s: ResultadoFalso([BloqueFalso(id_actividad="traslado-x")])

        resultado = aplicar(repos, tipo="crear", actividad=actividad())

        assert resultado.actividades_programadas[0]["activity"] is None


class TestEliminar:
    def test_borra_y_regenera(self):
        repos = ReposFalsos(existentes=[actividad()])

        aplicar(repos, tipo="eliminar", activity_id="1754000000000")

        assert repos.borradas == ["1754000000000"]
        assert len(repos.horarios_guardados) == 1


class TestRegenerar:
    def test_no_toca_las_actividades(self):
        repos = ReposFalsos(existentes=[actividad()])

        aplicar(repos, tipo="regenerar")

        assert repos.borradas == []
        assert len(repos.horarios_guardados) == 1


class TestCompensacion:
    """Si el solver falla despues de tocar la base, la base vuelve atras."""

    def test_una_creacion_fallida_no_deja_la_actividad(self):
        repos = ReposFalsos(generar_falla=True)

        with pytest.raises(ErrorAlAplicar):
            aplicar(repos, tipo="crear", actividad=actividad())

        assert "1754000000000" not in repos.guardadas

    def test_una_modificacion_fallida_restaura_la_anterior(self):
        repos = ReposFalsos(existentes=[actividad(nombre="Calculo")], generar_falla=True)

        with pytest.raises(ErrorAlAplicar):
            aplicar(repos, tipo="modificar", actividad=actividad(nombre="Calculo II"))

        assert repos.guardadas["1754000000000"].nombre == "Calculo"

    def test_no_se_guarda_horario_si_fallo(self):
        repos = ReposFalsos(generar_falla=True)

        with pytest.raises(ErrorAlAplicar):
            aplicar(repos, tipo="crear", actividad=actividad())

        assert repos.horarios_guardados == []

    def test_si_falla_antes_de_tocar_nada_el_error_sale_tal_cual(self):
        # Sin cambio que deshacer, envolverlo solo escondería la causa.
        repos = ReposFalsos(generar_falla=True)

        with pytest.raises(RuntimeError, match="el solver no pudo"):
            aplicar(repos, tipo="regenerar")


class TestUnSoloViaje:
    def test_devuelve_las_actividades_para_no_pedirlas_de_nuevo(self):
        # Sin esto el cliente tendria que hacer un GET despues de aplicar, y
        # el endpoint existe justamente para que sea una sola llamada.
        repos = ReposFalsos()

        resultado = aplicar(repos, tipo="crear", actividad=actividad())

        assert [a.id for a in resultado.actividades] == ["1754000000000"]
