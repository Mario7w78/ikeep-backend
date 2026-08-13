from abc import ABC, abstractmethod
from datetime import date

from domain.services.calendar.expansion import Excepcion


class ExcepcionesRepositoryPort(ABC):
    """Lo que rompe la regla de repeticion en una fecha puntual."""

    @abstractmethod
    def del_rango(self, access_token: str, desde: date, hasta: date) -> list[Excepcion]:
        """Las excepciones que afectan a ese rango.

        Se filtra por la fecha ORIGINAL y tambien por la nueva: una ocurrencia
        movida hacia adentro del rango tiene que aparecer aunque su fecha
        original cayera afuera.
        """

    @abstractmethod
    def guardar(self, access_token: str, user_id: str, excepcion: Excepcion) -> None:
        """Idempotente por (actividad, fecha): repetirla la reemplaza."""

    @abstractmethod
    def borrar(self, access_token: str, activity_id: str, fecha: date) -> None:
        """Deshace la excepcion. La ocurrencia vuelve a su lugar."""
