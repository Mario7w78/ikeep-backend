from abc import ABC, abstractmethod
from datetime import date


class CompletadosRepositoryPort(ABC):
    """Que actividades marco el usuario como hechas, y que dia.

    Una fila por (actividad, dia). Una actividad es una definicion recurrente,
    asi que "completada" siempre es una afirmacion sobre una ocurrencia.
    """

    @abstractmethod
    def marcar(self, access_token: str, user_id: str, activity_id: str, fecha: date) -> None:
        """Idempotente: marcar dos veces el mismo dia es la misma afirmacion."""

    @abstractmethod
    def desmarcar(self, access_token: str, activity_id: str, fecha: date) -> None:
        """Deshace un completado. Tocar por error no deberia ser definitivo."""

    @abstractmethod
    def del_dia(self, access_token: str, fecha: date) -> list[str]:
        """Los ids completados ese dia."""

    @abstractmethod
    def dias_con_actividad(self, access_token: str, desde: date) -> set[date]:
        """Los dias con al menos un completado. Es lo que la racha necesita."""
