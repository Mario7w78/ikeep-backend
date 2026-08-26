"""Los endpoints de la integracion con Google Calendar.

Un solo archivo (D1) porque los cuatro comparten dependencias: el puerto de
Google, el repositorio de tokens y la guardia de configuracion. Partirlo en
dos routers seria dos archivos importando lo mismo.

El flujo OAuth tiene una particularidad que decide todo: el callback llega
desde el NAVEGADOR, sin JWT de Supabase. No hay forma de saber quien era a
menos que el propio inicio del flujo se lo haya dicho — y firmado, porque un
state sin firma es un lugar libre para cualquiera. Por eso `state` es un JWT
(HS256, 10 minutos) que viaja con el code_verifier PKCE adentro: el backend
no guarda nada del flujo y aun asi sabe de quien es y que nadie lo monto.
"""

import base64
import hashlib
import secrets
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from domain.ports.outbound.google_calendar_port import (
    ErrorDeGoogle,
    GoogleCalendarPort,
)
from domain.ports.outbound.google_event_repository_port import (
    GoogleEventsRepositoryPort,
)
from domain.ports.outbound.google_token_repository_port import (
    GoogleTokensRepositoryPort,
    TokensDeConexion,
)
from domain.services.google.sincronizar import (
    Sincronizacion,
    dias_solapados,
    sincronizar,
)
from infrastructure.adapters.inbound.api.auth import AuthenticatedUser, get_current_user
from infrastructure.adapters.inbound.api.v1.activities_router import get_access_token
from infrastructure.adapters.outbound.google.calendar_client import HttpxGoogleCalendar
from infrastructure.adapters.outbound.google.token_cipher import (
    ClaveFernetAusente,
    cifrar,
    descifrar,
)
from infrastructure.adapters.outbound.supabase.google_event_repository import (
    SupabaseGoogleEventsRepository,
)
from infrastructure.adapters.outbound.supabase.google_token_repository import (
    SupabaseGoogleTokensRepository,
    guardar_como_servicio,
)
from infrastructure.config.settings import get_settings
from schemas.google import (
    CalendarioGoogleResponse,
    EstadoConexionResponse,
    EventoImportadoResponse,
    InicioResponse,
)

router = APIRouter(tags=["Google Calendar"])

#: A donde vuelve el navegador despues del consentimiento. Es un deep link:
#: el sistema operativo lo recibe la app, no hay servidor que conteste.
_DESTINO_APP = "lotus://google/callback"

#: El state vale 10 minutos: consentir tarda segundos, no cuartos de hora.
_VIDA_DEL_STATE = timedelta(minutes=10)

#: Se refresca ANTES de vencer: un token que vence en 60 segundos ya sirve
#: para fallar a mitad de una llamada lenta.
_MARGEN_DE_REFRESCO = timedelta(seconds=60)

_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"

_URL_AUTORIZAR = "https://accounts.google.com/o/oauth2/v2/auth"


def get_google_client() -> GoogleCalendarPort:
    return HttpxGoogleCalendar()


def get_google_tokens_repository() -> GoogleTokensRepositoryPort:
    return SupabaseGoogleTokensRepository()


def get_google_events_repository() -> GoogleEventsRepositoryPort:
    return SupabaseGoogleEventsRepository()


# --------------------------------------------------------------------------
# Errores: la taxonomia de ErrorDeGoogle traducida a HTTP, en UN solo lugar.
# --------------------------------------------------------------------------

def _error_de_configuracion() -> HTTPException:
    # Distinguible por convencion: todo error de configuracion empieza con
    # '[config]'. La app puede mostrar "el servidor no esta preparado" sin
    # parsear frases.
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="[config] El servidor no tiene credenciales de Google.",
    )


def _traducir_google(exc: ErrorDeGoogle) -> HTTPException:
    """La taxonomia completa, sin sorpresas:

    - invalid_grant -> 401 reconectar (reintentar no arregla nada).
    - config/quota/red -> 503 reintento, cada uno diciendo su motivo.
    """
    if exc.clase == "invalid_grant":
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="La conexion con Google expiro: conecta de nuevo.",
        )
    motivos = {
        "config": "[config] Faltan o sobran credenciales de Google.",
        "quota": "[quota] Google alcanzo su limite; reintenta mas tarde.",
        "red": "[red] Google no respondio; reintenta mas tarde.",
    }
    detalle = motivos.get(exc.clase, "[red] Fallo hablando con Google.")
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detalle
    )


