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

    @abstractmethod
    def borrar_importadas_desde_google(self, access_token: str) -> None:
        """Borra SOLO las actividades materializadas desde Google.

        Identificadas por un google_event_id presente: las creadas a mano
        (NULL) quedan intactas. Es la contraparte de la sincronizacion: si
        desconectar Google deja los eventos importados sin fuente, estas
        actividades se quedarian huérfanas con un vinculo roto.
        """

    @abstractmethod
    def borrar_importadas_con_eventos(
        self, access_token: str, event_ids: list[str]
    ) -> None:
        """Borra las materializadas desde esos EVENTOS concreto de Google.

        Es la limpieza del rediseño de sync: una serie recurrente llega
        expandida instancia por instancia, y las filas por-sesión del esquema
        anterior quedan huérfanas cuando la serie pasa a ser UNA actividad
        semanal. Se borran solo las que llevan uno de estos `google_event_id`
        — las manuales (NULL) y las de otras series no se tocan.
        """
