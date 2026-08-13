"""El calendario: qué ocurre cada día de un rango de fechas.

Devuelve la plantilla semanal ya expandida a fechas reales, con las
excepciones aplicadas y los eventos únicos incluidos. Es lo que permite
dibujar un mes como el de Google Calendar en vez de una semana que se repite.

El rango lo pide el cliente y las fechas son las suyas: el servidor no conoce
su huso. Es la misma regla que ya aplican /aplicar, /logros y /energia/hoy.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator

from domain.ports.outbound.exception_repository_port import ExcepcionesRepositoryPort
from domain.ports.outbound.user_activity_repository_port import (
    ActividadUsuarioRepositoryPort,
)
from domain.services.calendar.expansion import Excepcion, expandir
from infrastructure.adapters.inbound.api.auth import (
    AuthenticatedUser,
    get_current_user,
)
from infrastructure.adapters.inbound.api.v1.activities_router import (
    _a_respuesta,
    get_access_token,
    get_repository,
)
from infrastructure.adapters.outbound.supabase.exception_repository import (
    SupabaseExcepcionesRepository,
)
from schemas.user_activity import ActivityResponse

router = APIRouter(prefix="/api/v1/calendario", tags=["Calendario"])

#: Tope del rango consultable de una vez.
#:
#: Un año entero de ocurrencias en una sola respuesta es un payload que el
#: teléfono no puede dibujar igual, y la vista más grande que la app ofrece es
#: el mes. Con 120 días entra un trimestre, que cubre cualquier navegación
#: razonable sin abrir la puerta a pedir una década.
_MAXIMO_DIAS = 120


def get_exceptions_repository() -> ExcepcionesRepositoryPort:
    return SupabaseExcepcionesRepository()


class OcurrenciaResponse(BaseModel):
    fecha: date
    actividad: ActivityResponse
    #: De dónde se movió, si se movió. La pantalla lo necesita para poder
    #: decir "reprogramada" en vez de mostrarla como si siempre hubiera sido
    #: ese día.
    movida_desde: date | None = None
    es_unica: bool = False


class CalendarioResponse(BaseModel):
    desde: date
    hasta: date
    ocurrencias: list[OcurrenciaResponse]


class ExcepcionRequest(BaseModel):
    activity_id: str = Field(min_length=1, max_length=128)
    #: El día en que la regla decía que ocurría.
    fecha: date
    tipo: str = Field(pattern="^(cancelada|movida)$")
    nueva_fecha: date | None = None

    @model_validator(mode="after")
    def _destino_coherente(self) -> "ExcepcionRequest":
        if self.tipo == "movida" and self.nueva_fecha is None:
            raise ValueError("Mover una ocurrencia necesita nueva_fecha.")
        if self.tipo == "cancelada" and self.nueva_fecha is not None:
            raise ValueError("Cancelar una ocurrencia no lleva nueva_fecha.")
        return self


@router.get("", response_model=CalendarioResponse)
def ver_calendario(
    desde: date,
    hasta: date,
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    actividades_repo: ActividadUsuarioRepositoryPort = Depends(get_repository),
    excepciones_repo: ExcepcionesRepositoryPort = Depends(get_exceptions_repository),
):
    """Qué ocurre cada día del rango, con los extremos incluidos."""
    if hasta < desde:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="'hasta' no puede ser anterior a 'desde'.",
        )
    if (hasta - desde) > timedelta(days=_MAXIMO_DIAS):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"El rango no puede superar los {_MAXIMO_DIAS} días.",
        )

    ocurrencias = expandir(
        actividades_repo.list_all(token),
        excepciones_repo.del_rango(token, desde, hasta),
        desde,
        hasta,
    )

    return CalendarioResponse(
        desde=desde,
        hasta=hasta,
        ocurrencias=[
            OcurrenciaResponse(
                fecha=o.fecha,
                actividad=_a_respuesta(o.actividad),
                movida_desde=o.movida_desde,
                es_unica=o.es_unica,
            )
            for o in ocurrencias
        ],
    )


@router.put("/excepciones", status_code=status.HTTP_204_NO_CONTENT)
def guardar_excepcion(
    payload: ExcepcionRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    repo: ExcepcionesRepositoryPort = Depends(get_exceptions_repository),
):
    """Cancela o mueve una ocurrencia.

    PUT y no POST: hay como máximo una excepción por (actividad, fecha), así
    que repetir la llamada reemplaza en vez de acumular.
    """
    repo.guardar(
        token,
        user.id,
        Excepcion(
            activity_id=payload.activity_id,
            fecha=payload.fecha,
            tipo=payload.tipo,  # type: ignore[arg-type]
            nueva_fecha=payload.nueva_fecha,
        ),
    )


@router.delete("/excepciones", status_code=status.HTTP_204_NO_CONTENT)
def borrar_excepcion(
    activity_id: str = Query(min_length=1, max_length=128),
    fecha: date = Query(),
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    repo: ExcepcionesRepositoryPort = Depends(get_exceptions_repository),
):
    """Deshace la excepción: la ocurrencia vuelve a su lugar."""
    repo.borrar(token, activity_id, fecha)