def _exigir_credenciales() -> tuple[str, str]:
    settings = get_settings()
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise _error_de_configuracion()
    return settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET


# --------------------------------------------------------------------------
# OAuth
# --------------------------------------------------------------------------

def _redirect_uri(request: Request | None = None) -> str:
    """A donde Google tiene que devolver el navegador.

    Fija por entorno si puede (GOOGLE_REDIRECT_URI); detras de un proxy el
    request no siempre conserva el esquema real, y un redirect_uri que no
    coincide con el registrado en Google Cloud rompe el flujo entero.
    """
    settings = get_settings()
    if settings.GOOGLE_REDIRECT_URI:
        return settings.GOOGLE_REDIRECT_URI
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/v1/google/oauth/callback"


@router.get("/api/v1/google/oauth/inicio", response_model=InicioResponse)
def iniciar_conexion(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """La URL de consentimiento. La app la abre en el navegador del sistema."""
    client_id, _ = _exigir_credenciales()
    settings = get_settings()
    if not settings.GOOGLE_STATE_SECRET:
        raise _error_de_configuracion()

    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()

    state = jwt.encode(
        {
            "sub": user.id,
            "cv": verifier,
            "exp": datetime.now(timezone.utc) + _VIDA_DEL_STATE,
        },
        settings.GOOGLE_STATE_SECRET,
        algorithm="HS256",
    )

    auth_url = (
        f"{_URL_AUTORIZAR}?" + urlencode({
            "client_id": client_id,
            "redirect_uri": _redirect_uri(request),
            "response_type": "code",
            "scope": _SCOPE,
            "access_type": "offline",
            # 'consent' fuerza a Google a devolver refresh_token aunque el
            # usuario ya haya aceptado antes: sin esto, reconectar puede
            # llegar SIN el token de largo plazo.
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
    )
    return InicioResponse(auth_url=auth_url)


@router.get("/api/v1/google/oauth/callback")
def callback(
    request: Request,
    code: str = "",
    state: str = "",
    google: GoogleCalendarPort = Depends(get_google_client),
    tokens_repo: GoogleTokensRepositoryPort = Depends(get_google_tokens_repository),
):
    """Aqui vuelve el NAVEGADOR, sin credenciales: el state es la identidad."""
    settings = get_settings()

    try:
        claims = jwt.decode(
            state,
            settings.GOOGLE_STATE_SECRET.encode(),
            algorithms=["HS256"],
        )
        user_id, verifier = claims["sub"], claims["cv"]
    except Exception:
        # Forjado, vencido o ausente: NO se gasta el code ni se toca la base.
        return RedirectResponse(f"{_DESTINO_APP}?status=state_invalido")

    try:
        tokens = google.exchange_code(code, verifier, _redirect_uri(request))
    except (ErrorDeGoogle, ClaveFernetAusente):
        return RedirectResponse(f"{_DESTINO_APP}?status=error")

    guardar_como_servicio(
        TokensDeConexion(
            user_id=user_id,
            refresh_token_cifrado=cifrar(tokens.refresh_token),
            access_token=tokens.access_token,
            access_expira_en=tokens.access_expira_en,
        )
    )
    return RedirectResponse(f"{_DESTINO_APP}?status=ok")


@router.get("/api/v1/google/estado", response_model=EstadoConexionResponse)
def estado(
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    tokens_repo: GoogleTokensRepositoryPort = Depends(get_google_tokens_repository),
):
    """Hay conexion vigente? Es lo que consulta Settings al abrir."""
    return EstadoConexionResponse(conectado=tokens_repo.obtener(token) is not None)


@router.delete("/api/v1/google/oauth", status_code=status.HTTP_204_NO_CONTENT)
def desconectar(
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    google: GoogleCalendarPort = Depends(get_google_client),
    tokens_repo: GoogleTokensRepositoryPort = Depends(get_google_tokens_repository),
    eventos_repo: GoogleEventsRepositoryPort = Depends(get_google_events_repository),
):
    """Corta la conexion: revoca en Google Y borra todo rastro local."""
    conexion = tokens_repo.obtener(token)
    if conexion is None:
        return  # Nunca conecto: no-op exitoso, cero llamadas a Google.

    try:
        google.revoke(descifrar(conexion.refresh_token_cifrado))
    except (ErrorDeGoogle, ClaveFernetAusente):
        pass  # Revocar es cortesia hacia Google; borrar lo local es obligatorio.

    tokens_repo.borrar(token)
    eventos_repo.borrar_todo(token)
    tokens_repo.borrar_sync_token(token)


# --------------------------------------------------------------------------
# Sincronizacion y lectura
# --------------------------------------------------------------------------

_MAXIMO_DIAS = 120


@router.get("/api/v1/calendario/google", response_model=CalendarioGoogleResponse)
def calendario_google(
    desde: date,
    hasta: date,
    user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(get_access_token),
    google: GoogleCalendarPort = Depends(get_google_client),
    tokens_repo: GoogleTokensRepositoryPort = Depends(get_google_tokens_repository),
    eventos_repo: GoogleEventsRepositoryPort = Depends(get_google_events_repository),
):
    """Los eventos importados del mes. Aislado de /calendario a proposito:
    un fallo de Google no puede degradar el calendario propio."""
    if hasta < desde:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="'hasta' no puede ser anterior a 'desde'.")
    if (hasta - desde) > timedelta(days=_MAXIMO_DIAS):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"El rango no puede superar los {_MAXIMO_DIAS} días.")

    conexion = tokens_repo.obtener(token)
    if conexion is None:
        # Desconectado es un ESTADO, no un error: 200 y que la UI decida.
        # Respuesta exacta del spec, sin campos de mas.
        from fastapi.responses import JSONResponse

        return JSONResponse({"conectado": False})

    resultado = _sincronizar_con_renovacion(
        token, user.id, google, tokens_repo, eventos_repo, conexion, desde, hasta
    )

    dias: dict[str, list[date]] = {}
    for evento in resultado.eventos:
        ocupados = sorted(dias_solapados(evento, desde, hasta))
        if ocupados:
            dias[evento.id] = ocupados

    return CalendarioGoogleResponse(
        desde=desde,
        hasta=hasta,
        eventos=[
            EventoImportadoResponse(
                id=e.id, titulo=e.titulo, inicio=e.inicio, fin=e.fin,
                todo_el_dia=e.todo_el_dia,
            )
            for e in resultado.eventos
        ],
        dias=dias,
    )


def _sincronizar_con_renovacion(
    token, user_id, google, tokens_repo, eventos_repo, conexion, desde, hasta
) -> Sincronizacion:
    """Una pasada de sync con el access token siempre fresco.

    El refresco reactivo intenta UNA vez: si la segunda tambien llega muerta,
    el problema no es el token sino la conexion entera, y eso sube como 401.
    """
    acceso = _acceso_vigente(token, google, tokens_repo, conexion)

    try:
        return sincronizar(
            acceso, user_id, google, tokens_repo, eventos_repo, desde, hasta
        )
    except ErrorDeGoogle as exc:
        if exc.clase != "sesion":
            raise _traducir_google(exc) from exc

    acceso = _renovar(token, google, tokens_repo, conexion, forzado=True)
    try:
        return sincronizar(
            acceso, user_id, google, tokens_repo, eventos_repo, desde, hasta
        )
    except ErrorDeGoogle as exc:
        raise _traducir_google(exc) from exc


def _acceso_vigente(token, google, tokens_repo, conexion) -> str:
    expiracion = conexion.access_expira_en
    if (
        conexion.access_token
        and expiracion is not None
        and datetime.now(timezone.utc) < expiracion - _MARGEN_DE_REFRESCO
    ):
        return conexion.access_token
    return _renovar(token, google, tokens_repo, conexion)


def _renovar(token, google, tokens_repo, conexion, forzado: bool = False) -> str:
    try:
        plain_refresh = descifrar(conexion.refresh_token_cifrado)
        nuevos = google.refresh_access_token(plain_refresh)
    except ErrorDeGoogle as exc:
        if exc.clase == "invalid_grant":
            raise _traducir_google(exc) from exc
        if forzado and exc.clase in ("sesion", "gone"):
            # Ni renovando se arreglo: la conexion esta rota de verdad.
            raise _traducir_google(ErrorDeGoogle("invalid_grant", "")) from exc
        raise _traducir_google(exc) from exc

    tokens_repo.guardar(
        token,
        TokensDeConexion(
            user_id=conexion.user_id,
            refresh_token_cifrado=conexion.refresh_token_cifrado,
            access_token=nuevos.access_token,
            access_expira_en=nuevos.access_expira_en,
        ),
    )
    return nuevos.access_token
