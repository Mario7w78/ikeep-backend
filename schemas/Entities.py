from pydantic import BaseModel
from typing import Optional, List

class Actividad(BaseModel):
    id: str
    id_actividad_original: str
    nombre: str
    es_fija: bool
    duracion_minutos: int
    inicio_minutos: Optional[int] = None 
    fin_minutos: Optional[int] = None
    tiempo_traslado_minutos: int = 0
    dias_permitidos: List[int] 

class HorarioRequest(BaseModel):
    actividades: List[Actividad]
    hora_inicio_dia: int = 480
    hora_fin_dia: int = 1200

class ActividadProgramada(BaseModel):
    id_actividad: str
    id_actividad_original: str
    nombre: str
    dia: int
    inicio: int
    fin: int