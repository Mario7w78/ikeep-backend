from dataclasses import dataclass

from domain.entities.enums import Dificultad, TipoActividad


@dataclass
class Actividad:
    id: str
    nombre: str
    tipo: TipoActividad
    dia: int
    hora_inicio: int
    hora_fin: int
    ubicacion_id: str | None = None
    prioridad: int = 0
    duracion_estimada: int = 0
    fecha_limite: str | None = None
    dificultad: Dificultad = Dificultad.MEDIA
