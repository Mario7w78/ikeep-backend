from fastapi import APIRouter, Depends

from dependency_injector.wiring import Provide, inject

from domain.entities.enums import EstadoSolucion
from domain.ports.inbound.scheduler_port import AbstractSchedulerService
from infrastructure.config.container import ApplicationContainer
from infrastructure.adapters.inbound.api.mappers import solicitud_to_domain
from schemas.schedule_request import SolicitudHorario
from schemas.schedule_response import BloqueTiempo, RespuestaHorario

router = APIRouter(prefix="/api/v1/horarios", tags=["Horarios"])


@router.post("/generar", response_model=RespuestaHorario)
@inject
def generar_horario(
    request: SolicitudHorario,
    scheduler: AbstractSchedulerService = Depends(Provide[ApplicationContainer.scheduler_service]),
):
    solicitud_domain = solicitud_to_domain(request)
    resultado = scheduler.generar(solicitud_domain)

    if resultado.estado in (EstadoSolucion.INFACTIBLE, EstadoSolucion.DESCONOCIDO):
        from infrastructure.adapters.inbound.api.middleware import SolverException
        raise SolverException(resultado.mensaje)

    return RespuestaHorario(
        estado=resultado.estado.value,
        mensaje=resultado.mensaje,
        bloques=[
            BloqueTiempo(
                id_actividad=b.id_actividad,
                nombre=b.nombre,
                tipo=b.tipo,
                dia=b.dia,
                hora_inicio=b.hora_inicio,
                hora_fin=b.hora_fin,
                ubicacion_id=b.ubicacion_id,
            )
            for b in resultado.bloques
        ],
    )
