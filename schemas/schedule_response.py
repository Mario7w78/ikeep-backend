from pydantic import BaseModel

from schemas.activity import TipoActividad


class BloqueTiempo(BaseModel):
    id_actividad: str
    nombre: str
    tipo: TipoActividad
    dia: int
    hora_inicio: int
    hora_fin: int
    ubicacion_id: str | None = None


class RespuestaHorario(BaseModel):
    estado: str
    bloques: list[BloqueTiempo] = []
    mensaje: str = ""
