from fastapi import APIRouter, Depends

from dependency_injector.wiring import Provide, inject

from domain.entities.enums import EstadoSolucion as EstadoDomain
from domain.ports.inbound.reschedule_port import AbstractRescheduleService
from infrastructure.config.container import ApplicationContainer
from infrastructure.adapters.inbound.api.mappers import reschedule_to_domain
from schemas.reschedule_request import SolicitudReplanificacion
from schemas.schedule_response import BloqueTiempo, RespuestaHorario

router = APIRouter(prefix="/api/v1/horarios", tags=["Horarios"])


@router.post("/replanificar", response_model=RespuestaHorario)
@inject
def replanificar(
    request: SolicitudReplanificacion,
    service: AbstractRescheduleService = Depends(Provide[ApplicationContainer.reschedule_service]),
):
    domain_request = reschedule_to_domain(request)
    resultado = service.replanificar(domain_request)

    return RespuestaHorario(
        estado=resultado.estado.value,
        mensaje=resultado.mensaje,
        recomendaciones=resultado.recomendaciones,
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
