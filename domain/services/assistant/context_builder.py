"""Construccion del contexto dinamico que recibe el asistente.

Se le entrega como JSON y no como prosa. La version en prosa que habia antes
describia la agenda en espanol pero sin ids, y sin ids no se puede senalar una
actividad: esa es la razon estructural de que el asistente solo supiera crear.

Es una funcion pura —recibe datos, devuelve un diccionario— para poder
probarla sin tocar repositorios ni relojes.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from schemas.assistant import Borrador

DIAS = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]

# Debajo de esto un hueco no es tiempo utilizable. Ofrecerlo como "tiempo
# libre" seria ruido que el modelo tendria que aprender a ignorar.
HUECO_MINIMO_MINUTOS = 15

INICIO_DIA_POR_DEFECTO = 480  # 08:00
FIN_DIA_POR_DEFECTO = 1320  # 22:00


@dataclass(frozen=True)
class BloqueAgenda:
    """Una actividad ya ubicada en un dia y horario concretos."""

    id_actividad: str
    nombre: str
    dia: int  # 0 = lunes
    inicio: int  # minutos desde medianoche
    fin: int


def huecos_libres(
    ocupados: list[tuple[int, int]], inicio_dia: int, fin_dia: int
) -> list[tuple[int, int]]:
    """Tramos libres dentro del dia util.

    Habilita preguntas del tipo "tengo dos horas libres, que hago" sin que el
    modelo tenga que deducirlas restando bloques, que es justo el tipo de
    cuenta donde se equivoca.
    """
    # Se recortan al dia util antes de nada: lo que ocurre fuera no compite
    # por el tiempo que estamos repartiendo.
    dentro = sorted(
        (max(i, inicio_dia), min(f, fin_dia))
        for i, f in ocupados
        if f > inicio_dia and i < fin_dia
    )

    huecos = []
    cursor = inicio_dia
    for inicio, fin in dentro:
        if inicio > cursor:
            huecos.append((cursor, inicio))
        # max() y no asignacion directa: un bloque contenido dentro de otro no
        # debe hacer retroceder el cursor y abrir un hueco que no existe.
        cursor = max(cursor, fin)

    if cursor < fin_dia:
        huecos.append((cursor, fin_dia))

    return [(i, f) for i, f in huecos if f - i >= HUECO_MINIMO_MINUTOS]


def construir_contexto(
    *,
    ahora: datetime,
    agenda: list[BloqueAgenda],
    borrador: Borrador,
    ya_pregunte: list[str] | None = None,
    energia: str | None = None,
    inicio_dia: int = INICIO_DIA_POR_DEFECTO,
    fin_dia: int = FIN_DIA_POR_DEFECTO,
) -> dict[str, Any]:
    """El bloque dinamico del prompt, listo para serializar."""
    dia_actual = ahora.weekday()

    contexto: dict[str, Any] = {
        "ahora": {
            "fecha": ahora.strftime("%Y-%m-%d"),
            "dia": DIAS[dia_actual],
            "hora_min": ahora.hour * 60 + ahora.minute,
        },
        "agenda": [
            {
                "id": b.id_actividad,
                "nombre": b.nombre,
                "dia": DIAS[b.dia],
                "inicio": b.inicio,
                "fin": b.fin,
            }
            for b in agenda
        ],
        "huecos_libres_hoy": [
            [i, f]
            for i, f in huecos_libres(
                [(b.inicio, b.fin) for b in agenda if b.dia == dia_actual],
                inicio_dia,
                fin_dia,
            )
        ],
        "borrador": borrador.model_dump(exclude_none=True),
        "falta": borrador.campos_faltantes,
        # Lo ya preguntado rompe el bucle de repetir lo mismo: si el usuario
        # esquivo una pregunta, el modelo lo ve y sigue adelante.
        "ya_pregunte": ya_pregunte or [],
    }

    # Solo si se conoce: mandar "desconocida" invita a razonar sobre un dato
    # que no existe.
    if energia:
        contexto["energia"] = energia

    return contexto
