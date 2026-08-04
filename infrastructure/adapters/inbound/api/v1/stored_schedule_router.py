"""Horario guardado del usuario e historial de energia."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, status

from domain.entities.energy_record import (
    DIAS_DE_HISTORIAL_POR_DEFECTO,
    RegistroEnergia,
)
from domain.entities.stored_schedule import HorarioGuardado
from domain.ports.outbound.schedule_repository_port import (
    EnergiaRepositoryPort,
    HorarioRepositoryPort,
)
from infrastructure.adapters.inbound.api.auth import (
    AuthenticatedUser,
    get_current_user,
)
from infrastructure.adapters.inbound.api.v1.activities_router import get_access_token
from infrastructure.adapters.outbound.supabase.schedule_repository import (
    SupabaseEnergiaRepository,
    SupabaseHorarioRepository,
)
from schemas.stored_schedule import (
    EnergyPayload,
    EnergyResponse,
    EnergyTodayResponse,
    SchedulePayload,
    ScheduleResponse,
)

router = APIRouter(prefix="/api/v1", tags=["Horario"])


def get_horario_repository() -> HorarioRepositoryPort:
    return SupabaseHorarioRepository()


def get_energia_repository() -> EnergiaRepositoryPort:
    return SupabaseEnergiaRepository()


def _horario_a_respuesta(horario: HorarioGuardado) -> ScheduleResponse:
    return ScheduleResponse(
        user_id=horario.propietario_id,
        estado=horario.estado,
        mensaje=horario.mensaje,
        recomendaciones=horario.recomendaciones,
        tareas_omitidas=horario.tareas_omitidas,
        scheduled_activities=horario.actividades_programadas,
        created_at=horario.creado_en,
    )


@router.get("/horario", response_model=ScheduleResponse)
def obtener_horario(
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    repo: HorarioRepositoryPort = Depends(get_horario_repository),
):
    """Devuelve el horario vigente, o uno vacio si todavia no genero ninguno.

    Sin 404: "no genere horario todavia" es el estado inicial de cualquier
    cuenta nueva, no un error que el cliente deba manejar aparte.
    """
    horario = repo.get(token)
    return _horario_a_respuesta(horario or HorarioGuardado(propietario_id=user.id))


@router.put("/horario", response_model=ScheduleResponse)
def guardar_horario(
    payload: SchedulePayload,
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    repo: HorarioRepositoryPort = Depends(get_horario_repository),
):
    horario = HorarioGuardado(
        propietario_id=user.id,
        estado=payload.estado,
        mensaje=payload.mensaje,
        recomendaciones=payload.recomendaciones,
        tareas_omitidas=payload.tareas_omitidas,
        actividades_programadas=payload.scheduled_activities,
    )
    return _horario_a_respuesta(repo.save(token, horario))


@router.delete("/horario", status_code=status.HTTP_204_NO_CONTENT)
def borrar_horario(
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    repo: HorarioRepositoryPort = Depends(get_horario_repository),
):
    repo.delete(token)


@router.get("/energia", response_model=list[EnergyResponse])
def historial_de_energia(
    dias: int = Query(default=DIAS_DE_HISTORIAL_POR_DEFECTO, ge=1, le=90),
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    repo: EnergiaRepositoryPort = Depends(get_energia_repository),
):
    return [
        EnergyResponse(
            timestamp=r.momento,
            nivel=r.nivel,
            dia_semana=r.dia_semana,
            contexto=r.contexto,
        )
        for r in repo.history(token, dias)
    ]


@router.post(
    "/energia", response_model=EnergyResponse, status_code=status.HTTP_201_CREATED
)
def registrar_energia(
    payload: EnergyPayload,
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    repo: EnergiaRepositoryPort = Depends(get_energia_repository),
):
    momento = payload.timestamp or datetime.now(timezone.utc).isoformat()
    registro = RegistroEnergia(
        propietario_id=user.id,
        momento=momento,
        # El dia de la semana se deriva del momento y no se acepta del
        # cliente: son el mismo dato, y aceptar los dos permite que lleguen
        # contradiciendose. Python usa lunes=0, igual que el cliente.
        dia_semana=_dia_semana(momento),
        nivel=payload.nivel,
        contexto=payload.contexto,
    )
    guardado = repo.add(token, registro)
    return EnergyResponse(
        timestamp=guardado.momento,
        nivel=guardado.nivel,
        dia_semana=guardado.dia_semana,
        contexto=guardado.contexto,
    )


@router.get("/energia/hoy", response_model=EnergyTodayResponse)
def reporto_energia_hoy(
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    repo: EnergiaRepositoryPort = Depends(get_energia_repository),
):
    return EnergyTodayResponse(reportado=repo.reported_today(token))


def _dia_semana(momento: str) -> int:
    """0 = lunes ... 6 = domingo.

    Si el timestamp no se puede interpretar se cae al dia actual en vez de
    fallar: perder la precision de un registro de energia es preferible a
    rechazar el reporte del usuario.
    """
    try:
        return datetime.fromisoformat(momento.replace("Z", "+00:00")).weekday()
    except ValueError:
        return datetime.now(timezone.utc).weekday()
