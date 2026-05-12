from schemas.activity import Actividad as ActividadDTO
from schemas.location import Ubicacion as UbicacionDTO
from schemas.reschedule_request import SolicitudReplanificacion as SolicitudReplanDTO
from schemas.schedule_request import SolicitudHorario as SolicitudDTO
from schemas.travel_time import TiempoTraslado as TiempoTrasladoDTO
from schemas.user_context import BloqueSueno as BloqueSuenoDTO
from schemas.user_context import ContextoUsuario as ContextoDTO

from domain.entities.activity import Actividad as ActividadDomain
from domain.entities.location import Ubicacion as UbicacionDomain
from domain.entities.reschedule_request import SolicitudReplanificacion as SolicitudReplanDomain
from domain.entities.schedule_response import (
    BloqueTiempo as BloqueTiempoDomain,
    RespuestaHorario as RespuestaDomain,
)
from domain.entities.travel_time import TiempoTraslado as TiempoTrasladoDomain
from domain.entities.user_context import BloqueSueno as BloqueSuenoDomain
from domain.entities.user_context import ContextoUsuario as ContextoDomain


def actividad_to_domain(dto: ActividadDTO) -> ActividadDomain:
    return ActividadDomain(
        id=dto.id,
        nombre=dto.nombre,
        tipo=dto.tipo,
        dia=dto.dia,
        hora_inicio=dto.hora_inicio,
        hora_fin=dto.hora_fin,
        ubicacion_id=dto.ubicacion_id,
        prioridad=dto.prioridad,
        duracion_estimada=dto.duracion_estimada,
        fecha_limite=dto.fecha_limite,
        dificultad=dto.dificultad,
    )


def ubicacion_to_domain(dto: UbicacionDTO) -> UbicacionDomain:
    return UbicacionDomain(
        id=dto.id,
        nombre=dto.nombre,
        latitud=dto.latitud,
        longitud=dto.longitud,
    )


def tiempo_traslado_to_domain(dto: TiempoTrasladoDTO) -> TiempoTrasladoDomain:
    return TiempoTrasladoDomain(
        origen_id=dto.origen_id,
        destino_id=dto.destino_id,
        tiempo_estimado_minutos=dto.tiempo_estimado_minutos,
    )


def bloque_sueno_to_domain(dto: BloqueSuenoDTO) -> BloqueSuenoDomain:
    return BloqueSuenoDomain(dia=dto.dia, inicio=dto.inicio, fin=dto.fin)


def contexto_to_domain(dto: ContextoDTO) -> ContextoDomain:
    return ContextoDomain(
        nivel_energia=dto.nivel_energia,
        horario_inicio=dto.horario_inicio,
        horario_fin=dto.horario_fin,
        bloques_sueno=[bloque_sueno_to_domain(b) for b in dto.bloques_sueno],
    )


def solicitud_to_domain(dto: SolicitudDTO) -> ActividadDomain:
    from domain.entities.schedule_request import SolicitudHorario as SolicitudDomain

    return SolicitudDomain(
        actividades_fijas=[actividad_to_domain(a) for a in dto.actividades_fijas],
        tareas_pendientes=[actividad_to_domain(a) for a in dto.tareas_pendientes],
        ubicaciones=[ubicacion_to_domain(u) for u in dto.ubicaciones],
        tiempos_traslado=[tiempo_traslado_to_domain(t) for t in dto.tiempos_traslado],
        contexto_usuario=contexto_to_domain(dto.contexto_usuario),
    )


def reschedule_to_domain(dto: SolicitudReplanDTO) -> SolicitudReplanDomain:
    return SolicitudReplanDomain(
        horario_actual=RespuestaDomain(
            estado=_str_to_estado(dto.horario_actual.estado),
            mensaje=dto.horario_actual.mensaje,
            bloques=[
                BloqueTiempoDomain(
                    id_actividad=b.id_actividad,
                    nombre=b.nombre,
                    tipo=b.tipo,
                    dia=b.dia,
                    hora_inicio=b.hora_inicio,
                    hora_fin=b.hora_fin,
                    ubicacion_id=b.ubicacion_id,
                )
                for b in dto.horario_actual.bloques
            ],
        ),
        actividad_afectada_id=dto.actividad_afectada_id,
        tiempo_perdido_minutos=dto.tiempo_perdido_minutos,
        contexto_usuario=contexto_to_domain(dto.contexto_usuario),
    )


def _str_to_estado(value: str):
    from domain.entities.enums import EstadoSolucion
    for e in EstadoSolucion:
        if e.value == value:
            return e
    return EstadoSolucion.DESCONOCIDO
