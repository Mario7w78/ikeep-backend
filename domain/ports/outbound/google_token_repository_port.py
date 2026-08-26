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
    """Los tokens OAuth del usuario, y el syncToken de su ultima pasada.

    El syncToken vive aqui y no en un puerto aparte porque es estado de la
    CONEXION, no un evento: si se desconecta al usuario, las dos cosas se van
    juntas. Dos puertos para filas que nacen y mueren en el mismo momento
    seria ceremonia, no diseno.
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
    def sync_token(self, access_token: str) -> str | None:
        """El syncToken vigente, o None si la proxima tiene que ser completa."""

    @abstractmethod
    def guardar_sync_token(
        self, access_token: str, user_id: str, sync_token: str
    ) -> None:
        """Actualiza la marca despues de una sincronizacion exitosa."""

    @abstractmethod
    def borrar_sync_token(self, access_token: str) -> None:
        """Invalida la marca: Google respondio 410 y toca pasada completa."""
