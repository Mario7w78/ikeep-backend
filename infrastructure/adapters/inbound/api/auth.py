"""Verification of the Supabase access tokens the mobile app sends.

The project signs tokens asymmetrically (ES256) and publishes the public half
as a JWKS document, so there is no shared secret to configure: the signature
is checked against a key fetched from the project's own endpoint. That also
means key rotation needs no redeploy — the token carries the `kid` and the
client looks it up.

Verification happens locally. A forged, expired or foreign token is rejected
before it costs a round trip to Supabase.
"""

import logging
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from infrastructure.config.settings import get_settings

logger = logging.getLogger(__name__)

# Supabase issues every end-user token with this audience. Anything else is
# a service token or comes from somewhere we do not serve.
_AUDIENCE = "authenticated"
_ALGORITHMS = ["ES256"]

# auto_error=False so a missing header reaches our own handler and produces
# the same 401 shape as an invalid one, instead of FastAPI's 403.
_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    """The caller, as proven by their token. `id` matches auth.users.id."""

    id: str
    email: str | None = None


def _unauthorized(reason: str) -> HTTPException:
    # The reason is logged, never returned: telling a caller *why* a token
    # failed helps them forge a better one.
    logger.warning("Token rechazado: %s", reason)
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales invalidas o ausentes.",
        headers={"WWW-Authenticate": "Bearer"},
    )


@lru_cache(maxsize=1)
def _jwk_client() -> PyJWKClient:
    """Cached JWKS client. It keeps its own key cache, so this is fetched once."""
    settings = get_settings()
    if not settings.SUPABASE_URL:
        raise RuntimeError(
            "SUPABASE_URL no esta configurada: no hay forma de validar tokens."
        )
    return PyJWKClient(
        f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json",
        cache_keys=True,
    )


def verify_token(token: str) -> AuthenticatedUser:
    """Verify signature, expiry, audience and issuer, then return the caller."""
    settings = get_settings()

    try:
        signing_key = _jwk_client().get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=_ALGORITHMS,
            audience=_AUDIENCE,
            issuer=f"{settings.SUPABASE_URL}/auth/v1",
        )
    except jwt.PyJWTError as exc:
        raise _unauthorized(str(exc)) from exc
    except Exception as exc:  # JWKS fetch failures, malformed documents
        raise _unauthorized(f"no se pudo resolver la clave de firma: {exc}") from exc

    user_id = claims.get("sub")
    if not user_id:
        raise _unauthorized("el token no trae claim 'sub'")

    return AuthenticatedUser(id=user_id, email=claims.get("email"))


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthenticatedUser:
    """FastAPI dependency: put this on every route that touches user data."""
    if credentials is None or not credentials.credentials:
        raise _unauthorized("falta la cabecera Authorization: Bearer")

    return verify_token(credentials.credentials)
