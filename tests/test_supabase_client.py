"""Tests for the Supabase access layer and the startup schema check.

Nothing here reaches the network: `create_client` builds its HTTP clients
lazily and makes no request on construction, so the factories can be tested
directly, and the schema check is driven through a stubbed client.
"""

from unittest.mock import Mock, patch

import pytest

from infrastructure.adapters.outbound.supabase.client import (
    REQUIRED_TABLES,
    anon_client,
    client_for_user,
    missing_tables,
    verify_schema,
)
from infrastructure.config import settings as settings_module
from infrastructure.config.settings import Settings


@pytest.fixture(autouse=True)
def settings_with_supabase():
    original = settings_module._settings
    settings_module._settings = Settings(
        SUPABASE_URL="https://proyecto-de-prueba.supabase.co",
        SUPABASE_ANON_KEY="clave-de-prueba",
    )
    anon_client.cache_clear()
    yield
    settings_module._settings = original
    anon_client.cache_clear()


def _stub_client(failing: set[str] | None = None) -> Mock:
    """A client whose .table(name) raises for the names in `failing`."""
    failing = failing or set()

    def table(name):
        if name in failing:
            raise Exception(f'relation "public.{name}" does not exist')
        chain = Mock()
        chain.select.return_value.limit.return_value.execute.return_value = Mock(
            data=[]
        )
        return chain

    client = Mock()
    client.table.side_effect = table
    return client


class TestFabricaDeClientes:
    def test_el_cliente_anonimo_se_cachea(self):
        assert anon_client() is anon_client()

    def test_el_cliente_de_usuario_adjunta_su_token(self):
        """RLS depends on this: without the token every query runs as anon."""
        with patch(
            "infrastructure.adapters.outbound.supabase.client.create_client"
        ) as create:
            cliente = client_for_user("el-jwt-del-usuario")

        cliente.postgrest.auth.assert_called_once_with("el-jwt-del-usuario")
        assert cliente is create.return_value

    def test_el_cliente_de_usuario_no_se_cachea(self):
        """Tokens expire and belong to different people — never reuse one."""
        with patch(
            "infrastructure.adapters.outbound.supabase.client.create_client"
        ) as create:
            create.side_effect = [Mock(), Mock()]

            primero = client_for_user("token-a")
            segundo = client_for_user("token-b")

        assert create.call_count == 2
        assert primero is not segundo
        primero.postgrest.auth.assert_called_once_with("token-a")
        segundo.postgrest.auth.assert_called_once_with("token-b")

    def test_falla_si_falta_configuracion(self):
        settings_module._settings = Settings(SUPABASE_URL="", SUPABASE_ANON_KEY="")
        anon_client.cache_clear()

        with pytest.raises(RuntimeError, match="SUPABASE_URL"):
            anon_client()


class TestChequeoDeEsquema:
    def test_no_falta_nada_cuando_todas_responden(self):
        assert missing_tables(_stub_client()) == []

    def test_reporta_las_tablas_ausentes(self):
        faltantes = missing_tables(_stub_client(failing={"schedules", "profiles"}))

        assert sorted(faltantes) == ["profiles", "schedules"]

    def test_una_tabla_vacia_no_es_una_tabla_ausente(self):
        """RLS returns no rows to an anonymous caller — that is not an error."""
        assert missing_tables(_stub_client()) == []

    def test_revisa_las_cinco_tablas(self):
        assert set(REQUIRED_TABLES) == {
            "activities",
            "energy_records",
            "profiles",
            "schedules",
            "user_settings",
        }

    def test_verify_schema_explota_nombrando_lo_que_falta(self):
        with pytest.raises(RuntimeError) as exc:
            verify_schema(_stub_client(failing={"activities"}))

        assert "activities" in str(exc.value)
        assert "migrations" in str(exc.value)

    def test_verify_schema_pasa_cuando_esta_completo(self):
        verify_schema(_stub_client())
