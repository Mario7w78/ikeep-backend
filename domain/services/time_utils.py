"""Pure helper functions for absolute-minute conversion and midnight-crossing detection.

Convention:
    If ``hora_fin <= hora_inicio``, the interval crosses midnight — end time
    falls on the following day.  All conversion is stateless and unit-testable.

    Absolute minutes are measured from week start (0 … 10079).
"""

MINUTES_PER_DAY = 1440
WEEK_MINUTES = 10080

# ── Límites de validación ─────────────────────────────────────────
MAX_BLOCK_MINUTES = 960     # 16h — duración máxima de un bloque continuo
MAX_SLEEP_MINUTES = 720     # 12h — nadie necesita más de 12h de sueño
MAX_CROSSING_DAYS = 2       # una actividad no puede cruzar más de 2 días


def to_abs(dia: int, minutos: int) -> int:
    """Convert ``(dia, minutos)`` to absolute minutes from week start.

    ``minutos`` is expected in [0, 1439]; no clamping is performed.
    """
    return dia * MINUTES_PER_DAY + minutos


def to_dia_hora(abs_minutes: int) -> tuple[int, int]:
    """Split absolute minutes back to ``(dia, hora)``.

    ``dia`` is ``abs_minutes // 1440``, ``hora`` is ``abs_minutes % 1440``.
    """
    return (abs_minutes // MINUTES_PER_DAY, abs_minutes % MINUTES_PER_DAY)


def abs_duration(hora_inicio: int, hora_fin: int) -> int:
    """Compute interval duration considering midnight crossing.

    If ``hora_fin <= hora_inicio`` the interval is treated as crossing
    midnight and 1440 is added to the end before subtracting.
    """
    if hora_fin <= hora_inicio:
        return hora_fin + MINUTES_PER_DAY - hora_inicio
    return hora_fin - hora_inicio


def is_crossing(hora_inicio: int, hora_fin: int) -> bool:
    """Return ``True`` when the interval crosses midnight."""
    return hora_fin <= hora_inicio


def to_abs_minutes(dia: int, hora_inicio: int, hora_fin: int) -> tuple[int, int]:
    """Convenience: convert ``(dia, hora_inicio, hora_fin)`` to absolute
    ``(abs_start, abs_end)``.

    Midnight crossing is handled automatically when ``hora_fin <= hora_inicio``.
    """
    abs_start = to_abs(dia, hora_inicio)
    dur = abs_duration(hora_inicio, hora_fin)
    return (abs_start, abs_start + dur)


def from_abs_minutes(abs_minutes: int) -> tuple[int, int]:
    """Convenience alias for :func:`to_dia_hora`."""
    return to_dia_hora(abs_minutes)
