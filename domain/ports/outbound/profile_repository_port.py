from abc import ABC, abstractmethod

from domain.entities.profile import Perfil
from domain.entities.user_settings import AjustesUsuario


class PerfilRepositoryPort(ABC):
    """Perfil del usuario. Una fila por persona, con el id de auth.users."""

    @abstractmethod
    def get(self, access_token: str) -> Perfil | None:
        """El perfil del dueño del token, o None si la fila no existe."""

    @abstractmethod
    def save(self, access_token: str, perfil: Perfil) -> Perfil:
        """Crea o actualiza."""

    @abstractmethod
    def clear(self, access_token: str) -> None:
        """Vacia los campos sin borrar la fila.

        Borrarla no serviria: profiles.id referencia auth.users con cascade y
        solo el trigger de alta la recrea, asi que un usuario existente se
        quedaria sin fila para siempre.
        """


class AjustesRepositoryPort(ABC):
    """Preferencias de planificacion. Una fila por usuario."""

    @abstractmethod
    def get(self, access_token: str, user_id: str) -> AjustesUsuario:
        """Los ajustes, o los defaults si el usuario nunca guardo ninguno."""

    @abstractmethod
    def patch(
        self, access_token: str, user_id: str, cambios: dict
    ) -> AjustesUsuario:
        """Aplica solo los campos presentes y devuelve el resultado.

        Parcial y no reemplazo completo porque el cliente los toca de a uno
        —cambiar la hora de inicio no deberia poder pisar el resto.
        """
