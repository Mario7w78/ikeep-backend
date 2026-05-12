from dataclasses import dataclass, field

from domain.entities.enums import EstadoSolucion, TipoActividad


@dataclass
class BloqueTiempo:
    id_actividad: str
    nombre: str
    tipo: TipoActividad
    dia: int
    hora_inicio: int
    hora_fin: int
    ubicacion_id: str | None = None


@dataclass
class RespuestaHorario:
    estado: EstadoSolucion
    bloques: list[BloqueTiempo] = field(default_factory=list)
    mensaje: str = ""
