"""Los eventos importados de Google Calendar.

Es una copia local, no la fuente: si la copia se atrasa, la proxima
sincronizacion la alcanza. Por eso no hay entidad de dominio con
comportamiento aca — solo datos que entran y salen.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class EventoImportado:
    """Un evento de Google ya guardado localmente.

    Con singleEvents=true cada repeticion de un evento periodico llega como
    su propio evento, con su id de instancia; nunca se expande recurrencia
    por nuestra cuenta.

    `calendar_id` es parte de la identidad: el id del evento solo es unico
    dentro de un calendario, y dos calendarios pueden compartir el mismo
    evento con el mismo id.
    """

    id: str
    titulo: str
    inicio: datetime
    fin: datetime
    calendar_id: str = "primary"
    todo_el_dia: bool = False


class GoogleEventsRepositoryPort(ABC):
    @abstractmethod
    def upsert(
        self, access_token: str, user_id: str, eventos: list[EventoImportado]
    ) -> None:
        """Guarda los eventos; los repetidos pisan su fila."""

    @abstractmethod
    def del_rango(
        self, access_token: str, desde: datetime, hasta: datetime
    ) -> list[EventoImportado]:
        """Los eventos que se solapan con [desde, hasta]."""

    @abstractmethod
    def borrar_todo(self, access_token: str) -> None:
        """Desconectar deja al usuario sin eventos importados."""
