"""CRUD de las actividades guardadas del usuario.

Las rutas son delgadas a proposito: autenticar, mapear, delegar. El scope por
usuario no se resuelve aca sino en Postgres via RLS, con el token que viaja
en cada peticion.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from domain.entities.user_activity import ActividadUsuario
from domain.ports.outbound.user_activity_repository_port import (
    ActividadUsuarioRepositoryPort,
)
from infrastructure.adapters.inbound.api.auth import (
    AuthenticatedUser,
    get_current_user,
)
from infrastructure.adapters.outbound.supabase.user_activity_repository import (
    SupabaseActividadUsuarioRepository,
)
from schemas.user_activity import ActivityPayload, ActivityResponse

router = APIRouter(prefix="/api/v1/actividades", tags=["Actividades"])

_bearer = HTTPBearer(auto_error=False)


def get_access_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """El token en crudo, que el repositorio reenvia a PostgREST.

    get_current_user ya lo valido; aca solo hace falta el texto para que RLS
    actue en nombre del usuario.
    """
    return credentials.credentials if credentials else ""


def get_repository() -> ActividadUsuarioRepositoryPort:
    return SupabaseActividadUsuarioRepository()


def _a_dominio(payload: ActivityPayload, activity_id: str, user_id: str) -> ActividadUsuario:
    """Arma la entidad con el id de la URL y el dueño del token.

    Ninguno de los dos se toma del cuerpo: el id de la URL es el recurso que
    se esta direccionando, y el dueño solo puede salir de algo firmado.
    """
    return ActividadUsuario(
        id=activity_id,
        propietario_id=user_id,
        nombre=payload.title,
        tipo=payload.type,
        identidad=payload.identity,
        prioridad=payload.priority,
        dificultad=payload.difficulty,
        fecha_limite=payload.deadline,
        dias_habilitados=payload.days_enabled,
        config_por_dia=payload.days_config,
        dia_opcional=payload.optional_day,
        dia_desde=payload.day_from,
        dia_hasta=payload.day_to,
        es_ancla=payload.is_anchor,
    )


def _a_respuesta(actividad: ActividadUsuario) -> ActivityResponse:
    return ActivityResponse(
        id=actividad.id,
        user_id=actividad.propietario_id,
        title=actividad.nombre,
        type=actividad.tipo,
        identity=actividad.identidad,
        priority=actividad.prioridad,
        difficulty=actividad.dificultad,
        deadline=actividad.fecha_limite,
        days_enabled=actividad.dias_habilitados,
        days_config=actividad.config_por_dia,
        optional_day=actividad.dia_opcional,
        day_from=actividad.dia_desde,
        day_to=actividad.dia_hasta,
        is_anchor=actividad.es_ancla,
    )


# Las rutas son `def` y no `async def` a proposito: supabase-py es sincrono y
# bloqueante, y FastAPI corre las funciones sincronas en un threadpool. Con
# `async def` bloquearian el event loop durante toda la latencia de red.
@router.get("", response_model=list[ActivityResponse])
def listar_actividades(
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    repo: ActividadUsuarioRepositoryPort = Depends(get_repository),
):
    return [_a_respuesta(a) for a in repo.list_all(token)]


@router.get("/{activity_id}", response_model=ActivityResponse)
def obtener_actividad(
    activity_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    repo: ActividadUsuarioRepositoryPort = Depends(get_repository),
):
    actividad = repo.get(token, activity_id)
    if actividad is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La actividad no existe.",
        )
    return _a_respuesta(actividad)


@router.put("/{activity_id}", response_model=ActivityResponse)
def guardar_actividad(
    activity_id: str,
    payload: ActivityPayload,
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    repo: ActividadUsuarioRepositoryPort = Depends(get_repository),
):
    """PUT y no POST: el cliente genera los ids, asi que crear y reemplazar
    son la misma operacion y conviene que sea idempotente."""
    guardada = repo.save(token, _a_dominio(payload, activity_id, user.id))
    return _a_respuesta(guardada)


@router.delete("/{activity_id}", status_code=status.HTTP_204_NO_CONTENT)
def borrar_actividad(
    activity_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    repo: ActividadUsuarioRepositoryPort = Depends(get_repository),
):
    repo.delete(token, activity_id)
