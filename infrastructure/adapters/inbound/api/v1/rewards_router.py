"""Completar actividades, racha y progreso del dia.

Sin el evento "termine esto" no hay nada que festejar: ni racha, ni progreso,
ni mascota que celebre. Es la pieza que faltaba para que la app tenga un ciclo
y no solo un horario.

Las fechas las manda el cliente. El servidor no puede saber que dia es para el
usuario —el mismo error que ya tiene GET /energia/hoy usando medianoche UTC—,
y "lo hice hoy" es una afirmacion sobre el dia de quien lo dice.
"""

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from domain.ports.outbound.completion_repository_port import CompletadosRepositoryPort
from domain.ports.outbound.schedule_repository_port import EnergiaRepositoryPort
from domain.ports.outbound.user_activity_repository_port import (
    ActividadUsuarioRepositoryPort,
)
from domain.services.rewards.completion import (
    EstadoCompletado,
    OrigenCompletado,
    hoy_del_usuario,
    validar_marcado,
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

#: Cuantos dias hacia atras se sigue pudiendo marcar una ocurrencia.
#: Comparte el valor con `domain/services/rewards/completion.DIAS_DE_GRACIA`;
#: aca solo se repite como techo del carry-over, para no traer el historial
#: entero en cada apertura.
_DIAS_CARRY = 2


def get_completions_repository() -> CompletadosRepositoryPort:
    return SupabaseCompletadosRepository()


class CompletarRequest(BaseModel):
    activity_id: str = Field(min_length=1, max_length=128)
    #: El dia del usuario, no el del servidor.
    fecha: date
    #: Que se esta afirmando. `SIN_RESOLVER` no se puede mandar: es la
    #: ausencia de fila, y para volver a ella esta /descompletar.
    estado: Literal["hecha", "no_hecha"] = "hecha"
    #: De donde vino. No hay "automatico": nunca se marca sola.
    origen: Literal["sesion", "manual", "cierre"] = "manual"
    #: Sin esto el servidor usaria su medianoche para decidir si la fecha es
    #: futura, y en Lima rechazaria marcar hoy durante cinco horas.
    desfase_utc_minutos: int = Field(default=0, ge=-840, le=840)


class CierreDelDiaRequest(BaseModel):
    """Abrir a las once de la noche con el dia entero sin marcar.

    Es el caso mas frecuente, no el raro, y es donde se decide si la app se
    siente como un companero o como un formulario. Cuatro casillas para
    tildar es trabajo administrativo: una pregunta con tres salidas no.
    """

    fecha: date
    #: `todo` resuelve el dia de un toque —el caso mas comun de quien abre la
    #: app—. `algunas` marca solo las dichas y deja el resto en no hecha.
    #: `dificil` no toca nada: cero completadas, cero preguntas, cero
    #: penalizacion, y todo queda SIN_RESOLVER, que no suma pero tampoco
    #: resta. Ese tercer boton es el que ninguna app de habitos tiene.
    respuesta: Literal["todo", "algunas", "dificil"]
    hechas: list[str] = Field(default_factory=list)
    desfase_utc_minutos: int = Field(default=0, ge=-840, le=840)


class RachaResponse(BaseModel):
    actual: int
    mejor: int
    en_riesgo: bool


class ProgresoResponse(BaseModel):
    completadas: int
    total: int
    fraccion: float
    terminado: bool
    #: Lo que se dijo que SI. Es lo unico que cuenta como progreso.
    completados_ids: list[str]
    #: Lo que se dijo que NO. Viaja aparte de las hechas porque no es
    #: progreso, y aparte de la ausencia porque tampoco es "sin resolver":
    #: sin las dos listas el cliente no puede distinguir "me contestaste que
    #: no" de "todavia no me contestaste", y termina preguntando de nuevo lo
    #: que ya tiene respuesta.
    no_hechas_ids: list[str] = Field(default_factory=list)


class EquilibrioResponse(BaseModel):
    """Cuanto hay de cada area de vida.

    Devuelve CONTEOS y no una medida de apertura ya calculada: cuanto se abre
    cada petalo y como se dibuja la flor son decisiones de presentacion que
    van a cambiar con el arte, y no deberian obligar a redesplegar el
    servidor cada vez.
    """

    #: Un valor por cada una de las cinco areas, incluidas las que estan en
    #: cero. Omitirlas dejaria al cliente adivinando si un area falta porque
    #: no hay datos o porque el usuario nunca la toco, que es justamente la
    #: informacion que la pantalla existe para mostrar.
    #:
    #: `historico` es el TAMANO del petalo y nunca baja; `recientes` es la
    #: FORMA de la flor y si cambia. Lo que abre el loto no es el volumen, es
    #: el equilibrio.
    historico: dict[str, int]
    recientes: dict[str, int]
    dias: int
    #: Dias distintos con algo confirmado, desde siempre. Es lo que hace
    #: crecer al sapo, y nunca baja.
    #:
    #: Viaja el numero crudo y no la etapa: donde estan los umbrales es una
    #: decision de producto que se va a mover mientras se prueba el arte, y
    #: moverla no deberia pedir un redespliegue del servidor.
    dias_con_algo: int


class ResumenResponse(BaseModel):
    racha: RachaResponse
    progreso: ProgresoResponse
    #: Los dias con al menos un completado, para dibujar el historial. Van en
    #: esta respuesta porque el calculo de la racha ya los trajo: pedirlos
    #: aparte seria repetir la misma consulta.
    dias_completados: list[date] = Field(default_factory=list)
    #: Lo que quedo sin decir en los dias anteriores dentro de la gracia.
    #: Alimenta el carry-over: si el usuario no abrio la app el dia anterior,
    #: esto le permite responder o reprogramar al dia siguiente. Toda accion
    #: la decide el cliente despues de preguntar; el servidor solo informa.
    pendientes_pasados: list["PendientePasado"] = Field(default_factory=list)


class PendientePasado(BaseModel):
    """Un dia anterior con ocurrencias que nadie respondio todavia."""

    #: Fecha del dia anterior, en formato AAAA-MM-DD del usuario.
    fecha: date
    #: Las actividades de ese dia que quedaron sin resolver (ni hechas ni no
    #: hechas). Solo las que todavia se pueden marcar (dentro de la gracia).
    items: list["PendientePasadoItem"]


class PendientePasadoItem(BaseModel):
    activity_id: str
    titulo: str


def _exigir_fecha_afirmable(fecha: date, desfase_utc_minutos: int) -> None:
    """Deja pasar solo las fechas sobre las que todavia se puede afirmar algo.

    El motivo viaja en la respuesta porque "ese dia ya cerro" y "todavia no
    paso" piden mensajes distintos, y el cliente no deberia adivinar cual.
    """
    motivo = validar_marcado(fecha, hoy=hoy_del_usuario(desfase_utc_minutos))
    if motivo is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"motivo": motivo.value},
        )


