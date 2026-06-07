from dataclasses import dataclass

from domain.entities.enums import Dificultad, TipoActividad


@dataclass
class Actividad:
    id: str
    nombre: str
    tipo: TipoActividad
    hora_inicio: int = 0
    hora_fin: int = 0
    dia: int | None = None
    dia_desde: int = 0
    dia_hasta: int = 6
    dias_permitidos: list[int] | None = None
    es_ancla: bool = False
    ubicacion_id: str | None = None
    prioridad: int = 0
    duracion_estimada: int = 0
    fecha_limite: str | None = None
    dificultad: Dificultad = Dificultad.MEDIA
    hora_preferida_inicio: int | None = None
    hora_preferida_fin: int | None = None
