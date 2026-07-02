from fastapi import APIRouter, Depends

from dependency_injector.wiring import Provide, inject

from domain.entities.enums import EstadoSolucion
from domain.ports.inbound.scheduler_port import AbstractSchedulerService
from domain.services.llm_parser_service import LLMParserService
from infrastructure.config.container import ApplicationContainer
from infrastructure.adapters.inbound.api.mappers import solicitud_to_domain
from schemas.parse_nl import (
    ParseNLRequest,
    ParseNLResponse,
    ParseNLConversationRequest,
    ParseNLConversationResponse,
)
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


@router.post("/parse-nl", response_model=ParseNLResponse)
@inject
def parse_actividad_nl(
    request: ParseNLRequest,
    parser: LLMParserService = Depends(Provide[ApplicationContainer.llm_parser_service]),
):
    """Parse a natural language activity description into structured data."""
    return parser.parse(request.text)


@router.post("/parse-nl-conversation", response_model=ParseNLConversationResponse)
@inject
async def parse_actividad_nl_conversation(
    request: ParseNLConversationRequest,
    parser: LLMParserService = Depends(Provide[ApplicationContainer.llm_parser_service]),
):
    """Parse an activity description conversationally, with accumulated context."""
    return parser.parse_conversational(request.text, request.history, request.agenda_context, request.current_day)