@router.post("/completar", status_code=status.HTTP_204_NO_CONTENT)
def completar(
    payload: CompletarRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    repo: CompletadosRepositoryPort = Depends(get_completions_repository),
):
    _exigir_fecha_afirmable(payload.fecha, payload.desfase_utc_minutos)
    repo.marcar(
        token,
        user.id,
        payload.activity_id,
        payload.fecha,
        EstadoCompletado(payload.estado),
        OrigenCompletado(payload.origen),
    )


@router.post("/cerrar-dia", response_model=ProgresoResponse)
def cerrar_dia(
    payload: CierreDelDiaRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    repo: CompletadosRepositoryPort = Depends(get_completions_repository),
    actividades_repo: ActividadUsuarioRepositoryPort = Depends(get_repository),
):
    """Resuelve de una vez todo lo que quedo sin decir ese dia."""
    _exigir_fecha_afirmable(payload.fecha, payload.desfase_utc_minutos)

    # Un dia dificil no escribe nada. Dejarlo en SIN_RESOLVER es deliberado:
    # no suma, pero tampoco resta, y la racha sobrevive porque se apoya en la
    # presencia y no en completar. Marcarlo todo como no hecha seria convertir
    # una respuesta honesta en un registro de fracaso.
    if payload.respuesta != "dificil":
        del_dia = _ids_que_tocan(actividades_repo.list_all(token), payload.fecha)
        dichas = set(payload.hechas)

        for activity_id in del_dia:
            hecha = payload.respuesta == "todo" or activity_id in dichas
            repo.marcar(
                token,
                user.id,
                activity_id,
                payload.fecha,
                EstadoCompletado.HECHA if hecha else EstadoCompletado.NO_HECHA,
                OrigenCompletado.CIERRE,
            )

    estados = repo.estados_del_dia(token, payload.fecha)
    completados = _con_estado(estados, EstadoCompletado.HECHA)
    total = _cuantas_tocan(actividades_repo.list_all(token), payload.fecha)
    progreso = ProgresoDelDia(completadas=len(completados), total=total)

    return ProgresoResponse(
        completadas=progreso.completadas,
        total=progreso.total,
        fraccion=progreso.fraccion,
        terminado=progreso.terminado,
        completados_ids=completados,
        no_hechas_ids=_con_estado(estados, EstadoCompletado.NO_HECHA),
    )


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
    # Los estados y no solo los completados: de las mismas filas salen las
    # dos listas, asi que pedirlas por separado serian dos viajes contra un
    # servidor que tarda en despertar.
    estados = repo.estados_del_dia(token, fecha)
    completados = _con_estado(estados, EstadoCompletado.HECHA)
    no_hechas = _con_estado(estados, EstadoCompletado.NO_HECHA)

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
            no_hechas_ids=no_hechas,
        ),
        # Ordenados: el cliente los dibuja en una linea de tiempo.
        dias_completados=sorted(dias_con_algo_hecho),
        pendientes_pasados=_pendientes_pasados(
            actividades_repo, repo, token, fecha, desfase_utc_minutos
        ),
    )


#: Las cinco areas, y ese es el techo. Un loto de doce petalos no se lee a
#: 72 px y cada area nueva diluye a las demas.
_AREAS = ("estudio", "trabajo", "cuerpo", "vinculos", "yo")

