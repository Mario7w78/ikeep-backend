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
