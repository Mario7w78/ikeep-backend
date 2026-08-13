"""Expandir la plantilla semanal a fechas reales.

Hasta ahora el horario guardaba dias de la semana y se repetia para siempre.
Un parcial el 12 de noviembre no se podia representar, y "este martes no hay
clase" no tenia donde vivir.

Se guarda la regla y las excepciones, y las fechas se derivan al vuelo — que
es lo que hacen Google Calendar y el de Apple.
"""

from datetime import date

import pytest

from domain.entities.user_activity import ActividadUsuario
from domain.services.calendar.expansion import (
    Excepcion,
    Ocurrencia,
    expandir,
)


def actividad(**over) -> ActividadUsuario:
    base = dict(
        id="act-1",
        propietario_id="u1",
        nombre="Cálculo",
        tipo="FIXED",
        dias_habilitados=["Martes"],
        config_por_dia={"Martes": {"groupId": 1, "partitions": []}},
    )
    base.update(over)
    return ActividadUsuario(**base)


# Agosto 2026: el 4, 11, 18 y 25 son martes.
LUNES = date(2026, 8, 3)
DOMINGO = date(2026, 8, 30)


def fechas(ocurrencias: list[Ocurrencia]) -> list[date]:
    return [o.fecha for o in ocurrencias]


class TestLoQueSeRepite:
    def test_una_actividad_semanal_cae_en_todos_sus_dias(self):
        salida = expandir([actividad()], [], LUNES, DOMINGO)

        assert fechas(salida) == [
            date(2026, 8, 4), date(2026, 8, 11),
            date(2026, 8, 18), date(2026, 8, 25),
        ]

    def test_varios_dias_por_semana(self):
        a = actividad(
            dias_habilitados=["Martes", "Jueves"],
            config_por_dia={d: {"groupId": 1, "partitions": []} for d in ("Martes", "Jueves")},
        )

        salida = expandir([a], [], LUNES, date(2026, 8, 9))

        assert fechas(salida) == [date(2026, 8, 4), date(2026, 8, 6)]

    def test_respeta_el_rango_pedido(self):
        salida = expandir([actividad()], [], date(2026, 8, 10), date(2026, 8, 16))

        assert fechas(salida) == [date(2026, 8, 11)]

    def test_acepta_los_dias_con_tilde(self):
        a = actividad(
            dias_habilitados=["Miércoles"],
            config_por_dia={"Miércoles": {"groupId": 1, "partitions": []}},
        )

        salida = expandir([a], [], LUNES, date(2026, 8, 9))

        assert fechas(salida) == [date(2026, 8, 5)]


class TestEventosUnicos:
    """Un parcial el 12 de noviembre. Antes no habia forma de decirlo."""

    def test_ocurre_solo_ese_dia(self):
        parcial = actividad(
            id="parcial", nombre="Parcial de Cálculo",
            fecha_unica=date(2026, 8, 12), dias_habilitados=[], config_por_dia={},
        )

        salida = expandir([parcial], [], LUNES, DOMINGO)

        assert fechas(salida) == [date(2026, 8, 12)]

    def test_fuera_del_rango_no_aparece(self):
        parcial = actividad(id="p", fecha_unica=date(2026, 9, 3), dias_habilitados=[])

        assert expandir([parcial], [], LUNES, DOMINGO) == []

    def test_ignora_los_dias_de_la_semana(self):
        # Si tiene fecha propia, los dias habilitados no aplican: seria un
        # evento unico que ademas se repite, que no significa nada.
        parcial = actividad(id="p", fecha_unica=date(2026, 8, 12))

        assert fechas(expandir([parcial], [], LUNES, DOMINGO)) == [date(2026, 8, 12)]


class TestExcepciones:
    def test_una_clase_cancelada_no_aparece(self):
        # "Este martes no hay clase."
        excepciones = [Excepcion(activity_id="act-1", fecha=date(2026, 8, 11), tipo="cancelada")]

        salida = expandir([actividad()], excepciones, LUNES, DOMINGO)

        assert date(2026, 8, 11) not in fechas(salida)
        assert len(salida) == 3

    def test_una_clase_movida_aparece_en_la_nueva_fecha(self):
        excepciones = [
            Excepcion(
                activity_id="act-1", fecha=date(2026, 8, 11),
                tipo="movida", nueva_fecha=date(2026, 8, 13),
            )
        ]

        salida = expandir([actividad()], excepciones, LUNES, DOMINGO)

        assert date(2026, 8, 11) not in fechas(salida)
        assert date(2026, 8, 13) in fechas(salida)

    def test_la_movida_queda_marcada(self):
        # La pantalla necesita poder decir "reprogramada" en vez de mostrarla
        # como si siempre hubiera sido ese dia.
        excepciones = [
            Excepcion("act-1", date(2026, 8, 11), "movida", date(2026, 8, 13))
        ]

        movida = [o for o in expandir([actividad()], excepciones, LUNES, DOMINGO)
                  if o.fecha == date(2026, 8, 13)][0]

        assert movida.movida_desde == date(2026, 8, 11)

    def test_una_excepcion_de_otra_actividad_no_afecta(self):
        excepciones = [Excepcion("otra", date(2026, 8, 11), "cancelada")]

        assert len(expandir([actividad()], excepciones, LUNES, DOMINGO)) == 4

    def test_mover_fuera_del_rango_la_saca_de_la_vista(self):
        excepciones = [
            Excepcion("act-1", date(2026, 8, 11), "movida", date(2026, 9, 15))
        ]

        assert date(2026, 8, 11) not in fechas(expandir([actividad()], excepciones, LUNES, DOMINGO))


class TestOrdenYBordes:
    def test_vienen_ordenadas_por_fecha(self):
        a = actividad(
            dias_habilitados=["Jueves", "Martes"],
            config_por_dia={d: {"groupId": 1, "partitions": []} for d in ("Jueves", "Martes")},
        )

        salida = fechas(expandir([a], [], LUNES, date(2026, 8, 9)))

        assert salida == sorted(salida)

    def test_los_extremos_del_rango_entran(self):
        # 3 y 30 de agosto son lunes y domingo.
        a = actividad(
            dias_habilitados=["Lunes", "Domingo"],
            config_por_dia={d: {"groupId": 1, "partitions": []} for d in ("Lunes", "Domingo")},
        )

        salida = fechas(expandir([a], [], LUNES, DOMINGO))

        assert LUNES in salida and DOMINGO in salida

    def test_un_rango_invertido_no_devuelve_nada(self):
        assert expandir([actividad()], [], DOMINGO, LUNES) == []

    def test_sin_actividades_tampoco_rompe(self):
        assert expandir([], [], LUNES, DOMINGO) == []
