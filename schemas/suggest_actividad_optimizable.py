from pydantic import BaseModel

from schemas.activity import Actividad, Dificultad, TipoActividad


class SugerirActividadOptimizableRequest(BaseModel):
    tiempo_libre_minutos: int
    actividades_optimizables: list[Actividad]
    dia_preferido: int = 0


class SugerenciaActividadOptimizable(BaseModel):
    id_actividad: str
    nombre: str
    tipo: TipoActividad
    duracion_estimada: int
    dificultad: Dificultad
    prioridad: int
    encaja: bool
    razon: str = ""


class SugerirActividadOptimizableResponse(BaseModel):
    sugerencias: list[SugerenciaActividadOptimizable]
