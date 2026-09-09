"""La conexion de un usuario con Google: tokens y marca de sincronizacion.

Una sola fila por persona. Conectar de nuevo pisa la fila anterior: no hay
dos Googles conectados a la vez.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class TokensDeConexion:
    """Lo que se guarda de una conexion vigente."""

    user_id: str
    #: Cifrado con Fernet antes de llegar aqui: este repositorio jamas ve el
    #: refresh token en claro, y asi nadie que lea la tabla tampoco.
    refresh_token_cifrado: str
    access_token: str | None = None
    access_expira_en: datetime | None = None


class GoogleTokensRepositoryPort(ABC):
    """Los tokens OAuth del usuario, y el syncToken de cada calendario.

    El syncToken vive aqui y no en un puerto aparte porque es estado de la
    CONEXION, no un evento: si se desconecta al usuario, las dos cosas se van
    juntas. Dos puertos para filas que nacen y mueren en el mismo momento
    seria ceremonia, no diseno.

    La conexion es una fila por persona, pero la marca de sincronizacion es
    una por CALENDARIO: Google entrega un syncToken por calendario y usarlo
    cruzado devuelve mal los cambios.
    """

    @abstractmethod
    def guardar(self, access_token: str, tokens: TokensDeConexion) -> None:
        """Crea o reemplaza la fila del usuario (upsert)."""

    @abstractmethod
    def obtener(self, access_token: str) -> TokensDeConexion | None:
        """La fila del usuario, o None si nunca conecto Google."""

    @abstractmethod
    def borrar(self, access_token: str) -> None:
        """Desconectar: sin fila no hay conexion."""

    @abstractmethod
    def sync_token(self, access_token: str, calendar_id: str) -> str | None:
        """El syncToken de ese calendario, o None si la proxima es completa."""

    @abstractmethod
    def guardar_sync_token(
        self,
        access_token: str,
        user_id: str,
        sync_token: str,
        calendar_id: str,
    ) -> None:
        """Actualiza la marca de ese calendario tras una sincronizacion ok."""

    @abstractmethod
    def borrar_sync_token(self, access_token: str, calendar_id: str | None = None) -> None:
        """Invalida la marca de UN calendario, o de todos si no se pasa id."""