#: Cuanto mira hacia atras el equilibrio. Tres meses es suficiente para que
#: una temporada de examenes no defina la flor para siempre, y corto para que
#: lo que hiciste este mes se note.
_DIAS_DE_EQUILIBRIO = 90


@router.get("/equilibrio", response_model=EquilibrioResponse)
def equilibrio(
    fecha: date,
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    repo: CompletadosRepositoryPort = Depends(get_completions_repository),
):
    """Cuanto hay de cada parte de tu vida.

    La racha no puede decir esto: se pueden llevar treinta dias seguidos
    estudiando y tres semanas sin moverse ni ver a nadie, y la racha felicita
    igual.
    """
    desde = fecha - timedelta(days=_DIAS_DE_EQUILIBRIO)
    conteos = repo.conteos_por_area(token, desde)

    return EquilibrioResponse(
        historico={a: conteos.historico.get(a, 0) for a in _AREAS},
        recientes={a: conteos.recientes.get(a, 0) for a in _AREAS},
        dias=_DIAS_DE_EQUILIBRIO,
        dias_con_algo=conteos.dias_con_algo,
    )


def _fecha_unica(actividad) -> date | None:
    """La fecha propia de un evento que ocurre una sola vez, si la tiene.

    Con `fecha_unica` puesta, los dias de la semana no aplican: la actividad
    ocurre ese dia y ningun otro. Es el mismo criterio que
    `domain.services.calendar.expansion.expandir`, y tiene que serlo: el
    horario que el usuario ve sale de alla, asi que contar aca distinto
    produce un total que no coincide con lo que la pantalla muestra.
    """
    valor = getattr(actividad, "fecha_unica", None)
    if valor is None:
        return None
    return valor if isinstance(valor, date) else date.fromisoformat(str(valor)[:10])


def _corresponde_a(actividad, fecha: date) -> bool:
    """Si esa actividad ocurre ese dia.

    Se cuenta sobre la definicion y no sobre el horario generado: el horario
    puede no existir todavia —una cuenta nueva no genero ninguno— y el
    progreso del dia deberia funcionar igual desde el primer minuto.

    Las de dia opcional cuentan una vez: el solver elige el dia, asi que
    sumarlas en cada dia habilitado inflaria el total de toda la semana.
    """
    unica = _fecha_unica(actividad)
    if unica is not None:
        return unica == fecha

    indices = {
        DIA_A_INDICE[d] for d in actividad.dias_habilitados if d in DIA_A_INDICE
    }
    if actividad.dia_opcional:
        return bool(indices)
    return fecha.weekday() in indices


def _cuantas_tocan(actividades, fecha: date) -> int:
    """Cuantas actividades corresponden a ese dia."""
    return sum(1 for actividad in actividades if _corresponde_a(actividad, fecha))


def _con_estado(estados: dict[str, str], estado: EstadoCompletado) -> list[str]:
    """Los ids que tienen ese estado. Ordenados, para que la respuesta no
    dependa del orden en que PostgREST devolvio las filas."""
    return sorted(i for i, e in estados.items() if e == estado.value)


def _ids_que_tocan(actividades, fecha: date) -> list[str]:
    """Los ids de las actividades que corresponden a ese dia.

    Es la contraparte de `_cuantas_tocan`: el cierre no puede contar, tiene
    que saber a cuales referirse.
    """
    return [actividad.id for actividad in actividades if _corresponde_a(actividad, fecha)]


def _pendientes_pasados(
    actividades_repo: ActividadUsuarioRepositoryPort,
    repo: CompletadosRepositoryPort,
    token: str,
    hoy: date,
    desfase_utc_minutos: int,
) -> list[PendientePasado]:
    """Los dias anteriores (dentro de la gracia) con ocurrencias sin responder.

    Solo entra en el carry-over lo que todavia se puede marcar: una fecha
    fuera del margen de gracia ya no admite afirmacion, asi que listarla solo
    confundiria. Se usa el dia del usuario (desfase) para saber cual es el
    ayer real.
    """
    hoy_usuario = hoy_del_usuario(desfase_utc_minutos)
    actividades = actividades_repo.list_all(token)
    nombres = {a.id: a.nombre for a in actividades}

    resultado: list[PendientePasado] = []
    for atras in range(1, _DIAS_CARRY + 1):
        dia = hoy_usuario - timedelta(days=atras)
        # Fuera de la gracia no se puede afirmar nada de ese dia: se descarta.
        if validar_marcado(dia, hoy=hoy_usuario) is not None:
            continue

        tocan = _ids_que_tocan(actividades, dia)
        if not tocan:
            continue

        estados = repo.estados_del_dia(token, dia)
        # Sin resolver = toca ese dia y nadie dijo ni sí ni no todavía.
        sin_resolver = [
            PendientePasadoItem(activity_id=i, titulo=nombres.get(i, "Actividad"))
            for i in tocan
            if i not in estados
        ]
        if sin_resolver:
            resultado.append(
                PendientePasado(fecha=dia, items=sin_resolver)
            )

    # Del más reciente al más viejo: lo de ayer es lo primero que hay que ver.
    return resultado
