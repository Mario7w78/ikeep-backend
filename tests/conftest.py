"""Shared test setup.

Tests must not depend on the network or on a live Supabase project, so the
startup schema check is off for the whole suite. The check itself is covered
directly in test_supabase_client.py, against a stubbed client.
"""

import pytest

from infrastructure.config import settings as settings_module


@pytest.fixture(autouse=True, scope="session")
def _no_schema_check_in_tests():
    original = settings_module._settings
    settings_module._settings = settings_module.Settings(
        VERIFY_SCHEMA_ON_STARTUP=False
    )
    yield
    settings_module._settings = original


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: corre contra Supabase vivo; se salta sin credenciales",
    )
    # Desactivar la verificacion ANTES de coleccion: hay tests que importan
    # main al importarse, y create_app() consulta el proyecto vivo si nadie
    # la frena antes. Los fixtures llegan tarde para eso.
    settings_module._settings = settings_module.Settings(
        VERIFY_SCHEMA_ON_STARTUP=False
    )


def pytest_unconfigure(config):
    settings_module._settings = None
