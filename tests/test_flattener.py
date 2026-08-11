"""Aplanado de actividades del usuario a entrada del solver.

Lo que se prueba aca es la traduccion, no el solver: que cada definicion
produzca las unidades correctas, en la canasta correcta, con la hora que el
usuario ve.
"""

import pytest

from domain.entities.user_activity import ActividadUsuario
from domain.services.scheduling.flattener import aplanar, minuto_del_dia

LIMA = -300  # UTC-5, en minutos


def actividad(**over) -> ActividadUsuario:
    base = dict(
        id="act-1",
        propietario_id="user-1",
        nombre="Calculo",
        tipo="FIXED",
        identidad="clase",
        prioridad=3,
        dificultad="media",
        dias_habilitados=["Martes"],
        config_por_dia={
            "Martes": {
                "groupId": 1,
                "partitions": [
                    {
                        "startHour": "2026-08-03T15:00:00.000Z",
                        "endHour": "2026-08-03T17:00:00.000Z",
                        "durationTime": 120,
                        "travelTo": 0,
                        "travelFrom": 0,
                    }
                ],
                "preferredStartTime": None,
                "preferredEndTime": None,
            }
        },
    )
    base.update(over)
    return ActividadUsuario(**base)


class TestMinutoDelDia:
    def test_usa_la_hora_local_y_no_la_utc(self):
        # Una clase a las 10:00 en Lima viaja como 15:00Z. Leerla tal cual la
        # pondria cinco horas mas tarde en el horario.
        assert minuto_del_dia("2026-08-03T15:00:00.000Z", LIMA) == 600

    def test_sin_desfase_es_la_hora_utc(self):
        assert minuto_del_dia("2026-08-03T15:00:00.000Z", 0) == 900

    def test_un_numero_ya_es_minuto_del_dia(self):
        assert minuto_del_dia(600, LIMA) == 600

    def test_cruzar_la_medianoche_no_da_negativo(self):
        assert minuto_del_dia("2026-08-03T02:00:00.000Z", LIMA) == 1260


class TestCanastas:
    def test_una_actividad_fija_va_a_fijas(self):
        resultado = aplanar([actividad()], LIMA)

        assert len(resultado.fijas) == 1
        assert resultado.ancla == []
        assert resultado.optimizables == []

    def test_una_flexible_va_a_optimizables(self):
        resultado = aplanar([actividad(tipo="FLEXIBLE")], LIMA)

        assert len(resultado.optimizables) == 1
        assert resultado.fijas == []

    def test_una_flexible_con_ancla_va_a_ancla(self):
        resultado = aplanar([actividad(tipo="FLEXIBLE", es_ancla=True)], LIMA)

        assert len(resultado.ancla) == 1
        assert resultado.optimizables == []

    def test_la_hora_que_llega_al_solver_es_la_local(self):
        resultado = aplanar([actividad()], LIMA)

        assert resultado.fijas[0]["hora_inicio"] == 600
        assert resultado.fijas[0]["hora_fin"] == 720


class TestUnaDefinicionVariasUnidades:
    def test_un_turno_por_dia_habilitado(self):
        config = {
            dia: {
                "groupId": 1,
                "partitions": [
                    {
                        "startHour": "2026-08-03T15:00:00.000Z",
                        "endHour": "2026-08-03T17:00:00.000Z",
                        "durationTime": 120,
                    }
                ],
            }
            for dia in ("Martes", "Jueves")
        }
        resultado = aplanar(
            [actividad(dias_habilitados=["Martes", "Jueves"], config_por_dia=config)],
            LIMA,
        )

        assert len(resultado.fijas) == 2
        assert {f["dia"] for f in resultado.fijas} == {1, 3}

    def test_varios_turnos_en_el_mismo_dia(self):
        config = {
            "Martes": {
                "groupId": 1,
                "partitions": [
                    {
                        "startHour": "2026-08-03T13:00:00.000Z",
                        "endHour": "2026-08-03T14:00:00.000Z",
                        "durationTime": 60,
                    },
                    {
                        "startHour": "2026-08-03T20:00:00.000Z",
                        "endHour": "2026-08-03T21:00:00.000Z",
                        "durationTime": 60,
                    },
                ],
            }
        }
        resultado = aplanar([actividad(config_por_dia=config)], LIMA)

        assert len(resultado.fijas) == 2
        assert [f["hora_inicio"] for f in resultado.fijas] == [480, 900]

    def test_los_ids_no_se_repiten(self):
        # El solver los usa como clave: repetirlos perderia unidades.
        config = {
            dia: {
                "groupId": 1,
                "partitions": [
                    {
                        "startHour": "2026-08-03T15:00:00.000Z",
                        "endHour": "2026-08-03T17:00:00.000Z",
                        "durationTime": 120,
                    }
                ],
            }
            for dia in ("Martes", "Jueves")
        }
        resultado = aplanar(
            [actividad(dias_habilitados=["Martes", "Jueves"], config_por_dia=config)],
            LIMA,
        )

        ids = [f["id"] for f in resultado.fijas]
        assert len(set(ids)) == len(ids)


class TestDiaOpcional:
    def test_no_lleva_dia_pero_si_los_permitidos(self):
        # El solver elige el dia: fijarle uno seria decidir por el.
        resultado = aplanar(
            [
                actividad(
                    tipo="FLEXIBLE",
                    dia_opcional=True,
                    dias_habilitados=["Martes", "Jueves"],
                )
            ],
            LIMA,
        )

        entrada = resultado.optimizables[0]
        assert "dia" not in entrada
        assert entrada["dias_permitidos"] == [1, 3]

    def test_una_sola_unidad_aunque_haya_varios_dias(self):
        resultado = aplanar(
            [
                actividad(
                    tipo="FLEXIBLE",
                    dia_opcional=True,
                    dias_habilitados=["Martes", "Jueves"],
                )
            ],
            LIMA,
        )

        assert len(resultado.optimizables) == 1


class TestDefinicionesIncompletas:
    """Una definicion a medias no puede dejar sin horario a todo el mundo."""

    def test_sin_dias_se_omite(self):
        resultado = aplanar([actividad(dias_habilitados=[], config_por_dia={})], LIMA)

        assert resultado.fijas == []

    def test_sin_config_del_dia_se_omite_ese_dia(self):
        resultado = aplanar(
            [actividad(dias_habilitados=["Martes", "Viernes"])], LIMA
        )

        assert len(resultado.fijas) == 1

    def test_un_dia_desconocido_no_rompe(self):
        resultado = aplanar([actividad(dias_habilitados=["Martes", "Feriado"])], LIMA)

        assert len(resultado.fijas) == 1

    def test_las_demas_actividades_se_aplanan_igual(self):
        resultado = aplanar(
            [actividad(id="rota", dias_habilitados=[], config_por_dia={}), actividad()],
            LIMA,
        )

        assert len(resultado.fijas) == 1
