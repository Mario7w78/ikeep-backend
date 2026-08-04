"""Endpoint conversacional del asistente.

Convive con /parse-nl-conversation, que sigue funcionando: el camino viejo se
retira recien cuando este este validado en dispositivo.

A diferencia de aquel, este exige autenticacion. El endpoint viejo es publico
y el limite por IP es una mitigacion, no una solucion: aca se ejecutan tools
que leen datos del usuario, asi que saber quien pregunta no es opcional.
"""

from datetime import datetime, timezone
from typing import Any, Literal

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from domain.ports.outbound.conversational_llm_port import ConversationalLLMPort
from domain.services.assistant.conversation import ServicioConversacion
from infrastructure.adapters.inbound.api.auth import (
    AuthenticatedUser,
    get_current_user,
)
from infrastructure.adapters.inbound.api.v1.activities_router import get_access_token
from infrastructure.adapters.outbound.assistant.data_source import (
    RepositorioFuenteDeDatos,
)
from infrastructure.adapters.outbound.supabase.schedule_repository import (
    SupabaseHorarioRepository,
)
from infrastructure.adapters.outbound.supabase.user_activity_repository import (
    SupabaseActividadUsuarioRepository,
)
from infrastructure.config.container import ApplicationContainer
from schemas.assistant import Borrador

router = APIRouter(prefix="/api/v1/asistente", tags=["Asistente"])


class ConversarRequest(BaseModel):
    mensaje: str = Field(min_length=1, max_length=1000)
    # El borrador y los turnos los devuelve el servidor en cada respuesta y el
    # cliente los reenvia. El backend es stateless: no guarda conversaciones,
    # y sostener sesiones en memoria no sobreviviria a que Render duerma el
    # contenedor.
    borrador: Borrador = Field(default_factory=Borrador)
    turnos: list[dict[str, Any]] = Field(default_factory=list, max_length=60)
    ya_pregunte: list[str] = Field(default_factory=list, max_length=20)
    energia: str | None = Field(default=None, max_length=20)


class PropuestaResponse(BaseModel):
    tipo: Literal["crear", "modificar", "eliminar", "regenerar"]
    borrador: Borrador | None = None
    activity_id: str | None = None


class ConversarResponse(BaseModel):
    tipo: Literal["pregunta", "charla", "propuesta"]
    mensaje: str | None = None
    borrador: Borrador
    turnos: list[dict[str, Any]]
    propuesta: PropuestaResponse | None = None


def get_conversation_service_factory():
    """Se sustituye en los tests para no construir repositorios reales."""
    return _construir_servicio


def _construir_servicio(
    access_token: str, modelo: ConversationalLLMPort
) -> ServicioConversacion:
    # La fuente se arma por peticion porque va atada al token de quien
    # pregunta: es lo que hace que RLS acote lo que el asistente puede leer.
    return ServicioConversacion(
        modelo=modelo,
        datos=RepositorioFuenteDeDatos(
            access_token=access_token,
            horarios=SupabaseHorarioRepository(),
            actividades=SupabaseActividadUsuarioRepository(),
        ),
    )


# `def` y no `async def`: el bucle llama a un cliente HTTP sincrono varias
# veces por turno, y bloquear el event loop durante toda esa latencia dejaria
# al servidor sin atender a nadie mas.
@router.post("/conversar", response_model=ConversarResponse)
@inject
def conversar(
    request: ConversarRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    modelo: ConversationalLLMPort = Depends(
        Provide[ApplicationContainer.conversational_adapter]
    ),
    construir=Depends(get_conversation_service_factory),
):
    servicio = construir(token, modelo)

    resultado = servicio.responder(
        mensaje=request.mensaje,
        borrador=request.borrador,
        turnos=request.turnos,
        ahora=datetime.now(timezone.utc),
        ya_pregunte=request.ya_pregunte,
        energia=request.energia,
    )

    return ConversarResponse(
        tipo=resultado.tipo,
        mensaje=resultado.mensaje,
        borrador=resultado.borrador,
        turnos=resultado.turnos,
        propuesta=(
            PropuestaResponse(
                tipo=resultado.propuesta.tipo,
                borrador=resultado.propuesta.borrador,
                activity_id=resultado.propuesta.activity_id,
            )
            if resultado.propuesta
            else None
        ),
    )
