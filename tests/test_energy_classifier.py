"""Unit tests for clasificar_patron_energia."""

from datetime import datetime, timezone, timedelta

from domain.entities.enums import PatronEnergia
from domain.entities.user_context import RegistroEnergia
from domain.services.energy_classifier import clasificar_patron_energia


def _ts(days_ago: int = 0) -> str:
    """Helper: ISO timestamp N days ago from now."""
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.isoformat()


def _entry(nivel: int, days_ago: int = 0) -> RegistroEnergia:
    return RegistroEnergia(
        timestamp=_ts(days_ago),
        nivel=nivel,
        dia_semana=0,
    )


# ── Empty / edge cases ──────────────────────────────────────────


def test_empty_history_returns_transcriptoriano():
    assert clasificar_patron_energia([], 2) == PatronEnergia.TRANSCRIPTORIO


def test_all_high_energy_returns_transcriptoriano():
    history = [_entry(3) for _ in range(14)]
    assert clasificar_patron_energia(history, 3) == PatronEnergia.TRANSCRIPTORIO


# ── Threshold: < 20% → TRANSCRIPTORIO ────────────────────────────


def test_14_percent_low_returns_transcriptoriano():
    # 2 low out of 14 → ~14%
    history = [_entry(3) for _ in range(12)] + [_entry(1) for _ in range(2)]
    assert clasificar_patron_energia(history, 2) == PatronEnergia.TRANSCRIPTORIO


# ── Threshold: 20% – 60% → TENDENCIA ─────────────────────────────


def test_21_percent_low_returns_tendencia():
    # 3 low out of 14 → ~21%
    history = [_entry(3) for _ in range(11)] + [_entry(1) for _ in range(3)]
    assert clasificar_patron_energia(history, 2) == PatronEnergia.TENDENCIA


def test_57_percent_low_returns_tendencia():
    # 8 low out of 14 → ~57%
    history = [_entry(3) for _ in range(6)] + [_entry(1) for _ in range(8)]
    assert clasificar_patron_energia(history, 2) == PatronEnergia.TENDENCIA


# ── Threshold: > 60% → CRONICO ───────────────────────────────────


def test_64_percent_low_returns_cronico():
    # 9 low out of 14 → ~64%
    history = [_entry(3) for _ in range(5)] + [_entry(1) for _ in range(9)]
    assert clasificar_patron_energia(history, 2) == PatronEnergia.CRONICO


def test_all_low_returns_cronico():
    history = [_entry(1) for _ in range(14)]
    assert clasificar_patron_energia(history, 1) == PatronEnergia.CRONICO


# ── Boundary: exactly 20% ────────────────────────────────────────


def test_exactly_20_percent_low_returns_tendencia():
    # 3 low out of 15 → exactly 20%
    history = [_entry(3) for _ in range(12)] + [_entry(1) for _ in range(3)]
    assert clasificar_patron_energia(history, 2) == PatronEnergia.TENDENCIA


# ── 14-day window ────────────────────────────────────────────────


def test_old_entries_are_ignored():
    # 2 low entries from 20 days ago should not count
    recent = [_entry(3) for _ in range(10)]
    old = [_entry(1, days_ago=20) for _ in range(5)]
    history = recent + old
    assert clasificar_patron_energia(history, 2) == PatronEnergia.TRANSCRIPTORIO


def test_all_old_returns_transcriptoriano():
    # All entries older than 14 days → effectively empty
    history = [_entry(2, days_ago=15) for _ in range(10)]
    assert clasificar_patron_energia(history, 2) == PatronEnergia.TRANSCRIPTORIO
