from enum import Enum

from pydantic import BaseModel


class TipoActividad(str, Enum):
    CLASE = "clase"
    TRABAJO = "trabajo"
    TAREA = "tarea"


class Dificultad(str, Enum):
    BAJA = "baja"
    MEDIA = "media"
    ALTA = "alta"


class Actividad(BaseModel):
    id: str
    nombre: str
    tipo: TipoActividad
    dia: int
    hora_inicio: int
    hora_fin: int
    ubicacion_id: str | None = None
    prioridad: int = 0
    duracion_estimada: int
    fecha_limite: str | None = None
    dificultad: Dificultad = Dificultad.MEDIA
