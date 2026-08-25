"""El calendario de Google, visto desde el dominio.

El dominio no sabe que Google existe ni que REST significa algo: pide
intercambiar un codigo por tokens, listar eventos y revocar. Que arriba haya
httpx contra oauth2.googleapis.com es decision de un adaptador, y cambiarla
no toca a nadie que piense.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


class ErrorDeGoogle(Exception):
    """Algo fallo hablando con Google.

    La taxonomia completa la decide quien traduce a HTTP; esta excepcion solo
    trae lo necesario para eso: que clase de error fue y que dijo Google.
    """

    def __init__(self, clase: str, detalle: str):
        super().__init__(detalle)
        #: 'invalid_grant' | 'config' | 'quota' | 'red'
        self.clase = clase
        self.detalle = detalle


@dataclass(frozen=True)
class TokensDeGoogle:
    """Lo que devuelve el intercambio del codigo de autorizacion."""

    refresh_token: str
    access_token: str
    #: Cuando vence el access token, en UTC. Google lo manda como segundos
    #: desde epoch; aqui ya es una fecha.
    access_expira_en: datetime


@dataclass(frozen=True)
class EventoRemoto:
    """Un evento tal como llega de Google Calendar.

    Con singleEvents=true cada repeticion llega como su propio evento, asi
    que nadie expande recurrencias mas abajo.
    """

    id: str
    titulo: str
    inicio: datetime
    fin: datetime
    todo_el_dia: bool = False


class GoogleCalendarPort(ABC):
    """Las cuatro llamadas que la integracion necesita. Ni una mas."""

    @abstractmethod
    def exchange_code(
        self, code: str, code_verifier: str, redirect_uri: str
    ) -> TokensDeGoogle:
        """Cambia el codigo del navegador por los tokens (PKCE)."""

    @abstractmethod
    def refresh_access_token(self, refresh_token: str) -> TokensDeGoogle:
        """Un access token nuevo a partir del refresh token guardado."""

    @abstractmethod
    def list_events(
        self,
        access_token: str,
        desde: datetime,
        hasta: datetime,
        page_token: str | None = None,
        sync_token: str | None = None,
    ) -> tuple[list[EventoRemoto], str | None]:
        """Los eventos que se solapan con la ventana, y el token de pagina.

        Devuelve (eventos, next_page_token). Si `sync_token` viene, Google
        manda solo cambios desde esa marca; si responde 410 levanta
        ErrorDeGoogle para que quien orquesta decida reintentar completo.
        """

    @abstractmethod
    def revoke(self, token: str) -> None:
        """Le dice a Google que ese token deja de valer."""
