"""Access to Supabase, and the startup check that the schema is actually there.

The database is reached through PostgREST rather than a direct Postgres
connection. Two reasons: the container sleeps on the free tier and a
connection pool does not survive that cycle cleanly, and going through the
REST API keeps row-level security in force — every query runs with the
caller's own JWT instead of a privileged service role.

The trade-off is that there are no real transactions. Anything that must be
atomic belongs in a Postgres function called through `rpc()`.
"""

import logging
from functools import lru_cache

from supabase import Client, create_client

from infrastructure.config.settings import get_settings

logger = logging.getLogger(__name__)

# Every table the app reads or writes. Kept in sync with
# supabase/migrations/ — the startup check compares against this list.
REQUIRED_TABLES = (
    "activities",
    "energy_records",
    "profiles",
    "schedules",
    "user_settings",
)


def _credentials() -> tuple[str, str]:
    settings = get_settings()
    if not settings.SUPABASE_URL or not settings.SUPABASE_ANON_KEY:
        raise RuntimeError(
            "Faltan SUPABASE_URL y/o SUPABASE_ANON_KEY. Copialas de .env.example."
        )
    return settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY


@lru_cache(maxsize=1)
def anon_client() -> Client:
    """Unauthenticated client, for work that belongs to no user.

    RLS gives this client nothing: it is here for the schema check and for
    anything genuinely public. Never use it to serve user data.
    """
    url, key = _credentials()
    return create_client(url, key)


def client_for_user(access_token: str) -> Client:
    """Client that acts as the caller, so RLS scopes every query to them.

    Deliberately not cached. Tokens expire and belong to different people;
    a cached client would eventually answer one user with another's session.
    Construction makes no network call, so the cost is small.
    """
    url, key = _credentials()
    client = create_client(url, key)
    client.postgrest.auth(access_token)
    return client


def missing_tables(client: Client) -> list[str]:
    """Names from REQUIRED_TABLES that the database does not answer for.

    A table that exists but returns no rows is fine — that is just RLS
    refusing an anonymous caller. Only a failed request means it is absent.
    """
    missing = []
    for table in REQUIRED_TABLES:
        try:
            client.table(table).select("*").limit(0).execute()
        except Exception as exc:
            logger.debug("La tabla '%s' no respondio: %s", table, exc)
            missing.append(table)
    return missing


def verify_schema(client: Client) -> None:
    """Fail loudly at startup rather than cryptically at request time.

    The frontend spent a while writing to tables that did not exist: every
    save failed silently because the caller swallowed the error. A boot-time
    check turns that class of problem into one obvious message.
    """
    missing = missing_tables(client)
    if missing:
        raise RuntimeError(
            f"Faltan tablas en Supabase: {', '.join(sorted(missing))}. "
            "Aplica los archivos de supabase/migrations/."
        )
    logger.info("Esquema verificado: %d tablas presentes.", len(REQUIRED_TABLES))
