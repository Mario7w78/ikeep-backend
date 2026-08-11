"""Rachas y progreso diario.

Las reglas de borde son decisiones de producto, no detalles: cuando se rompe
una racha y que pasa con el dia en curso cambian como se siente la app.
"""

from datetime import date

from domain.services.rewards.streak import (
    ProgresoDelDia,
    calcular_racha,
)

HOY = date(2026, 8, 11)


def dias(*numeros: int) -> set[date]:
    """Dias de agosto de 2026, para leer los casos de un vistazo."""
    return {date(2026, 8, n) for n in numeros}


class TestRacha:
    def test_sin_nada_no_hay_racha(self):
        assert calcular_racha(set(), HOY).actual == 0

    def test_cuenta_los_dias_seguidos_hasta_hoy(self):
        assert calcular_racha(dias(9, 10, 11), HOY).actual == 3

    def test_un_hueco_la_corta(self):
        # El 8 no cuenta: entre el 8 y el 10 falta el 9.
        assert calcular_racha(dias(7, 8, 10, 11), HOY).actual == 2

    def test_hoy_sin_completar_todavia_no_rompe(self):
        # Cortarla a las 00:01 castigaria a alguien por no haber empezado la
        # manana. Hasta que el dia termine, la racha de ayer sigue viva.
        assert calcular_racha(dias(9, 10), HOY).actual == 2

    def test_pero_queda_marcada_en_riesgo(self):
        assert calcular_racha(dias(9, 10), HOY).en_riesgo is True

    def test_si_hoy_ya_completo_no_esta_en_riesgo(self):
        assert calcular_racha(dias(9, 10, 11), HOY).en_riesgo is False

    def test_sin_racha_que_perder_no_hay_riesgo(self):
        # Avisar "tu racha esta en riesgo" a quien no tiene ninguna es ruido.
        assert calcular_racha(dias(1), HOY).en_riesgo is False

    def test_dos_dias_de_hueco_la_terminan(self):
        assert calcular_racha(dias(5, 6, 7), HOY).actual == 0


class TestMejorRacha:
    def test_recuerda_el_tramo_mas_largo(self):
        assert calcular_racha(dias(1, 2, 3, 4, 10, 11), HOY).mejor == 4

    def test_la_actual_puede_ser_la_mejor(self):
        assert calcular_racha(dias(9, 10, 11), HOY).mejor == 3

    def test_un_solo_dia_es_una_racha_de_uno(self):
        assert calcular_racha(dias(11), HOY).mejor == 1


class TestProgresoDelDia:
    def test_la_fraccion_es_lo_hecho_sobre_lo_que_habia(self):
        assert ProgresoDelDia(completadas=3, total=5).fraccion == 0.6

    def test_un_dia_sin_nada_programado_esta_completo(self):
        # Mostrar 0% a alguien que no tenia nada lo haria sentir en falta por
        # un dia libre.
        assert ProgresoDelDia(completadas=0, total=0).fraccion == 1.0

    def test_pero_un_dia_libre_no_esta_terminado(self):
        # No hay nada que festejar: no hizo nada porque no habia nada.
        assert ProgresoDelDia(completadas=0, total=0).terminado is False

    def test_no_pasa_de_uno(self):
        assert ProgresoDelDia(completadas=7, total=5).fraccion == 1.0

    def test_terminado_cuando_no_queda_nada(self):
        assert ProgresoDelDia(completadas=5, total=5).terminado is True

    def test_a_medias_no_esta_terminado(self):
        assert ProgresoDelDia(completadas=4, total=5).terminado is False
