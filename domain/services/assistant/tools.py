"""Catalogo de tools del asistente.

Tres clases de tool, que se comportan distinto en el bucle:

- `actualizar_borrador` no devuelve nada al modelo ni termina el turno. Es
  memoria: acumula lo que se extrajo y permite seguir preguntando en el mismo
  turno. Es la pieza que arregla el "se olvida".
- Las de lectura se ejecutan en el servidor contra los repositorios y su
  resultado vuelve al modelo en el mismo turno, para que pueda responder con
  ese dato.
- Las de propuesta terminan el turno y hacen que el cliente muestre una
  tarjeta de confirmacion. Nada se escribe sin que el usuario acepte.

Texto plano sin tool alguna es una pregunta o charla. No hace falta una tool
para eso: agregarla solo daria una forma mas de equivocarse.
"""

from typing import Any

from schemas.assistant import BorradorPatch

TOOLS_DE_LECTURA = {"consultar_agenda", "buscar_actividad", "sugerir_tarea"}

TOOLS_DE_PROPUESTA = {
    "proponer_actividad",
    "proponer_modificacion",
    "proponer_eliminacion",
    "proponer_regeneracion",
}

TOOLS = {"actualizar_borrador"} | TOOLS_DE_LECTURA | TOOLS_DE_PROPUESTA


def es_tool_conocida(nombre: str) -> bool:
    """El modelo puede inventar nombres; hay que poder rechazarlos sin que
    revienten el turno."""
    return nombre in TOOLS


# Tipos JSON Schema derivados de los campos de BorradorPatch, para que el
# catalogo no pueda divergir del schema que despues valida lo que llega.
_TIPOS_PATCH: dict[str, dict[str, Any]] = {
    "name": {"type": "string", "description": "Nombre de la actividad."},
    "activity_type": {
        "type": "string",
        "enum": ["clase", "trabajo", "tarea", "viaje"],
        "description": "Que clase de actividad es.",
    },
    "is_fixed": {
        "type": "boolean",
        "description": (
            "true si ocurre siempre a la misma hora; false si el usuario deja "
            "que el sistema elija cuando."
        ),
    },
    "is_anchor": {
        "type": "boolean",
        "description": "true si el usuario fija el dia pero delega la hora.",
    },
    "difficulty": {
        "type": "string",
        "enum": ["baja", "media", "alta"],
        "description": "Cuanto esfuerzo mental exige.",
    },
    "priority": {
        "type": "string",
        "enum": ["baja", "media", "alta"],
        "description": "Que tan importante es para el usuario.",
    },
    "schedule": {
        "type": "array",
        "description": (
            "Bloques concretos, solo para actividades a hora fija. Se "
            "reemplaza entero: hay que mandar todos los bloques vigentes, no "
            "solo el que cambia."
        ),
        "items": {
            "type": "object",
            "properties": {
                "day": {
                    "type": "string",
                    "description": "Dia en espanol, ej. 'Martes'.",
                },
                "start_time": {
                    "type": "integer",
                    "description": "Minutos desde medianoche. 10:00 son 600.",
                },
                "end_time": {
                    "type": "integer",
                    "description": "Minutos desde medianoche. 12:00 son 720.",
                },
            },
            "required": ["day", "start_time", "end_time"],
        },
    },
    "duracion_minutos": {
        "type": "integer",
        "description": "Cuanto dura en minutos. Obligatorio si no es a hora fija.",
    },
    "hora_preferida_inicio": {
        "type": "integer",
        "description": (
            "Inicio de la ventana en que el usuario prefiere hacerla, en "
            "minutos desde medianoche. 'Por la tarde' son 840 a 1200."
        ),
    },
    "hora_preferida_fin": {
        "type": "integer",
        "description": "Fin de esa ventana, en minutos desde medianoche.",
    },
    "deadline": {
        "type": "string",
        "description": "Fecha limite en formato AAAA-MM-DD.",
    },
    "location": {"type": "string", "description": "Donde ocurre."},
    "travel_to": {
        "type": "integer",
        "description": "Minutos de traslado antes. 0 si no hay que viajar.",
    },
    "travel_from": {
        "type": "integer",
        "description": "Minutos de traslado despues. 0 si no hay que viajar.",
    },
}


def _parametros_del_borrador() -> dict[str, Any]:
    # Se recorren los campos del schema en vez de escribir la lista a mano:
    # asi agregar un campo al patch sin describirlo aca falla en los tests y
    # no en produccion.
    faltan = set(BorradorPatch.model_fields) - set(_TIPOS_PATCH)
    if faltan:
        raise RuntimeError(
            f"Campos de BorradorPatch sin descripcion para el modelo: {sorted(faltan)}"
        )
    return {
        "type": "object",
        "properties": {
            campo: _TIPOS_PATCH[campo] for campo in BorradorPatch.model_fields
        },
    }


def definiciones_openai() -> list[dict[str, Any]]:
    """El catalogo en el formato que espera la API de tool calling."""
    return [
        {
            "type": "function",
            "function": {
                "name": "actualizar_borrador",
                "description": (
                    "Registra la informacion que acabas de extraer del mensaje "
                    "del usuario. Llamala en CUALQUIER turno donde aprendas algo "
                    "nuevo, incluso si todavia te falta preguntar otras cosas. "
                    "Manda solo los campos que aprendiste ahora: lo que no "
                    "menciones se conserva."
                ),
                "parameters": _parametros_del_borrador(),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "consultar_agenda",
                "description": (
                    "Consulta que tiene agendado el usuario. Usala cuando "
                    "pregunte por su agenda o cuando necesites saber si algo se "
                    "superpone."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "dia": {
                            "type": "string",
                            "description": (
                                "Dia en espanol. Omitilo para ver la semana "
                                "entera."
                            ),
                        }
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "buscar_actividad",
                "description": (
                    "Busca una actividad del usuario por nombre aproximado. "
                    "Usala antes de proponer modificar o eliminar algo, para "
                    "obtener su id."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "texto": {
                            "type": "string",
                            "description": "Como la nombro el usuario.",
                        }
                    },
                    "required": ["texto"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "sugerir_tarea",
                "description": (
                    "Sugiere en que podria trabajar el usuario ahora, segun su "
                    "agenda y su energia."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "proponer_actividad",
                "description": (
                    "Propone crear la actividad del borrador. Llamala solo "
                    "cuando no falte ningun dato. El usuario tendra que "
                    "confirmarla."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "proponer_modificacion",
                "description": (
                    "Propone cambiar una actividad existente con los datos del "
                    "borrador. Busca antes su id con buscar_actividad."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "activity_id": {
                            "type": "string",
                            "description": "Id devuelto por buscar_actividad.",
                        }
                    },
                    "required": ["activity_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "proponer_eliminacion",
                "description": (
                    "Propone eliminar una actividad. Busca antes su id con "
                    "buscar_actividad; si hay varias parecidas, pregunta cual "
                    "en vez de elegir."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "activity_id": {
                            "type": "string",
                            "description": "Id devuelto por buscar_actividad.",
                        }
                    },
                    "required": ["activity_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "proponer_regeneracion",
                "description": (
                    "Propone volver a generar el horario completo. Usala cuando "
                    "el usuario pida reorganizar su semana."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]
