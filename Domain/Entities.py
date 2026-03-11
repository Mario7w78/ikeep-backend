from pydantic import BaseModel
from typing import Optional, List

class Actividad(BaseModel):
    id: str
    nombre: str
    es_fija: bool
    duracion_minutos: int
    # Solo para actividades fijas
    inicio_minutos: Optional[int] = None 
    fin_minutos: Optional[int] = None
    tiempo_traslado_minutos: int = 0

class HorarioRequest(BaseModel):
    actividades: List[Actividad]
    hora_inicio_dia: int = 480 # 8:00 AM en minutos
    hora_fin_dia: int = 1200   # 8:00 PM en minutos

class ActividadProgramada(BaseModel):
    id_actividad: str
    nombre: str
    inicio: int
    fin: int