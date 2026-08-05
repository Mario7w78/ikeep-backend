"""Presupuesto de contexto de la conversacion.

Reemplaza al viejo "quedate con los ultimos N intercambios". Contar turnos no
mide nada: un turno puede ser "si" o puede traer una propuesta con la
configuracion por dia entera, y son dos ordenes de magnitud distintos. Con un
tope por cantidad, una conversacion corta pero pesada revienta la ventana y
una larga pero liviana se poda sin necesidad.

Podar es seguro porque el estado no vive en la prosa sino en el borrador. Lo
que se pierde es historia conversacional, no informacion de la actividad.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Aproximacion suficiente para no pasarse de la ventana. Cuatro caracteres por
# token es la regla habitual para texto latino; no se usa un tokenizador real
# porque cada proveedor tiene el suyo y el objetivo es acotar el crecimiento,
# no medirlo con precision.
CARACTERES_POR_TOKEN = 4

# Reparto pensado para una ventana de 16K: ~3.5K de instrucciones, ~2.5K de
# contexto, ~2K de salida. Lo que queda es historial.
PRESUPUESTO_HISTORIAL = 8000


def estimar_tokens(turnos: list[dict[str, Any]]) -> int:
    """Costo aproximado de una lista de turnos.

    Se serializa entero en vez de mirar solo `content`: los argumentos de las
    invocaciones son a menudo lo mas pesado del turno, y un turno con el
    content vacio puede costar miles de tokens.
    """
    if not turnos:
        return 0
    return len(json.dumps(turnos, ensure_ascii=False)) // CARACTERES_POR_TOKEN


def agrupar_turnos(turnos: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Agrupa cada invocacion con los resultados que le responden.

    Un grupo es la unidad minima que se puede podar. Separar un tool_call de
    su resultado deja la conversacion invalida para la API en la peticion
    siguiente, y ese error aparece como un 400 opaco del proveedor.
    """
    grupos: list[list[dict[str, Any]]] = []

    for turno in turnos:
        es_resultado = turno.get("role") == "tool"
        # Un resultado se pega al grupo anterior solo si ese grupo lo pidio.
        # Uno huerfano —cliente que reenvia turnos manipulados— va suelto en
        # vez de contaminar un grupo que no le corresponde.
        if es_resultado and grupos and _pidio(grupos[-1], turno.get("tool_call_id")):
            grupos[-1].append(turno)
        else:
            grupos.append([turno])

    return grupos


def _pidio(grupo: list[dict[str, Any]], tool_call_id: Any) -> bool:
    return any(
        llamada.get("id") == tool_call_id
        for turno in grupo
        for llamada in turno.get("tool_calls", [])
    )


def podar_turnos(
    turnos: list[dict[str, Any]], presupuesto: int = PRESUPUESTO_HISTORIAL
) -> list[dict[str, Any]]:
    """Deja los turnos mas recientes que entren en el presupuesto."""
    if not turnos:
        return []

    grupos = agrupar_turnos(turnos)

    conservados: list[list[dict[str, Any]]] = []
    gastado = 0

    # De atras hacia adelante: lo reciente es lo que el modelo necesita.
    for grupo in reversed(grupos):
        costo = estimar_tokens(grupo)

        # El ultimo grupo se conserva aunque no entre. Podar hasta dejar la
        # conversacion vacia seria peor que pasarse: el modelo se quedaria sin
        # la pregunta que tiene que responder.
        if conservados and gastado + costo > presupuesto:
            break

        conservados.append(grupo)
        gastado += costo

    if len(conservados) < len(grupos):
        logger.debug(
            "Historial podado: %d de %d grupos, ~%d tokens.",
            len(conservados),
            len(grupos),
            gastado,
        )

    return [turno for grupo in reversed(conservados) for turno in grupo]
