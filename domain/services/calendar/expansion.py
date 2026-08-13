"""Convierte la plantilla semanal en fechas reales.

Hasta ahora una actividad guardaba dias de la semana —"Calculo, martes y
jueves"— y esa semana se repetia indefinidamente. Servia para generar un
horario, pero no para un calendario: un parcial el 12 de noviembre no se podia
representar, y "este martes no hay clase" no tenia donde vivir.

El modelo que se usa aca es el mismo de Google Calendar y el de Apple: se
guarda **la regla** y **las excepciones**, y las fechas se derivan al vuelo.
La alternativa —crear una fila por cada repeticion— obliga a elegir hasta
cuando materializar, y a regenerar todo cada vez que el usuario cambia un dia.

Es logica pura a proposito: es la pieza de la que cuelga todo el calendario,
y se prueba sin base de datos ni red.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

from domain.entities.user_activity import ActividadUsuario

#: Del nombre en espanol al indice de `date.weekday()` (0 = lunes).
DIA_A_INDICE: dict[str, int] = {
    "Lunes": 0,
    "Martes": 1,
    "Miercoles": 2,
    "Miércoles": 2,
    "Jueves": 3,
    "Viernes": 4,
    "Sabado": 5,
    "Sábado": 5,
    "Domingo": 6,
}

TipoExcepcion = Literal["cancelada", "movida"]


@dataclass(frozen=True)
class Excepcion:
    """Algo que rompe la regla en una fecha puntual.

    `cancelada` es "este martes no hay clase". `movida` es "la de este martes
    se pasa al jueves" y necesita `nueva_fecha`.
    """

    activity_id: str
    fecha: date
    tipo: TipoExcepcion
    nueva_fecha: date | None = None


@dataclass(frozen=True)
class Ocurrencia:
    """Una actividad en un dia concreto."""

    fecha: date
    actividad: ActividadUsuario
    #: De donde se movio, si se movio. La pantalla lo necesita para poder
    #: decir "reprogramada" en vez de mostrarla como si siempre hubiera sido
    #: ese dia.
    movida_desde: date | None = None

    @property
    def es_unica(self) -> bool:
        return _fecha_unica(self.actividad) is not None


def _fecha_unica(actividad: ActividadUsuario) -> date | None:
    """La fecha propia de un evento que ocurre una sola vez, si la tiene."""
    valor: Any = getattr(actividad, "fecha_unica", None)
    if valor is None:
        return None
    return valor if isinstance(valor, date) else date.fromisoformat(str(valor)[:10])


def _dias_de(actividad: ActividadUsuario) -> set[int]:
    return {
        DIA_A_INDICE[d]
        for d in actividad.dias_habilitados
        if d in DIA_A_INDICE
    }


def expandir(
    actividades: list[ActividadUsuario],
    excepciones: list[Excepcion],
    desde: date,
    hasta: date,
) -> list[Ocurrencia]:
    """Qué ocurre cada día del rango, con los extremos incluidos.

    Devuelve la lista ordenada por fecha. Un rango invertido devuelve vacío en
    vez de fallar: pedir del 30 al 3 es un error del que llama, y romper la
    pantalla por eso sería peor que no mostrar nada.
    """
    if desde > hasta:
        return []

    canceladas: set[tuple[str, date]] = set()
    movidas: dict[tuple[str, date], date] = {}
    for e in excepciones:
        if e.tipo == "cancelada":
            canceladas.add((e.activity_id, e.fecha))
        elif e.tipo == "movida" and e.nueva_fecha is not None:
            movidas[(e.activity_id, e.fecha)] = e.nueva_fecha

    ocurrencias: list[Ocurrencia] = []

    for actividad in actividades:
        unica = _fecha_unica(actividad)

        if unica is not None:
            # Con fecha propia, los días de la semana no aplican: un evento
            # único que además se repite no significa nada.
            candidatas = [unica]
        else:
            dias = _dias_de(actividad)
            if not dias:
                continue
            candidatas = _fechas_del_rango(desde, hasta, dias)

        for fecha_original in candidatas:
            clave = (actividad.id, fecha_original)

            if clave in canceladas:
                continue

            destino = movidas.get(clave)
            fecha_final = destino or fecha_original

            # Se filtra al final y no antes: una actividad movida hacia
            # adentro del rango tiene que aparecer aunque su fecha original
            # cayera afuera.
            if not (desde <= fecha_final <= hasta):
                continue

            ocurrencias.append(
                Ocurrencia(
                    fecha=fecha_final,
                    actividad=actividad,
                    movida_desde=fecha_original if destino else None,
                )
            )

    ocurrencias.sort(key=lambda o: (o.fecha, o.actividad.nombre))
    return ocurrencias


def _fechas_del_rango(desde: date, hasta: date, dias: set[int]) -> list[date]:
    """Las fechas del rango que caen en alguno de esos días de la semana."""
    salida = []
    cursor = desde
    while cursor <= hasta:
        if cursor.weekday() in dias:
            salida.append(cursor)
        cursor += timedelta(days=1)
    return salida
