from fastapi import APIRouter, Depends, HTTPException

from domain.entities.enums import EstadoSolucion as EstadoDomain
from domain.ports.inbound.reschedule_port import AbstractRescheduleService
from infrastructure.adapters.inbound.api.dependencies import get_reschedule_service
from infrastructure.adapters.inbound.api.mappers import reschedule_to_domain
from schemas.reschedule_request import SolicitudReplanificacion
from schemas.schedule_response import BloqueTiempo, RespuestaHorario

router = APIRouter(prefix="/api/v1/horarios", tags=["Horarios"])


@router.post("/replanificar", response_model=RespuestaHorario)
def replanificar(
    request: SolicitudReplanificacion,
    service: AbstractRescheduleService = Depends(get_reschedule_service),
):
    try:
        domain_request = reschedule_to_domain(request)
        resultado = service.replanificar(domain_request)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if resultado.estado in (EstadoDomain.INFACTIBLE, EstadoDomain.DESCONOCIDO):
        raise HTTPException(status_code=409, detail=resultado.mensaje)

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
