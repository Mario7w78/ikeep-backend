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
class CalendarioRemoto:
    """Un calendario de Google al que el usuario dio acceso.

    La vista de la app mezcla TODOS los calendarios del usuario, no solo el
    principal: el horario de mucha gente vive en calendarios secundarios
    (trabajo, universidad) y leer solo `primary` hacia que los eventos de la
    semana actual parecieran "aparecer desde el mes siguiente".

    `id` es el identificador con el que Google distingue los calendarios; el
    principal se puede pedir por el alias `primary` pero no siempre se llama
    asi en calendarList, por eso el flag.
    """

    id: str
    nombre: str
    es_principal: bool = False


@dataclass(frozen=True)
class EventoRemoto:
    """Un evento tal como llega de Google Calendar.

    Con singleEvents=true cada repeticion llega como su propio evento, asi
    que nadie expande recurrencias mas abajo.

    `calendar_id` identifica de que calendario salio: el id del evento solo
    es unico DENTRO de un calendario, y la copia local lo necesita junto.
    """

    id: str
    titulo: str
    inicio: datetime
    fin: datetime
    #: Por defecto "primary" para no obligar a quienes construyen eventos de
    #: prueba a repetir el id; el adaptador SIEMPRE lo llena con el real.
    calendar_id: str = "primary"
    todo_el_dia: bool = False
    #: El id del evento MAESTRO cuando esto es una instancia de una serie
    #: recurrente (singleEvents=true expandio la repeticion). Vacío para los
    #: eventos sueltos. Es la señal para agrupar: una serie recurrente se
    #: guarda como UNA actividad semanal, no como N filas sueltas.
    recurring_event_id: str | None = None


@dataclass(frozen=True)
class VentanaDeEventos:
    """Lo que devuelve una pasada de lectura completa del calendario.

    El adaptador recorre las paginas por dentro: al que llama no le interesa
    la mecanica, le interesan los eventos y la marca para la proxima pasada
    incremental.
    """

    eventos: list[EventoRemoto]
    #: La marca que pide Google para traer solo cambios. Viene solo si la
    #: pasada fue completa (con syncToken no se entrega marca nueva).
    sync_token: str | None = None


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
    def list_calendarios(self, access_token: str) -> list[CalendarioRemoto]:
        """Los calendarios que el usuario dio permiso de leer."""

    @abstractmethod
    def list_events(
        self,
        access_token: str,
        desde: datetime,
        hasta: datetime,
        calendar_id: str,
        sync_token: str | None = None,
    ) -> VentanaDeEventos:
        """Los eventos de ese calendario que se solapan con la ventana.

        Sin `sync_token` hace una pasada completa acotada a [desde, hasta].
        Con el, Google manda solo cambios desde esa marca —y entonces la
        ventana no viaja: Google rechaza las dos cosas juntas—. Si la marca
        ya no vale, levanta ErrorDeGoogle con clase 'gone' para que quien
        orquesta decida reintentar completo.

        `calendar_id` es por calendario: la ventana a la que se le piden
        eventos, y la marca, viven en UN calendario cada una. Google no
        mezcla.
        """

    @abstractmethod
    def revoke(self, token: str) -> None:
        """Le dice a Google que ese token deja de valer."""
