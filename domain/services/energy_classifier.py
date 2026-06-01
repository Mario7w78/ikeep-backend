from datetime import datetime, timezone

from domain.entities.enums import PatronEnergia
from domain.entities.user_context import RegistroEnergia


def clasificar_patron_energia(
    history: list[RegistroEnergia],
    current_level: int,
) -> PatronEnergia:
    """Clasifica el patrón de energía del usuario en TRANSCRIPTORIO, TENDENCIA o CRONICO.

    Usa el historial de los últimos 14 días: si la relación de entradas con
    nivel < 2 (baja) es:
        < 20%   → TRANSCRIPTORIO
        20-60%  → TENDENCIA
        > 60%   → CRONICO

    Args:
        history: Lista de registros de energía.
        current_level: Nivel de energía actual (no usado actualmente, reservado).

    Returns:
        PatronEnergia: clasificación del patrón.
    """
    if not history:
        return PatronEnergia.TRANSCRIPTORIO

    cutoff = datetime.now(timezone.utc).timestamp() - 14 * 24 * 3600
    recent = [
        r
        for r in history
        if _to_epoch(r.timestamp) >= cutoff
    ]

    if not recent:
        return PatronEnergia.TRANSCRIPTORIO

    low_count = sum(1 for r in recent if r.nivel < 2)
    ratio = low_count / len(recent)

    if ratio > 0.6:
        return PatronEnergia.CRONICO
    if ratio >= 0.2:
        return PatronEnergia.TENDENCIA
    return PatronEnergia.TRANSCRIPTORIO


def _to_epoch(ts: str) -> float:
    """Convierte un string ISO 8601 a timestamp Unix."""
    return datetime.fromisoformat(ts).timestamp()
