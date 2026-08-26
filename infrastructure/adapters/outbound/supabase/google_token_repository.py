"""Tokens de la conexion con Google (y el syncToken) sobre PostgREST.

El refresh token llega YA cifrado y se guarda tal cual: este repositorio no
sabe descifrar ni quiere aprender. El que lee lo descifra arriba, y aca solo
pasa texto opaco.
"""

from datetime import datetime

from domain.ports.outbound.google_token_repository_port import (
    GoogleTokensRepositoryPort,
    TokensDeConexion,
)
from infrastructure.adapters.outbound.supabase.client import client_for_user

TABLA = "google_tokens"
TABLA_SYNC = "sync_tokens"


class SupabaseGoogleTokensRepository(GoogleTokensRepositoryPort):
    def guardar(self, access_token: str, tokens: TokensDeConexion) -> None:
        # upsert y no insert: reconectar pisa la conexion anterior en vez de
        # acumular filas que ya nadie usa.
        (
            client_for_user(access_token)
            .table(TABLA)
            .upsert(
                {
                    "user_id": tokens.user_id,
                    "refresh_token_cifrado": tokens.refresh_token_cifrado,
                    "access_token": tokens.access_token,
                    "access_expira_en": (
                        tokens.access_expira_en.isoformat()
                        if tokens.access_expira_en
                        else None
                    ),
                    "actualizado_en": datetime.now().astimezone().isoformat(),
                },
                on_conflict="user_id",
            )
            .execute()
        )

    def obtener(self, access_token: str) -> TokensDeConexion | None:
        respuesta = (
            client_for_user(access_token)
            .table(TABLA)
            .select("*")
            .limit(1)
            .execute()
        )
        fila = (respuesta.data or [None])[0]
        if not fila:
            return None
        return TokensDeConexion(
            user_id=fila["user_id"],
            refresh_token_cifrado=fila["refresh_token_cifrado"],
            access_token=fila.get("access_token"),
            access_expira_en=_a_momento(fila.get("access_expira_en")),
        )

    def borrar(self, access_token: str) -> None:
        # Sin filtro por user_id y a proposito: RLS acota la fila al dueno
        # del token, y filtrar ademas seria fingir una certeza que no hace
        # falta.
        client_for_user(access_token).table(TABLA).delete().execute()

    def sync_token(self, access_token: str) -> str | None:
        respuesta = (
            client_for_user(access_token)
            .table(TABLA_SYNC)
            .select("sync_token")
            .limit(1)
            .execute()
        )
        fila = (respuesta.data or [{}])[0]
        return fila.get("sync_token")

    def guardar_sync_token(
        self, access_token: str, user_id: str, sync_token: str
    ) -> None:
        (
            client_for_user(access_token)
            .table(TABLA_SYNC)
            .upsert({"user_id": user_id, "sync_token": sync_token})
            .execute()
        )

    def borrar_sync_token(self, access_token: str) -> None:
        client_for_user(access_token).table(TABLA_SYNC).delete().execute()


def _a_momento(valor):
    if not valor:
        return None
    return valor if isinstance(valor, datetime) else datetime.fromisoformat(valor)
