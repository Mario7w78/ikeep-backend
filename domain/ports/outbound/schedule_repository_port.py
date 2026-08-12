from abc import ABC, abstractmethod

from domain.entities.energy_record import RegistroEnergia
from domain.entities.stored_schedule import HorarioGuardado


class HorarioRepositoryPort(ABC):
    """El horario vigente del usuario. Uno solo por persona."""

    @abstractmethod
    def get(self, access_token: str) -> HorarioGuardado | None:
        """El horario guardado, o None si todavia no genero ninguno."""

    @abstractmethod
    def save(self, access_token: str, horario: HorarioGuardado) -> HorarioGuardado:
        """Reemplaza el horario vigente."""

    @abstractmethod
    def delete(self, access_token: str) -> None:
        """Deja al usuario sin horario."""


class EnergiaRepositoryPort(ABC):
    """Historial de reportes de energia."""

    @abstractmethod
    def add(self, access_token: str, registro: RegistroEnergia) -> RegistroEnergia:
        """Agrega un reporte y poda los que superaron la retencion."""

    @abstractmethod
    def history(self, access_token: str, dias: int) -> list[RegistroEnergia]:
        """Los ultimos `dias` de historial, del mas reciente al mas viejo."""

    @abstractmethod
    def reported_today(self, access_token: str, desfase_utc_minutos: int = 0) -> bool:
        """Si el usuario ya reporto hoy, en el dia del usuario.

        El desfase lo manda el cliente porque el servidor no puede saberlo.
        Sin el, "hoy" es el dia UTC: para alguien en UTC-5 el dia cambiaria a
        las 19:00 locales.
        """
