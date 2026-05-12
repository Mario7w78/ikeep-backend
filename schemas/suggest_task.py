from pydantic import BaseModel

from schemas.activity import Actividad, Dificultad, TipoActividad


class SugerirTareaRequest(BaseModel):
    tiempo_libre_minutos: int
    tareas_pendientes: list[Actividad]
    dia_preferido: int = 0


class SugerenciaTarea(BaseModel):
    id_actividad: str
    nombre: str
    tipo: TipoActividad
    duracion_estimada: int
    dificultad: Dificultad
    prioridad: int
    encaja: bool
    razon: str = ""


class SugerirTareaResponse(BaseModel):
    sugerencias: list[SugerenciaTarea]
