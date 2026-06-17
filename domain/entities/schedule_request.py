from dataclasses import dataclass, field

from domain.entities.activity import Actividad
from domain.entities.location import Ubicacion
from domain.entities.travel_time import TiempoTraslado
from domain.entities.user_context import ContextoUsuario


@dataclass
class SolicitudHorario:
    actividades_fijas: list[Actividad] = field(default_factory=list)
    actividades_ancla: list[Actividad] = field(default_factory=list)
    actividades_optimizables_puras: list[Actividad] = field(default_factory=list)
    ubicaciones: list[Ubicacion] = field(default_factory=list)
    tiempos_traslado: list[TiempoTraslado] = field(default_factory=list)
    contexto_usuario: ContextoUsuario = field(default_factory=ContextoUsuario)
    dia_inicio: int = 0
    dias_totales: int = 7
