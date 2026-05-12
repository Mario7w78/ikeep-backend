from pydantic import BaseModel

from schemas.schedule_response import RespuestaHorario
from schemas.user_context import ContextoUsuario


class SolicitudReplanificacion(BaseModel):
    horario_actual: RespuestaHorario
    actividad_afectada_id: str
    tiempo_perdido_minutos: int
    contexto_usuario: ContextoUsuario = ContextoUsuario()
