from schemas.activity import Actividad as ActividadDTO
from schemas.location import Ubicacion as UbicacionDTO
from schemas.reschedule_request import SolicitudReplanificacion as SolicitudReplanDTO
from schemas.schedule_request import SolicitudHorario as SolicitudDTO
from schemas.travel_time import TiempoTraslado as TiempoTrasladoDTO
from schemas.user_context import DreamBlock as DreamBlockDTO
from schemas.user_context import ContextoUsuario as ContextoDTO
from schemas.user_context import RegistroEnergia as RegistroEnergiaDTO

from domain.entities.activity import Actividad as ActividadDomain
from domain.entities.location import Ubicacion as UbicacionDomain
from domain.entities.travel_time import TiempoTraslado as TiempoTrasladoDomain
from domain.entities.reschedule_request import SolicitudReplanificacion as SolicitudReplanDomain
from domain.entities.schedule_response import BloqueTiempo as BloqueTiempoDomain
from domain.entities.schedule_response import RespuestaHorario as RespuestaDomain
from domain.entities.user_context import DreamBlock as DreamBlockDomain
from domain.entities.user_context import ContextoUsuario as ContextoDomain
from domain.entities.user_context import RegistroEnergia as RegistroEnergiaDomain


def actividad_to_domain(dto: ActividadDTO) -> ActividadDomain:
    return ActividadDomain(
        id=dto.id,
        nombre=dto.nombre,
        tipo=dto.tipo,
        dia=dto.dia,
        dia_desde=dto.dia_desde,
        dia_hasta=dto.dia_hasta,
        dias_permitidos=dto.dias_permitidos,
        es_ancla=dto.es_ancla,
        hora_inicio=dto.hora_inicio,
        hora_fin=dto.hora_fin,
        ubicacion_id=dto.ubicacion_id,
        prioridad=dto.prioridad,
        duracion_estimada=dto.duracion_estimada,
        fecha_limite=dto.fecha_limite,
        dificultad=dto.dificultad,
        hora_preferida_inicio=dto.hora_preferida_inicio,
        hora_preferida_fin=dto.hora_preferida_fin,
        travel_to=dto.travel_to,
        travel_from=dto.travel_from,
    )


def domain_to_actividad_request(domain: ActividadDomain) -> ActividadDTO:
    return ActividadDTO(
        id=domain.id,
        nombre=domain.nombre,
        tipo=domain.tipo,
        dia=domain.dia,
        dia_desde=domain.dia_desde,
        dia_hasta=domain.dia_hasta,
        dias_permitidos=domain.dias_permitidos,
        es_ancla=domain.es_ancla,
        hora_inicio=domain.hora_inicio,
        hora_fin=domain.hora_fin,
        ubicacion_id=domain.ubicacion_id,
        prioridad=domain.prioridad,
        duracion_estimada=domain.duracion_estimada,
        fecha_limite=domain.fecha_limite,
        dificultad=domain.dificultad,
        hora_preferida_inicio=domain.hora_preferida_inicio,
        hora_preferida_fin=domain.hora_preferida_fin,
        travel_to=domain.travel_to,
        travel_from=domain.travel_from,
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


def dream_block_to_domain(dto: DreamBlockDTO) -> DreamBlockDomain:
    return DreamBlockDomain(dia=dto.dia, inicio=dto.inicio, fin=dto.fin)


def registro_energia_to_domain(dto: RegistroEnergiaDTO) -> RegistroEnergiaDomain:
    return RegistroEnergiaDomain(
        timestamp=dto.timestamp,
        nivel=dto.nivel,
        dia_semana=dto.dia_semana,
        contexto=dto.contexto,
    )


def contexto_to_domain(dto: ContextoDTO) -> ContextoDomain:
    return ContextoDomain(
        nivel_energia=dto.nivel_energia,
        horario_inicio=dto.horario_inicio,
        horario_fin=dto.horario_fin,
        dream_blocks=[dream_block_to_domain(b) for b in dto.dream_blocks],
        historial_energia=[registro_energia_to_domain(r) for r in dto.historial_energia],
        patron_energia_manual=dto.patron_energia_manual,
    )


def solicitud_to_domain(dto: SolicitudDTO) -> ActividadDomain:
    from domain.entities.schedule_request import SolicitudHorario as SolicitudDomain

    return SolicitudDomain(
        actividades_fijas=[actividad_to_domain(a) for a in dto.actividades_fijas],
        actividades_ancla=[actividad_to_domain(a) for a in dto.actividades_ancla],
        actividades_optimizables_puras=[actividad_to_domain(a) for a in dto.actividades_optimizables_puras],
        ubicaciones=[ubicacion_to_domain(u) for u in dto.ubicaciones],
        tiempos_traslado=[tiempo_traslado_to_domain(t) for t in dto.tiempos_traslado],
        contexto_usuario=contexto_to_domain(dto.contexto_usuario),
        dia_inicio=dto.dia_inicio,
        dias_totales=dto.dias_totales,
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
        dia_inicio=dto.dia_inicio,
        dias_totales=dto.dias_totales,
    )


def _str_to_estado(value: str):
    from domain.entities.enums import EstadoSolucion
    for e in EstadoSolucion:
        if e.value == value:
            return e
    return EstadoSolucion.DESCONOCIDO
