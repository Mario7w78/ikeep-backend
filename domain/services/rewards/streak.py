"""Rachas y progreso diario.

Hoy no se puede marcar una actividad como completada, asi que no hay ningun
evento que festejar: sin "terminaste esto" no hay racha, ni progreso, ni nada
que la mascota pueda celebrar. Duolingo funciona porque existe el momento en
que terminas la leccion.

El calculo vive aca y no en una consulta SQL porque las reglas de borde —que
cuenta como romper una racha, si hoy todavia cuenta— son decisiones de
producto, y en una consulta quedarian escritas donde nadie las lee.
"""

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Racha:
    """Dias consecutivos con al menos una actividad completada."""

    actual: int
    mejor: int
    #: Si hoy todavia no hay ninguna y la racha depende de que la haya.
    en_riesgo: bool


def calcular_racha(fechas: set[date], hoy: date) -> Racha:
    """La racha que corresponde a este conjunto de dias.

    Un dia sin nada rompe la racha, con una excepcion: el dia de hoy. Hasta
    que el dia termine, no completar todavia no es fallar — cortar la racha a
    las 00:01 castigaria a alguien por no haber empezado la manana.
    """
    if not fechas:
        return Racha(actual=0, mejor=0, en_riesgo=False)

    hoy_cuenta = hoy in fechas
    # Si hoy no hay nada, se mide desde ayer: hoy todavia esta abierto.
    cursor = hoy if hoy_cuenta else hoy - timedelta(days=1)

    actual = 0
    while cursor in fechas:
        actual += 1
        cursor -= timedelta(days=1)

    return Racha(
        actual=actual,
        mejor=_mejor_racha(fechas),
        # Solo esta en riesgo si hay algo que perder.
        en_riesgo=not hoy_cuenta and actual > 0,
    )


def _mejor_racha(fechas: set[date]) -> int:
    mejor = 0
    for fecha in fechas:
        # Solo se cuenta desde el principio de cada tramo: sin esto, un tramo
        # de N dias se recorreria N veces.
        if fecha - timedelta(days=1) in fechas:
            continue
        largo = 0
        cursor = fecha
        while cursor in fechas:
            largo += 1
            cursor += timedelta(days=1)
        mejor = max(mejor, largo)
    return mejor


@dataclass(frozen=True)
class ProgresoDelDia:
    completadas: int
    total: int

    @property
    def fraccion(self) -> float:
        """Entre 0 y 1. Un dia sin nada programado esta completo, no vacio.

        Mostrar 0% a alguien que no tenia nada que hacer lo haria sentir en
        falta por un dia libre.
        """
        if self.total == 0:
            return 1.0
        return min(self.completadas / self.total, 1.0)

    @property
    def terminado(self) -> bool:
        return self.completadas >= self.total and self.total > 0
