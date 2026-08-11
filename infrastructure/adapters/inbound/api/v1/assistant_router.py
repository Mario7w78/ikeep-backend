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
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator

from domain.entities.stored_schedule import HorarioGuardado
from domain.ports.inbound.scheduler_port import AbstractSchedulerService
from domain.ports.outbound.conversational_llm_port import ConversationalLLMPort
from domain.services.scheduling.apply_proposal import ErrorAlAplicar, aplicar
from domain.services.assistant.conversation import ServicioConversacion
from infrastructure.adapters.inbound.api.auth import (
    AuthenticatedUser,
    get_current_user,
)
from infrastructure.adapters.inbound.api.mappers import solicitud_to_domain
from infrastructure.adapters.inbound.api.v1.activities_router import (
    _a_dominio,
    get_access_token,
)
from infrastructure.adapters.outbound.assistant.data_source import (
    RepositorioFuenteDeDatos,
)
from infrastructure.adapters.outbound.supabase.profile_repository import (
    SupabaseAjustesRepository,
)
from infrastructure.adapters.outbound.supabase.schedule_repository import (
    SupabaseHorarioRepository,
)
from infrastructure.adapters.outbound.supabase.user_activity_repository import (
    SupabaseActividadUsuarioRepository,
)
from infrastructure.config.container import ApplicationContainer
from schemas.assistant import Borrador
from schemas.schedule_request import SolicitudHorario
from schemas.user_activity import ActivityPayload

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


class AplicarRequest(BaseModel):
    """Una propuesta que el usuario ya confirmo.

    Llega con el desfase del reloj del cliente porque los turnos se guardan
    como instantes UTC y la hora que importa es la que el usuario ve: una
    clase a las 10:00 en Lima viaja como las 15:00Z, y leerla tal cual la
    correria cinco horas.
    """

    tipo: Literal["crear", "modificar", "eliminar", "regenerar"]
    actividad: ActivityPayload | None = None
    activity_id: str | None = None
    desfase_utc_minutos: int = Field(default=0, ge=-840, le=840)
    nivel_energia: int = Field(default=2, ge=0, le=4)

    @model_validator(mode="after")
    def _exige_lo_que_el_tipo_necesita(self) -> "AplicarRequest":
        if self.tipo in ("crear", "modificar") and self.actividad is None:
            raise ValueError(f"'{self.tipo}' necesita la actividad.")
        if self.tipo == "eliminar" and not self.activity_id:
            raise ValueError("'eliminar' necesita activity_id.")
        return self


class AplicarResponse(BaseModel):
    estado: str | None = None
    mensaje: str | None = None
    recomendaciones: list[Any] = Field(default_factory=list)
    tareas_omitidas: list[Any] = Field(default_factory=list)
    scheduled_activities: list[dict[str, Any]] = Field(default_factory=list)


def get_apply_repos_factory():
    """Se sustituye en los tests para no tocar repositorios reales."""
    return _construir_repos


class _ReposDeAplicar:
    """Reune en un solo objeto lo que el servicio necesita del exterior.

    El token viaja en cada llamada porque es lo que hace que RLS acote lo que
    se puede leer y escribir: el servidor nunca actua con mas permisos que
    quien pidio la accion.
    """

    def __init__(self, access_token: str, user_id: str, scheduler):
        self._token = access_token
        self._user_id = user_id
        self._scheduler = scheduler
        self._actividades = SupabaseActividadUsuarioRepository()
        self._horarios = SupabaseHorarioRepository()
        self._ajustes = SupabaseAjustesRepository()

    def actividades(self):
        return self._actividades.list_all(self._token)

    def guardar_actividad(self, actividad):
        self._actividades.save(self._token, actividad)

    def borrar_actividad(self, activity_id):
        self._actividades.delete(self._token, activity_id)

    def obtener_actividad(self, activity_id):
        return self._actividades.get(self._token, activity_id)

    def ajustes(self):
        return self._ajustes.get(self._token, self._user_id)

    def generar(self, solicitud):
        return self._scheduler.generar(solicitud_to_domain(SolicitudHorario(**solicitud)))

    def guardar_horario(self, resultado):
        self._horarios.save(
            self._token,
            HorarioGuardado(
                propietario_id=self._user_id,
                estado=resultado.estado,
                mensaje=resultado.mensaje,
                recomendaciones=resultado.recomendaciones,
                tareas_omitidas=resultado.tareas_omitidas,
                actividades_programadas=resultado.actividades_programadas,
            ),
        )


def _construir_repos(access_token: str, user_id: str, scheduler):
    return _ReposDeAplicar(access_token, user_id, scheduler)


@router.post("/aplicar", response_model=AplicarResponse)
@inject
def aplicar_propuesta(
    request: AplicarRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    scheduler: AbstractSchedulerService = Depends(
        Provide[ApplicationContainer.scheduler_service]
    ),
    construir=Depends(get_apply_repos_factory),
):
    """Guarda, regenera y persiste en una sola llamada.

    Antes el cliente hacia tres viajes y compensaba a mano si el solver
    fallaba. Eso ponia logica de dominio en la capa de presentacion y pagaba
    el arranque en frio de Render en cada salto.
    """
    actividad = (
        _a_dominio(request.actividad, request.actividad.id, user.id)
        if request.actividad
        else None
    )

    try:
        resultado = aplicar(
            construir(token, user.id, scheduler),
            tipo=request.tipo,
            actividad=actividad,
            activity_id=request.activity_id,
            desfase_utc_minutos=request.desfase_utc_minutos,
            nivel_energia=request.nivel_energia,
        )
    except ErrorAlAplicar as error:
        # 409 y no 500: el servidor funciono. Lo que no se pudo fue dejar el
        # horario en un estado bueno con lo que el usuario pidio, y ya se
        # deshizo el cambio.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"No se pudo aplicar el cambio: {error}",
        ) from error

    return AplicarResponse(
        estado=resultado.estado,
        mensaje=resultado.mensaje,
        recomendaciones=resultado.recomendaciones,
        tareas_omitidas=resultado.tareas_omitidas,
        scheduled_activities=resultado.actividades_programadas,
    )
