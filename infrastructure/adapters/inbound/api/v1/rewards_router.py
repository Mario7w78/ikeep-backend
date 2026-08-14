"""Completar actividades, racha y progreso del dia.

Sin el evento "termine esto" no hay nada que festejar: ni racha, ni progreso,
ni mascota que celebre. Es la pieza que faltaba para que la app tenga un ciclo
y no solo un horario.

Las fechas las manda el cliente. El servidor no puede saber que dia es para el
usuario —el mismo error que ya tiene GET /energia/hoy usando medianoche UTC—,
y "lo hice hoy" es una afirmacion sobre el dia de quien lo dice.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from domain.ports.outbound.completion_repository_port import CompletadosRepositoryPort
from domain.ports.outbound.schedule_repository_port import EnergiaRepositoryPort
from domain.ports.outbound.user_activity_repository_port import (
    ActividadUsuarioRepositoryPort,
)
from domain.services.rewards.streak import ProgresoDelDia, calcular_racha
from domain.services.scheduling.flattener import DIA_A_INDICE
from infrastructure.adapters.inbound.api.auth import (
    AuthenticatedUser,
    get_current_user,
)
from infrastructure.adapters.inbound.api.v1.activities_router import (
    get_access_token,
    get_repository,
)
from infrastructure.adapters.inbound.api.v1.stored_schedule_router import (
    get_energia_repository,
)
from infrastructure.adapters.outbound.supabase.completion_repository import (
    SupabaseCompletadosRepository,
)

router = APIRouter(prefix="/api/v1/logros", tags=["Logros"])

#: Cuanto se mira hacia atras para la racha. Un ano cubre cualquier racha
#: real y evita traerse el historial entero en cada apertura de la app.
_VENTANA_DIAS = 365


def get_completions_repository() -> CompletadosRepositoryPort:
    return SupabaseCompletadosRepository()


class CompletarRequest(BaseModel):
    activity_id: str = Field(min_length=1, max_length=128)
    #: El dia del usuario, no el del servidor.
    fecha: date


class RachaResponse(BaseModel):
    actual: int
    mejor: int
    en_riesgo: bool


class ProgresoResponse(BaseModel):
    completadas: int
    total: int
    fraccion: float
    terminado: bool
    completados_ids: list[str]


class ResumenResponse(BaseModel):
    racha: RachaResponse
    progreso: ProgresoResponse
    #: Los dias con al menos un completado, para dibujar el historial. Van en
    #: esta respuesta porque el calculo de la racha ya los trajo: pedirlos
    #: aparte seria repetir la misma consulta.
    dias_completados: list[date] = Field(default_factory=list)


@router.post("/completar", status_code=status.HTTP_204_NO_CONTENT)
def completar(
    payload: CompletarRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    repo: CompletadosRepositoryPort = Depends(get_completions_repository),
):
    repo.marcar(token, user.id, payload.activity_id, payload.fecha)


@router.post("/descompletar", status_code=status.HTTP_204_NO_CONTENT)
def descompletar(
    payload: CompletarRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    repo: CompletadosRepositoryPort = Depends(get_completions_repository),
):
    """Tocar por error no deberia ser definitivo."""
    repo.desmarcar(token, payload.activity_id, payload.fecha)


@router.get("/resumen", response_model=ResumenResponse)
def resumen(
    fecha: date,
    desfase_utc_minutos: int = Query(default=0, ge=-840, le=840),
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    repo: CompletadosRepositoryPort = Depends(get_completions_repository),
    actividades_repo: ActividadUsuarioRepositoryPort = Depends(get_repository),
    energia_repo: EnergiaRepositoryPort = Depends(get_energia_repository),
):
    """Racha y progreso en una sola llamada.

    Van juntos porque se muestran juntos —el badge de racha y el anillo del
    dia estan en la misma pantalla— y separarlos serian dos viajes contra un
    servidor que tarda en despertar.
    """
    completados = repo.del_dia(token, fecha)

    # La racha mide PRESENCIA, no rendimiento: cuenta los dias en que el
    # usuario aparecio y dijo como estaba. Antes contaba dias con al menos un
    # completado, y se rompia justo en la semana de examenes — el momento en
    # que mas importa que la app no castigue.
    desde = fecha - timedelta(days=_VENTANA_DIAS)
    dias_presente = energia_repo.dias_con_registro(token, desde, desfase_utc_minutos)
    racha = calcular_racha(dias_presente, fecha)

    # El historial que dibuja la cuadricula sigue siendo el de lo hecho: son
    # dos preguntas distintas y la pantalla muestra las dos.
    dias_con_algo_hecho = repo.dias_con_actividad(token, desde)

    total = _cuantas_tocan(actividades_repo.list_all(token), fecha)
    progreso = ProgresoDelDia(completadas=len(completados), total=total)

    return ResumenResponse(
        racha=RachaResponse(
            actual=racha.actual, mejor=racha.mejor, en_riesgo=racha.en_riesgo
        ),
        progreso=ProgresoResponse(
            completadas=progreso.completadas,
            total=progreso.total,
            fraccion=progreso.fraccion,
            terminado=progreso.terminado,
            completados_ids=completados,
        ),
        # Ordenados: el cliente los dibuja en una linea de tiempo.
        dias_completados=sorted(dias_con_algo_hecho),
    )


def _cuantas_tocan(actividades, fecha: date) -> int:
    """Cuantas actividades corresponden a ese dia de la semana.

    Se cuenta sobre la definicion y no sobre el horario generado: el horario
    puede no existir todavia —una cuenta nueva no genero ninguno— y el
    progreso del dia deberia funcionar igual desde el primer minuto.

    Las de dia opcional cuentan una vez: el solver elige el dia, asi que
    sumarlas en cada dia habilitado inflaria el total de toda la semana.
    """
    indice = fecha.weekday()
    total = 0
    for actividad in actividades:
        indices = {
            DIA_A_INDICE[d] for d in actividad.dias_habilitados if d in DIA_A_INDICE
        }
        if actividad.dia_opcional:
            total += 1 if indices else 0
        elif indice in indices:
            total += 1
    return total
