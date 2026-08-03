"""Tests for Supabase JWT verification.

The project signs tokens asymmetrically (ES256, curve P-256) and publishes
the public half at /auth/v1/.well-known/jwks.json, so verification needs the
JWKS endpoint rather than a shared secret. These tests generate their own
keypair and stub the JWKS client, so nothing here touches the network.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from infrastructure.adapters.inbound.api.auth import (
    AuthenticatedUser,
    get_current_user,
)
from infrastructure.config import settings as settings_module
from infrastructure.config.settings import Settings

SUPABASE_URL = "https://proyecto-de-prueba.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"


def _keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem, private_key.public_key()


def _token(signing_pem, **overrides) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": "11111111-2222-3333-4444-555555555555",
        "email": "alguien@ejemplo.com",
        "aud": "authenticated",
        "iss": ISSUER,
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    claims.update(overrides)
    return jwt.encode(claims, signing_pem, algorithm="ES256")


@pytest.fixture
def keys():
    return _keypair()


@pytest.fixture(autouse=True)
def settings_with_supabase():
    """Point the verifier at the fake project, and restore afterwards."""
    original = settings_module._settings
    settings_module._settings = Settings(SUPABASE_URL=SUPABASE_URL)
    yield
    settings_module._settings = original


@pytest.fixture
def client(keys):
    """App with one protected route, wired to the test keypair."""
    _, public_key = keys

    app = FastAPI()

    @app.get("/protegido")
    def protegido(user: AuthenticatedUser = Depends(get_current_user)):
        return {"user_id": user.id, "email": user.email}

    signing_key = Mock()
    signing_key.key = public_key
    jwk_client = Mock()
    jwk_client.get_signing_key_from_jwt.return_value = signing_key

    with patch(
        "infrastructure.adapters.inbound.api.auth._jwk_client",
        return_value=jwk_client,
    ):
        with TestClient(app) as c:
            yield c


class TestTokenAceptado:
    def test_devuelve_el_usuario_del_claim_sub(self, client, keys):
        pem, _ = keys
        response = client.get(
            "/protegido",
            headers={"Authorization": f"Bearer {_token(pem)}"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "user_id": "11111111-2222-3333-4444-555555555555",
            "email": "alguien@ejemplo.com",
        }

    def test_el_email_es_opcional(self, client, keys):
        pem, _ = keys
        token = _token(pem, email=None)

        response = client.get(
            "/protegido", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        assert response.json()["email"] is None


class TestTokenRechazado:
    def test_sin_cabecera_authorization(self, client):
        assert client.get("/protegido").status_code == 401

    def test_esquema_distinto_de_bearer(self, client, keys):
        pem, _ = keys
        response = client.get(
            "/protegido", headers={"Authorization": f"Basic {_token(pem)}"}
        )

        assert response.status_code == 401

    def test_token_expirado(self, client, keys):
        pem, _ = keys
        expired = datetime.now(timezone.utc) - timedelta(hours=1)
        token = _token(pem, exp=expired, iat=expired - timedelta(hours=1))

        response = client.get(
            "/protegido", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 401

    def test_firmado_con_otra_clave(self, client):
        """A token from a different Supabase project must not be accepted."""
        otro_pem, _ = _keypair()

        response = client.get(
            "/protegido", headers={"Authorization": f"Bearer {_token(otro_pem)}"}
        )

        assert response.status_code == 401

    def test_sin_claim_sub(self, client, keys):
        """Without a subject there is no user to scope the data to."""
        pem, _ = keys
        token = _token(pem, sub=None)

        response = client.get(
            "/protegido", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 401

    def test_audiencia_incorrecta(self, client, keys):
        pem, _ = keys
        token = _token(pem, aud="otra-cosa")

        response = client.get(
            "/protegido", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 401

    def test_emisor_incorrecto(self, client, keys):
        pem, _ = keys
        token = _token(pem, iss="https://otro-proyecto.supabase.co/auth/v1")

        response = client.get(
            "/protegido", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 401

    def test_token_ilegible(self, client):
        response = client.get(
            "/protegido", headers={"Authorization": "Bearer no-es-un-jwt"}
        )

        assert response.status_code == 401
