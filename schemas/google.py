"""Contrato HTTP de la integracion con Google Calendar.

Igual que el resto de schemas: los nombres de campo son los que consume la
app y el mapeo desde el dominio vive en el router.
"""

from datetime import date, datetime

from pydantic import BaseModel


class InicioResponse(BaseModel):
    """Lo que la app necesita para abrir el navegador de consentimiento."""

    auth_url: str
    #: El estado firmado viaja dentro de auth_url; no se expone por separado
    #: porque no le sirve a nadie fuera de la URL.


class EstadoConexionResponse(BaseModel):
    """Si hay conexion vigente. Es lo que consulta Settings al abrir."""

    conectado: bool


class EventoImportadoResponse(BaseModel):
    """Un evento de Google, tal como lo dibuja el mes."""

    id: str
    titulo: str
    inicio: datetime
    fin: datetime
    todo_el_dia: bool = False


class CalendarioGoogleResponse(BaseModel):
    """Los eventos importados que tocan el rango pedido.

    Sin conexion responde SOLO `{conectado: false}` con 200: para la UI eso
    es un estado normal, no un error. Con conexion, `dias` es la expansion:
    un evento de varios dias aparece una vez en `eventos` pero lista todos
    los dias que ocupa, recortados al rango. El cliente dibuja por dia y asi
    no tiene que cruzar nada.
    """

    conectado: bool = True
    desde: date | None = None
    hasta: date | None = None
    eventos: list[EventoImportadoResponse] = []
    #: id del evento -> dias (ISO) en que aparece dentro del rango.
    dias: dict[str, list[date]] = {}
