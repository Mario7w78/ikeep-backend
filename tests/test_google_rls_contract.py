"""Contrato de aislamiento entre usuarios sobre las tablas de Google.

Estos tests corren contra un Supabase VIVO y necesitan dos JWTs de usuarios
de prueba distintos, porque lo que prueban es exactamente eso: que el token
de uno no alcance para ver las filas del otro. Sin credenciales se saltan —
el resto de la suite no depende de la red.

Para activarlos:

    GOOGLE_TEST_JWT_A=... GOOGLE_TEST_JWT_B=... \
    pytest -m integration tests/test_google_rls_contract.py

La regla que defienden: el adaptador nunca filtra por user_id, adjunta el
token y confia en RLS. Si alguien rompe esa confianza (una consulta sin
token, un cliente anon sirviendo datos), estos tests dejan de pasar.
"""

import os
from datetime import datetime, timezone

import pytest

from domain.ports.outbound.google_event_repository_port import EventoImportado
from domain.ports.outbound.google_token_repository_port import TokensDeConexion
from infrastructure.adapters.outbound.supabase.google_event_repository import (
    SupabaseGoogleEventsRepository,
)
from infrastructure.adapters.outbound.supabase.google_token_repository import (
    SupabaseGoogleTokensRepository,
)
from infrastructure.config.settings import get_settings

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (
            os.environ.get("GOOGLE_TEST_JWT_A")
            and os.environ.get("GOOGLE_TEST_JWT_B")
        ),
        reason="requiere GOOGLE_TEST_JWT_A y GOOGLE_TEST_JWT_B contra Supabase vivo",
    ),
]


@pytest.fixture
def usuario_a():
    return os.environ["GOOGLE_TEST_JWT_A"]


@pytest.fixture
def usuario_b():
    return os.environ["GOOGLE_TEST_JWT_B"]


@pytest.fixture(autouse=True)
def _limpiar(usuario_a, usuario_b):
    yield
    for token in (usuario_a, usuario_b):
        SupabaseGoogleEventsRepository().borrar_todo(token)
        SupabaseGoogleTokensRepository().borrar(token)
        SupabaseGoogleTokensRepository().borrar_sync_token(token)


def _evento(id_: str) -> EventoImportado:
    return EventoImportado(
        id=id_,
        titulo=f"de-{id_}",
        inicio=datetime(2026, 8, 3, 10, tzinfo=timezone.utc),
        fin=datetime(2026, 8, 3, 11, tzinfo=timezone.utc),
    )


class TestAislamientoGoogleEvents:
    def test_a_no_ve_los_eventos_de_b(self, usuario_a, usuario_b):
        eventos = SupabaseGoogleEventsRepository()
        eventos.upsert(usuario_b, "usuario-b", [_evento("evt-de-b")])

        vistas_por_a = eventos.del_rango(
            usuario_a,
            datetime(2026, 8, 1, tzinfo=timezone.utc),
            datetime(2026, 9, 1, tzinfo=timezone.utc),
        )

        assert all(e.id != "evt-de-b" for e in vistas_por_a)

    def test_a_ve_lo_suyo_y_solo_lo_suyo(self, usuario_a, usuario_b):
        eventos = SupabaseGoogleEventsRepository()
        eventos.upsert(usuario_a, "usuario-a", [_evento("evt-de-a")])
        eventos.upsert(usuario_b, "usuario-b", [_evento("evt-de-b")])

        vistas_por_a = eventos.del_rango(
            usuario_a,
            datetime(2026, 8, 1, tzinfo=timezone.utc),
            datetime(2026, 9, 1, tzinfo=timezone.utc),
        )

        assert [e.id for e in vistas_por_a] == ["evt-de-a"]


class TestAislamientoTokens:
    def test_la_conexion_de_b_no_aparece_para_a(self, usuario_a, usuario_b):
        tokens = SupabaseGoogleTokensRepository()
        tokens.guardar(
            usuario_b, TokensDeConexion(user_id="usuario-b", refresh_token_cifrado="x")
        )

        assert tokens.obtener(usuario_a) is None
        assert tokens.obtener(usuario_b) is not None

    def test_el_sync_token_tambien_es_por_usuario(self, usuario_a, usuario_b):
        tokens = SupabaseGoogleTokensRepository()
        tokens.guardar_sync_token(usuario_b, "usuario-b", "st-de-b")

        assert tokens.sync_token(usuario_a) is None
