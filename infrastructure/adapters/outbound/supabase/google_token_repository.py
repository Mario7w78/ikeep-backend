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
from infrastructure.adapters.outbound.supabase.client import (
    client_con_rol_de_servicio,
    client_for_user,
)

TABLA = "google_tokens"
TABLA_SYNC = "sync_tokens"

#: PostgREST exige un filtro para borrar, y RLS ya acoto el alcance a las
#: filas del dueno del token; este uuid (que ningun usuario tiene) es el
#: "todas mis filas" que si castea a la columna uuid.
_UUID_NULO = "00000000-0000-0000-0000-000000000000"

#: Version de la clave con la que se guarda el syncToken. Subirla en un
#: deploy INVALIDA todas las marcas guardadas: la proxima pasada por cada
#: calendario es completa, lo que permite re-materializar actividades con un
#: esquema nuevo (por ejemplo, agrupar series recurrentes en una sola fila).
_SYNC_VERSION = 2


def guardar_como_servicio(tokens: TokensDeConexion) -> None:
    """El upsert del callback OAuth, con rol de servicio.

    Es la UNICA escritura privilegiada de la integracion y existe por una
    sola razon: el callback llega desde el navegador, sin JWT de nadie, y
    RLS (con toda la razon) rechazaria escribir. El user_id viaja firmado
    dentro del state — no se toma de un cuerpo suelto.
    """
    client_con_rol_de_servicio().table(TABLA).upsert(
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
    ).execute()


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
        # falta. El `neq` cumple el requisito de PostgREST de borrar con
        # filtro sin reducir el alcance que RLS ya garantiza.
        client_for_user(access_token).table(TABLA).delete().neq(
            "user_id", _UUID_NULO
        ).execute()

    def sync_token(self, access_token: str, calendar_id: str) -> str | None:
        respuesta = (
            client_for_user(access_token)
            .table(TABLA_SYNC)
            .select("sync_token")
            .eq("calendar_id", _clave_calendario(calendar_id))
            .limit(1)
            .execute()
        )
        fila = (respuesta.data or [{}])[0]
        return fila.get("sync_token")

    def guardar_sync_token(
        self,
        access_token: str,
        user_id: str,
        sync_token: str,
        calendar_id: str,
    ) -> None:
        (
            client_for_user(access_token)
            .table(TABLA_SYNC)
            .upsert(
                {
                    "user_id": user_id,
                    "calendar_id": _clave_calendario(calendar_id),
                    "sync_token": sync_token,
                },
                on_conflict="user_id,calendar_id",
            )
            .execute()
        )

    def borrar_sync_token(self, access_token: str, calendar_id: str | None = None) -> None:
        query = client_for_user(access_token).table(TABLA_SYNC)
        if calendar_id is not None:
            query = query.eq("calendar_id", _clave_calendario(calendar_id))
        # Sin filtro por user_id y a proposito: RLS acota las filas al dueno
        # del token, y filtrar ademas seria fingir una certeza que no hace
        # falta. El `neq` cumple el requisito de PostgREST de borrar con
        # filtro sin reducir el alcance que RLS ya garantiza.
        query.delete().neq("user_id", _UUID_NULO).execute()


def _a_momento(valor):
    if not valor:
        return None
    return valor if isinstance(valor, datetime) else datetime.fromisoformat(valor)


def _clave_calendario(calendar_id: str) -> str:
    """La clave versionada del syncToken de un calendario.

    El syncToken vive por calendario (Google lo entrega y lo valida por
    calendario), y la version en la clave permite invalidar las marcas
    guardadas de golpe: subir `_SYNC_VERSION` hace que las filas viejas no se
    encuentren y la proxima pasada sea completa.
    """
    return f"{calendar_id}@v{_SYNC_VERSION}"
