from enum import Enum


class EstadoSolucion(Enum):
    OPTIMA = "OPTIMA"
    FACTIBLE = "FACTIBLE"
    INFACTIBLE = "INFACTIBLE"
    DESCONOCIDO = "DESCONOCIDO"


class TipoActividad(str, Enum):
    CLASE = "clase"
    TRABAJO = "trabajo"
    TAREA = "tarea"


class Dificultad(str, Enum):
    BAJA = "baja"
    MEDIA = "media"
    ALTA = "alta"
