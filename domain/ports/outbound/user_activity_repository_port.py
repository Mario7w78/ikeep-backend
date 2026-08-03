from abc import ABC, abstractmethod

from domain.entities.user_activity import ActividadUsuario


class ActividadUsuarioRepositoryPort(ABC):
    """Acceso a las actividades guardadas de un usuario.

    Toda operacion recibe el token de quien la pide, no un user_id suelto.
    La diferencia importa: un id se puede falsificar desde el cliente, un
    token esta firmado. El adaptador lo adjunta a la peticion y es Postgres,
    via RLS, el que decide que filas son visibles — el backend no vuelve a
    filtrar por su cuenta, porque duplicar esa regla es duplicar la forma de
    equivocarse.
    """

    @abstractmethod
    def list_all(self, access_token: str) -> list[ActividadUsuario]:
        """Todas las actividades del dueño del token."""

    @abstractmethod
    def get(self, access_token: str, activity_id: str) -> ActividadUsuario | None:
        """Una actividad, o None si no existe o no es suya."""

    @abstractmethod
    def save(self, access_token: str, actividad: ActividadUsuario) -> ActividadUsuario:
        """Crea o reemplaza, y devuelve lo que quedó guardado."""

    @abstractmethod
    def delete(self, access_token: str, activity_id: str) -> None:
        """Borra. No falla si no existe: el resultado buscado ya se cumple."""
