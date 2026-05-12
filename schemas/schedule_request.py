from pydantic import BaseModel

from schemas.activity import Actividad
from schemas.location import Ubicacion
from schemas.travel_time import TiempoTraslado
from schemas.user_context import ContextoUsuario


class SolicitudHorario(BaseModel):
    actividades_fijas: list[Actividad]
    tareas_pendientes: list[Actividad]
    ubicaciones: list[Ubicacion] = []
    tiempos_traslado: list[TiempoTraslado] = []
    contexto_usuario: ContextoUsuario = ContextoUsuario()
