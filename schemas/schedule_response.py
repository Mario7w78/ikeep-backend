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
    #: Viaja de ida y de vuelta: el cliente devuelve el horario entero al
    #: pedir una replanificacion. Sin este campo en el DTO el dominio decide
    #: bien y el dato se pierde igual en el camino.
    #:
    #: `None` no es lo mismo que `False`: significa que el bloque se genero
    #: antes de que el campo existiera. Un horario ya guardado en el telefono
    #: llega asi, y tratarlo como movible le desordenaria las clases a alguien
    #: que no cambio nada. Ver `es_fija_efectiva` en el dominio.
    es_fija: bool | None = None


class RespuestaHorario(BaseModel):
    estado: str
    bloques: list[BloqueTiempo] = []
    mensaje: str = ""
    recomendaciones: list[str] = []
    tareas_omitidas: list[str] = []
