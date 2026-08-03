"""Perfil del usuario y ajustes de planificacion."""

from fastapi import APIRouter, Depends

from domain.entities.profile import Perfil
from domain.entities.user_settings import AjustesUsuario
from domain.ports.outbound.profile_repository_port import (
    AjustesRepositoryPort,
    PerfilRepositoryPort,
)
from infrastructure.adapters.inbound.api.auth import (
    AuthenticatedUser,
    get_current_user,
)
from infrastructure.adapters.inbound.api.v1.activities_router import get_access_token
from infrastructure.adapters.outbound.supabase.profile_repository import (
    SupabaseAjustesRepository,
    SupabasePerfilRepository,
)
from schemas.profile import (
    ProfilePayload,
    ProfileResponse,
    SettingsPatch,
    SettingsResponse,
)

router = APIRouter(prefix="/api/v1", tags=["Perfil"])

# Campo del contrato HTTP -> campo del dominio.
_CAMPOS_AJUSTES = {
    "start_hour": "inicio_dia",
    "end_hour": "fin_dia",
    "dia_inicio": "dia_inicio",
    "dias_totales": "dias_totales",
    "per_day_start_hours": "inicio_por_dia",
    "per_day_end_hours": "fin_por_dia",
    "custom_energy_pattern": "patron_energia_manual",
}


def get_perfil_repository() -> PerfilRepositoryPort:
    return SupabasePerfilRepository()


def get_ajustes_repository() -> AjustesRepositoryPort:
    return SupabaseAjustesRepository()


def _perfil_a_respuesta(perfil: Perfil) -> ProfileResponse:
    return ProfileResponse(
        id=perfil.id,
        username=perfil.nombre_usuario,
        energy_level=perfil.nivel_energia,
        wake_up_time=perfil.hora_despertar,
        sleep_time=perfil.hora_dormir,
        is_complete=perfil.esta_completo,
    )


def _ajustes_a_respuesta(ajustes: AjustesUsuario) -> SettingsResponse:
    return SettingsResponse(
        user_id=ajustes.propietario_id,
        start_hour=ajustes.inicio_dia,
        end_hour=ajustes.fin_dia,
        dia_inicio=ajustes.dia_inicio,
        dias_totales=ajustes.dias_totales,
        per_day_start_hours=ajustes.inicio_por_dia,
        per_day_end_hours=ajustes.fin_por_dia,
        custom_energy_pattern=ajustes.patron_energia_manual,
    )


@router.get("/perfil", response_model=ProfileResponse)
def obtener_perfil(
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    repo: PerfilRepositoryPort = Depends(get_perfil_repository),
):
    """Devuelve el perfil, vacio si el onboarding no termino.

    No da 404 cuando falta la fila: para el cliente "todavia no complete el
    onboarding" y "no existe fila" son lo mismo, y un 404 le haria tratar un
    estado normal como un error.
    """
    perfil = repo.get(token)
    return _perfil_a_respuesta(perfil or Perfil(id=user.id))


@router.put("/perfil", response_model=ProfileResponse)
def guardar_perfil(
    payload: ProfilePayload,
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    repo: PerfilRepositoryPort = Depends(get_perfil_repository),
):
    perfil = Perfil(
        id=user.id,
        nombre_usuario=payload.username,
        nivel_energia=payload.energy_level,
        hora_despertar=payload.wake_up_time,
        hora_dormir=payload.sleep_time,
    )
    return _perfil_a_respuesta(repo.save(token, perfil))


@router.delete("/perfil", response_model=ProfileResponse)
def limpiar_perfil(
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    repo: PerfilRepositoryPort = Depends(get_perfil_repository),
):
    """Vacia los campos. La fila queda: la referencia a auth.users con cascade
    y el trigger de alta hacen que nadie la recrearia."""
    repo.clear(token)
    return _perfil_a_respuesta(Perfil(id=user.id))


@router.get("/ajustes", response_model=SettingsResponse)
def obtener_ajustes(
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    repo: AjustesRepositoryPort = Depends(get_ajustes_repository),
):
    return _ajustes_a_respuesta(repo.get(token, user.id))


@router.patch("/ajustes", response_model=SettingsResponse)
def actualizar_ajustes(
    payload: SettingsPatch,
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    repo: AjustesRepositoryPort = Depends(get_ajustes_repository),
):
    """PATCH y no PUT: el cliente cambia un ajuste a la vez.

    exclude_unset distingue "no lo mandaron" de "lo mandaron en null", que
    para per_day_start_hours son cosas distintas —el segundo borra el
    override por dia.
    """
    cambios = payload.model_dump(exclude_unset=True)
    presentes = {
        _CAMPOS_AJUSTES[entrante]: valor
        for entrante, valor in cambios.items()
        if entrante in _CAMPOS_AJUSTES
    }

    return _ajustes_a_respuesta(repo.patch(token, user.id, presentes))
