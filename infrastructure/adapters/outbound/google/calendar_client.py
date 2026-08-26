"""Google Calendar por REST, con httpx.

Es el unico archivo del backend que sabe que Google existe como URLs. Todo
lo que sale de aca son datos de dominio; todo lo que entra son decisiones ya
tomadas. Cambiar de API (o de proveedor) toca este archivo y ninguno mas.

Mapeo de errores, la taxonomia que el router traduce a HTTP:

- 'invalid_grant': Google rechazo el refresh token (revocado o expirado).
  No se arregla reintentando: el usuario tiene que conectar de nuevo.
- 'sesion': la llamada llego con un access token que ya no vale. Se puede
  refrescar una vez y reintentar.
- 'gone': el syncToken ya no sirve (HTTP 410). La proxima pasada es completa.
- 'config': faltan credenciales o son invalidas. Es despliegue, no usuario.
- 'quota': rate limit o cuota de Google. Reintentable, pero no ahora mismo.
- 'red': timeout o Google caido. Tambien reintento, con calma.

Un detalle que cuesta horas descubrir: la API NO acepta `timeMin`/`timeMax`
junto con `syncToken`. El incremental trae TODOS los cambios y quien orquesta
filtra; la completa es la acotada a la ventana.
"""

import httpx
from datetime import datetime, timedelta, timezone

from domain.ports.outbound.google_calendar_port import (
    ErrorDeGoogle,
    EventoRemoto,
    GoogleCalendarPort,
    TokensDeGoogle,
    VentanaDeEventos,
)
from infrastructure.config.settings import get_settings

_URL_TOKEN = "https://oauth2.googleapis.com/token"
_URL_REVOCAR = "https://oauth2.googleapis.com/revoke"
_URL_EVENTOS = "https://www.googleapis.com/calendar/v3/calendars/primary/events"

#: Errores de token endpoint que significan "conectate de nuevo" y no
#: "reintenta": el refresh token murio o las credenciales del servidor.
_PERMANENTES = {"invalid_grant", "invalid_client", "unauthorized_client"}

_RAZONES_DE_CUOTA = (
    "rateLimitExceeded",
    "userRateLimitExceeded",
    "quotaExceeded",
    "dailyLimitExceeded",
)


def _cliente() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(15.0))


