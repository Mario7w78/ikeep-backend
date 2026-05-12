from fastapi import APIRouter, Depends, HTTPException

from domain.entities.enums import EstadoSolucion
from domain.ports.inbound.scheduler_port import AbstractSchedulerService
from infrastructure.adapters.inbound.api.dependencies import get_scheduler_service
from infrastructure.adapters.inbound.api.mappers import solicitud_to_domain
from schemas.schedule_request import SolicitudHorario
from schemas.schedule_response import BloqueTiempo, RespuestaHorario

router = APIRouter(prefix="/api/v1/horarios", tags=["Horarios"])


@router.post("/generar", response_model=RespuestaHorario)
def generar_horario(
    request: SolicitudHorario,
    scheduler: AbstractSchedulerService = Depends(get_scheduler_service),
):
    try:
        solicitud_domain = solicitud_to_domain(request)
        resultado = scheduler.generar(solicitud_domain)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if resultado.estado in (EstadoSolucion.INFACTIBLE, EstadoSolucion.DESCONOCIDO):
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
