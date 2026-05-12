from dataclasses import dataclass, field

from domain.entities.schedule_response import RespuestaHorario
from domain.entities.user_context import ContextoUsuario


@dataclass
class SolicitudReplanificacion:
    horario_actual: RespuestaHorario
    actividad_afectada_id: str
    tiempo_perdido_minutos: int
    contexto_usuario: ContextoUsuario = field(default_factory=ContextoUsuario)