class HttpxGoogleCalendar(GoogleCalendarPort):
    """El adaptador REST. I/O y nada de logica: decidir vive en el dominio."""

    def exchange_code(
        self, code: str, code_verifier: str, redirect_uri: str
    ) -> TokensDeGoogle:
        client_id, client_secret = _credenciales()
        datos = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            # PKCE: el verifier lo genero quien inicio el flujo y viajo en
            # el `state` firmado. Sin el, un codigo robado no vale nada.
            "code_verifier": code_verifier,
        }
        cuerpo = _post_token(datos)
        return TokensDeGoogle(
            refresh_token=cuerpo["refresh_token"],
            access_token=cuerpo["access_token"],
            access_expira_en=_expira_en(cuerpo),
        )

    def refresh_access_token(self, refresh_token: str) -> TokensDeGoogle:
        client_id, client_secret = _credenciales()
        datos = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        cuerpo = _post_token(datos)
        # En un refresh Google NO devuelve refresh_token nuevo: el que hay
        # sigue siendo el de siempre hasta que el usuario lo revoque.
        return TokensDeGoogle(
            refresh_token=refresh_token,
            access_token=cuerpo["access_token"],
            access_expira_en=_expira_en(cuerpo),
        )

    def list_events(
        self,
        access_token: str,
        desde,
        hasta,
        sync_token: str | None = None,
    ) -> VentanaDeEventos:
        base: dict = {
            "singleEvents": "true",
            # Ordenado por inicio para que las paginas sean estables.
            "orderBy": "startTime",
            "maxResults": 2500,
        }
        if sync_token:
            base["syncToken"] = sync_token
        else:
            base["timeMin"] = desde.isoformat()
            base["timeMax"] = hasta.isoformat()

        eventos: list[EventoRemoto] = []
        sync_nuevo: str | None = None
        with _cliente() as cliente:
            while True:
                respuesta = cliente.get(
                    _URL_EVENTOS,
                    params=base,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                _exigir_ok(respuesta)

                cuerpo = respuesta.json()
                eventos.extend(
                    _evento_de(item) for item in cuerpo.get("items", [])
                )
                if cuerpo.get("nextPageToken"):
                    base["pageToken"] = cuerpo["nextPageToken"]
                    continue
                # Solo la ultima pagina entrega la marca: pedir antes de
                # terminarla devolveria un token que pierde cambios.
                sync_nuevo = cuerpo.get("nextSyncToken")
                break

        return VentanaDeEventos(eventos=eventos, sync_token=sync_nuevo)

    def revoke(self, token: str) -> None:
        with _cliente() as cliente:
            try:
                respuesta = cliente.post(_URL_REVOCAR, data={"token": token})
            except httpx.RequestError as exc:
                raise ErrorDeGoogle("red", f"revocacion inalcanzable: {exc}") from exc
        if respuesta.status_code != 200:
            raise ErrorDeGoogle(
                "red",
                f"revocar devolvio {respuesta.status_code}",
            )


def _credenciales() -> tuple[str, str]:
    settings = get_settings()
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise ErrorDeGoogle(
            "config",
            "Faltan GOOGLE_CLIENT_ID y/o GOOGLE_CLIENT_SECRET en el servidor.",
        )
    return settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET


def _expira_en(cuerpo: dict):
    segundos = int(cuerpo.get("expires_in", 3600))
    return datetime.now(timezone.utc) + timedelta(seconds=segundos)


def _post_token(datos: dict) -> dict:
    """POST al endpoint de tokens con el mapeo de error comun."""
    with _cliente() as cliente:
        try:
            respuesta = cliente.post(_URL_TOKEN, data=datos)
        except httpx.RequestError as exc:
            raise ErrorDeGoogle("red", f"endpoint de tokens inalcanzable: {exc}") from exc

    if respuesta.status_code == 200:
        return respuesta.json()

    error = respuesta.json().get("error", "") if respuesta.headers.get(
        "content-type", ""
    ).startswith("application/json") else ""
    if error in _PERMANENTES:
        clase = "invalid_grant" if error == "invalid_grant" else "config"
        raise ErrorDeGoogle(clase, f"Google rechazo el pedido ({error}).")
    raise ErrorDeGoogle("red", f"endpoint de tokens respondio {respuesta.status_code}")


def _exigir_ok(respuesta: httpx.Response) -> None:
    if respuesta.status_code == 200:
        return
    if respuesta.status_code == 401:
        raise ErrorDeGoogle(
            "sesion", "el access token ya no vale; toca refrescar."
        )
    if respuesta.status_code == 410:
        raise ErrorDeGoogle(
            "gone", "el syncToken expiro: la proxima pasada tiene que ser completa."
        )
    if respuesta.status_code == 429 or (
        respuesta.status_code == 403
        and any(
            razon in respuesta.text for razon in _RAZONES_DE_CUOTA
        )
    ):
        raise ErrorDeGoogle("quota", "cuota o rate limit de Google alcanzado.")
    raise ErrorDeGoogle(
        "red", f"events.list respondio {respuesta.status_code}"
    )


def _evento_de(item: dict) -> EventoRemoto:
    """Del JSON de Google al dato de dominio.

    Un evento de todo el dia no trae `dateTime`, trae `date`: solo el dia, y
    ese dia ES su fecha — sin huso horario ni medianoches que interpretar.
    """
    inicio = item.get("start", {})
    fin = item.get("end", {})
    todo_el_dia = "date" in inicio

    return EventoRemoto(
        id=item["id"],
        titulo=item.get("summary") or "(sin titulo)",
        inicio=_momento_de(inicio),
        fin=_momento_de(fin),
        todo_el_dia=todo_el_dia,
    )


def _momento_de(marca: dict) -> datetime:
    valor = marca.get("dateTime") or marca.get("date")
    if not valor:
        raise ValueError(f"Evento de Google sin ni date ni dateTime: {marca}")
    # Python 3.11+ entiende el sufijo 'Z' directamente.
    return datetime.fromisoformat(valor)
