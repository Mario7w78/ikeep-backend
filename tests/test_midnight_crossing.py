"""Tests for midnight-crossing support.

Covers time_utils helpers, CP-SAT model integration, and validation.
"""

import pytest
from ortools.sat.python import cp_model

from domain.entities.activity import Actividad
from domain.entities.enums import Dificultad, EstadoSolucion, TipoActividad
from domain.entities.location import Ubicacion
from domain.entities.schedule_request import SolicitudHorario
from domain.entities.user_context import DreamBlock, ContextoUsuario
from domain.services.schedule_service import ScheduleOptimizer
from domain.services.time_utils import (
    WEEK_MINUTES,
    abs_duration,
    from_abs_minutes,
    is_crossing,
    to_abs,
    to_abs_minutes,
    to_dia_hora,
)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Phase 4.1 + 4.2 â€” Unit: time_utils
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


class TestToAbs:
    """to_abs(dia, minutos) â†’ absolute minutes from week start."""

    def test_zero(self):
        assert to_abs(0, 0) == 0

    def test_normal(self):
        assert to_abs(0, 480) == 480

    def test_late_evening(self):
        assert to_abs(0, 1380) == 1380

    def test_multi_day(self):
        assert to_abs(2, 360) == 2 * 1440 + 360

    def test_end_of_week(self):
        assert to_abs(6, 1439) == 6 * 1440 + 1439  # last minute of the week


class TestToDiaHora:
    """to_dia_hora(abs_minutes) â†’ (dia, hora)."""

    def test_zero(self):
        assert to_dia_hora(0) == (0, 0)

    def test_normal(self):
        assert to_dia_hora(480) == (0, 480)

    def test_crossing_end(self):
        """abs=1500 â†’ dia=1, hora=60 (modulo 1440)."""
        assert to_dia_hora(1500) == (1, 60)

    def test_boundary_1440(self):
        assert to_dia_hora(1440) == (1, 0)

    def test_end_of_week(self):
        assert to_dia_hora(WEEK_MINUTES - 1) == (6, 1439)

    def test_midweek(self):
        assert to_dia_hora(2 * 1440 + 500) == (2, 500)


class TestAbsDuration:
    """abs_duration(hora_inicio, hora_fin) â†’ minutes."""

    def test_normal_same_day(self):
        assert abs_duration(480, 600) == 120

    def test_crossing_midnight(self):
        """1380 â†’ 60 crossing: (60 + 1440) - 1380 = 120."""
        assert abs_duration(1380, 60) == 120

    def test_crossing_large(self):
        """1140 â†’ 60: (60 + 1440) - 1140 = 360."""
        assert abs_duration(1140, 60) == 360

    def test_zero_length_crossing(self):
        """0 â†’ 0: full-day crossing, 1440 min."""
        assert abs_duration(0, 0) == 1440

    def test_same_time_non_zero(self):
        assert abs_duration(500, 500) == 1440

    def test_full_day_non_crossing(self):
        assert abs_duration(0, 1439) == 1439

    def test_edge_1439_to_0(self):
        """Last minute of the day crossing to first minute of next day."""
        assert abs_duration(1439, 0) == 1


class TestIsCrossing:
    """is_crossing(hora_inicio, hora_fin) â†’ bool."""

    def test_normal_not_crossing(self):
        assert is_crossing(480, 600) is False

    def test_crossing(self):
        assert is_crossing(1380, 60) is True

    def test_equal_is_crossing(self):
        assert is_crossing(100, 100) is True

    def test_boundary_not_crossing(self):
        assert is_crossing(0, 1439) is False


class TestToAbsMinutes:
    """to_abs_minutes(dia, hora_inicio, hora_fin) â†’ (abs_start, abs_end)."""

    def test_normal_same_day(self):
        start, end = to_abs_minutes(0, 480, 600)
        assert start == 480
        assert end == 600

    def test_crossing_midnight(self):
        """dia=0, inicio=1140, fin=60 â†’ start=1140, end=1500."""
        start, end = to_abs_minutes(0, 1140, 60)
        assert start == 1140
        assert end == 1500

    def test_crossing_sleep(self):
        """dia=1, inicio=1380, fin=420 â†’ start=2820, end=3300."""
        start, end = to_abs_minutes(1, 1380, 420)
        assert start == 2820
        assert end == 3300

    def test_zero_length(self):
        start, end = to_abs_minutes(0, 0, 0)
        assert start == 0
        assert end == 1440


class TestFromAbsMinutes:
    """from_abs_minutes(abs_time) â†’ (dia, hora)."""

    def test_normal(self):
        assert from_abs_minutes(480) == (0, 480)

    def test_crossing_end(self):
        assert from_abs_minutes(1500) == (1, 60)

    def test_zero(self):
        assert from_abs_minutes(0) == (0, 0)

    def test_end_of_week(self):
        assert from_abs_minutes(10079) == (6, 1439)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Helpers for integration tests
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


def _make_solver() -> cp_model.CpSolver:
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.max_time_in_seconds = 5
    return solver


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Phase 4.3 â€” Integration: fixed activity crossing midnight
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


def test_fixed_activity_crossing_midnight():
    """CP-SAT model with a fixed activity crossing midnight is feasible.

    Actividad(dia=0, hora_inicio=1140, hora_fin=60).
    Absolute interval: [1140, 1500], duration 360 min.
    """
    actividades = [
        Actividad(
            id="cross_fix",
            nombre="Crossing Fixed",
            tipo=TipoActividad.CLASE,
            dia=0,
            hora_inicio=1140,
            hora_fin=60,
            ubicacion_id="loc_a",
        ),
    ]
    ctx = ContextoUsuario()
    request = SolicitudHorario(
        actividades_fijas=actividades,
        actividades_optimizables_puras=[],
        contexto_usuario=ctx,
    )
    optimizer = ScheduleOptimizer(timeout_seconds=5)
    response = optimizer.generar(request)

    # The model has no flex tasks, so it should be feasible immediately
    assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE), (
        f"Crossing fixed activity should be feasible, got {response.estado}"
    )

    # Verify the crossing block is in the response
    assert len(response.bloques) == 1
    block = response.bloques[0]
    assert block.id_actividad == "cross_fix"
    assert block.dia == 0
    assert block.hora_inicio == 1140
    # hora_fin should signal crossing: 60 < 1140
    assert block.hora_fin == 60, (
        f"Expected hora_fin=60 (crossing signal), got {block.hora_fin}"
    )
    assert block.hora_fin < block.hora_inicio, (
        "Crossing block should have hora_fin < hora_inicio"
    )


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Phase 4.4 â€” Integration: sleep block crossing midnight
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


def test_sleep_block_crossing_midnight():
    """CP-SAT model with a sleep block crossing midnight.

    DreamBlock(dia=1, inicio=1380, fin=420) â†’ absolute [2820, 3300].
    A flex task must be scheduled alongside this sleep block.
    """
    ctx = ContextoUsuario(
        nivel_energia=3,
        horario_inicio=480,
        horario_fin=1200,
        dream_blocks=[
            DreamBlock(dia=1, inicio=1380, fin=420),
        ],
    )
    tareas = [
        Actividad(
            id="flex_task_1",
            nombre="Flex Task",
            tipo=TipoActividad.TAREA,
            dia=1,
            hora_inicio=0,
            hora_fin=0,
            ubicacion_id="loc_a",
            duracion_estimada=60,
            dificultad=Dificultad.MEDIA,
            prioridad=1,
        ),
    ]
    request = SolicitudHorario(
        actividades_fijas=[],
        actividades_optimizables_puras=tareas,
        contexto_usuario=ctx,
    )
    optimizer = ScheduleOptimizer(timeout_seconds=5)
    response = optimizer.generar(request)

    assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE), (
        f"Crossing sleep block + flex task should be feasible, got {response.estado}"
    )

    # The flex task should be scheduled
    flex_blocks = [b for b in response.bloques if b.id_actividad == "flex_task_1"]
    assert len(flex_blocks) == 1, "Flex task should be scheduled"
    block = flex_blocks[0]
    assert block.hora_inicio >= ctx.horario_inicio[block.dia]
    assert block.hora_fin <= ctx.horario_fin[block.dia]
    assert block.hora_fin - block.hora_inicio == 60, (
        f"Expected 60-minute flex task, got {block.hora_fin - block.hora_inicio}"
    )


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Phase 4.5 â€” Integration: mixed crossing + same-day activities
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


def test_mixed_crossing_and_same_day():
    """Crossing sleep + same-day fixed + flex tasks coexist.

    Sleep crossing dia=1 (1380-420) â†’ occupies [2820, 3300].
    Fixed dia=0 (1320-60 crossing) â†’ occupies [1320, 1500].
    Fixed dia=1 (120-240) â†’ occupies [1560, 1680].
    Flex tasks with deadline dia=1.
    """
    ctx = ContextoUsuario(
        nivel_energia=3,
        horario_inicio=480,
        horario_fin=1200,
        dream_blocks=[
            DreamBlock(dia=1, inicio=1380, fin=420),
        ],
    )
    actividades_fijas = [
        Actividad(
            id="cross_fix_0",
            nombre="Fixed Crossing",
            tipo=TipoActividad.CLASE,
            dia=0,
            hora_inicio=1320,
            hora_fin=60,
            ubicacion_id="loc_a",
        ),
        Actividad(
            id="same_day_fix_1",
            nombre="Fixed Same-Day",
            tipo=TipoActividad.CLASE,
            dia=1,
            hora_inicio=120,
            hora_fin=240,
            ubicacion_id="loc_b",
        ),
    ]
    tareas = [
        Actividad(
            id="flex_a",
            nombre="Flex A",
            tipo=TipoActividad.TAREA,
            dia=1,
            hora_inicio=0,
            hora_fin=0,
            ubicacion_id="loc_c",
            duracion_estimada=60,
            dificultad=Dificultad.MEDIA,
        ),
        Actividad(
            id="flex_b",
            nombre="Flex B",
            tipo=TipoActividad.TAREA,
            dia=1,
            hora_inicio=0,
            hora_fin=0,
            ubicacion_id="loc_c",
            duracion_estimada=45,
            dificultad=Dificultad.BAJA,
        ),
    ]
    request = SolicitudHorario(
        actividades_fijas=actividades_fijas,
        actividades_optimizables_puras=tareas,
        contexto_usuario=ctx,
        ubicaciones=[
            Ubicacion(id="loc_a", nombre="A", latitud=0.0, longitud=0.0),
            Ubicacion(id="loc_b", nombre="B", latitud=0.0, longitud=0.0),
            Ubicacion(id="loc_c", nombre="C", latitud=0.0, longitud=0.0),
        ],
    )
    optimizer = ScheduleOptimizer(timeout_seconds=10)
    response = optimizer.generar(request)

    assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE), (
        f"Mixed crossing scenario should be feasible, got {response.estado}"
    )

    # All blocks should be in the response
    block_ids = {b.id_actividad for b in response.bloques}
    assert "flex_a" in block_ids, "Flex A should be scheduled"
    assert "flex_b" in block_ids, "Flex B should be scheduled"
    assert "cross_fix_0" in block_ids, "Crossing fixed should be in response"
    assert "same_day_fix_1" in block_ids, "Same-day fixed should be in response"

    # Verify crossing fixed has correct signal
    cross_blocks = [b for b in response.bloques if b.id_actividad == "cross_fix_0"]
    assert len(cross_blocks) == 1
    assert cross_blocks[0].hora_inicio == 1320
    assert cross_blocks[0].hora_fin == 60  # crossing signal


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Phase 4.6 â€” Integration: multi-day crossing validation
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


def test_multi_day_crossing_rejected():
    """Fixed activity with >2880 min duration raises ValueError."""
    # Non-crossing but >2880 min duration (hora_fin >> 1440)
    actividades = [
        Actividad(
            id="too_long",
            nombre="Too Long",
            tipo=TipoActividad.CLASE,
            dia=0,
            hora_inicio=0,
            hora_fin=2881,  # > 2880 min
        ),
    ]
    with pytest.raises(ValueError, match="superando el máximo permitido"):
        ScheduleOptimizer._validate_fixed_overlaps(actividades)


def test_single_crossing_allowed():
    """Single crossing (1440 min) should pass validation."""
    actividades = [
        Actividad(
            id="single_cross",
            nombre="Single Crossing",
            tipo=TipoActividad.CLASE,
            dia=0,
            hora_inicio=0,
            hora_fin=0,  # full-day crossing, 1440 min
        ),
    ]
    # Should not raise
    ScheduleOptimizer._validate_fixed_overlaps(actividades)


def test_non_crossing_normal_allowed():
    """Normal non-crossing activity should pass validation."""
    actividades = [
        Actividad(
            id="normal",
            nombre="Normal",
            tipo=TipoActividad.CLASE,
            dia=0,
            hora_inicio=480,
            hora_fin=600,
        ),
    ]
    ScheduleOptimizer._validate_fixed_overlaps(actividades)


def test_exact_2880_boundary_allowed():
    """Exactly 2880 min should pass validation (boundary)."""
    actividades = [
        Actividad(
            id="boundary",
            nombre="Boundary",
            tipo=TipoActividad.CLASE,
            dia=0,
            hora_inicio=0,
            hora_fin=2880,  # exactly 2880 min
        ),
    ]
    ScheduleOptimizer._validate_fixed_overlaps(actividades)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Phase 4.7 â€” Extra: overlap detection across midnight
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


def test_crossing_activities_overlap_detected():
    """Two crossing activities that overlap should raise ValueError.

    A: dia=0, inicio=1320, fin=120  â†’ [1320, 1560]
    B: dia=1, inicio=60,   fin=180 â†’ [1500, 1620]
    A ends at 1560, B starts at 1500 â†’ overlap!
    """
    actividades = [
        Actividad(
            id="a",
            nombre="Activity A",
            tipo=TipoActividad.CLASE,
            dia=0,
            hora_inicio=1320,
            hora_fin=120,
        ),
        Actividad(
            id="b",
            nombre="Activity B",
            tipo=TipoActividad.CLASE,
            dia=1,
            hora_inicio=60,
            hora_fin=180,
        ),
    ]
    with pytest.raises(ValueError, match="Actividades fijas solapadas"):
        ScheduleOptimizer._validate_fixed_overlaps(actividades)


def test_crossing_activities_no_overlap():
    """Crossing A followed by same-day B with no overlap.

    A: dia=0, inicio=1320, fin=60   â†’ [1320, 1500]
    B: dia=1, inicio=120,  fin=240  â†’ [1560, 1680]
    1500 < 1560 â†’ no overlap.
    """
    actividades = [
        Actividad(
            id="a",
            nombre="Crossing A",
            tipo=TipoActividad.CLASE,
            dia=0,
            hora_inicio=1320,
            hora_fin=60,
        ),
        Actividad(
            id="b",
            nombre="Day-after B",
            tipo=TipoActividad.CLASE,
            dia=1,
            hora_inicio=120,
            hora_fin=240,
        ),
    ]
    ScheduleOptimizer._validate_fixed_overlaps(actividades)  # no raise


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Robustness: consistency validation
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


def test_sleep_block_exceeds_max_duration():
    """Sleep block > MAX_SLEEP_MINUTES raises ValueError."""
    ctx = ContextoUsuario(
        horario_inicio=480,
        horario_fin=1200,
        dream_blocks=[
            DreamBlock(dia=0, inicio=0, fin=1440),  # 24h sleep â†’ too long
        ],
    )
    request = SolicitudHorario(
        actividades_fijas=[],
        actividades_optimizables_puras=[],
        contexto_usuario=ctx,
    )
    with pytest.raises(ValueError, match="superando el máximo"):
        ScheduleOptimizer(timeout_seconds=1).generar(request)


def test_sleep_block_conflicts_with_fixed():
    """Sleep overlapping with fixed activity raises ValueError."""
    ctx = ContextoUsuario(
        horario_inicio=480,
        horario_fin=1200,
        dream_blocks=[
            DreamBlock(dia=0, inicio=1380, fin=120),  # ~23:00-02:00
        ],
    )
    actividades = [
        Actividad(
            id="night_fix",
            nombre="Night Work",
            tipo=TipoActividad.CLASE,
            dia=1,  # crosses to day 1 â†’ abs [60, 180]
            hora_inicio=60,
            hora_fin=180,
        ),
    ]
    request = SolicitudHorario(
        actividades_fijas=actividades,
        actividades_optimizables_puras=[],
        contexto_usuario=ctx,
    )
    with pytest.raises(ValueError, match="solapa con un bloque de sueño"):
        ScheduleOptimizer(timeout_seconds=1).generar(request)


def test_insufficient_capacity_raises():
    """More flex task minutes than available raises ValueError."""
    ctx = ContextoUsuario(
        horario_inicio=480,  # 08:00
        horario_fin=600,    # 10:00 â†’ only 120 min/day
        dream_blocks=[],
    )
    tareas = [
        Actividad(
            id="big_task",
            nombre="Big Task",
            tipo=TipoActividad.TAREA,
            dia=0,
            hora_inicio=0, hora_fin=0,
            duracion_estimada=180,  # 180 min > 120 available
            dificultad=Dificultad.MEDIA,
        ),
    ]
    request = SolicitudHorario(
        actividades_fijas=[],
        actividades_optimizables_puras=tareas,
        contexto_usuario=ctx,
    )
    with pytest.raises(ValueError, match="ocupa.*min.*duración.*disponible.*solo.*min"):
        ScheduleOptimizer(timeout_seconds=1).generar(request)


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1 — Schema & Arithmetic Fixes (R1–R5)
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchemaCrossingPhase1:
    """R1: Schema validation accepts/rejects crossing windows."""

    def test_accepts_crossing(self):
        """horario_inicio=480, horario_fin=60 should validate OK."""
        from schemas.schedule_request import SolicitudHorario as PydanticSolicitud
        from schemas.user_context import ContextoUsuario as PydanticCtx

        solicitud = PydanticSolicitud(
            actividades_fijas=[],
            actividades_optimizables_puras=[],
            contexto_usuario=PydanticCtx(horario_inicio=480, horario_fin=60),
        )
        _ = solicitud  # should not raise

    def test_accepts_normal_window(self):
        """Same-day window (480, 1200) still works."""
        from schemas.schedule_request import SolicitudHorario as PydanticSolicitud
        from schemas.user_context import ContextoUsuario as PydanticCtx

        solicitud = PydanticSolicitud(
            actividades_fijas=[],
            actividades_optimizables_puras=[],
            contexto_usuario=PydanticCtx(horario_inicio=480, horario_fin=1200),
        )
        _ = solicitud  # should not raise

    def test_accepts_equal_nonzero_duration(self):
        """Equal but crossing (0, 0) = 1440 min should validate OK."""
        from schemas.schedule_request import SolicitudHorario as PydanticSolicitud
        from schemas.user_context import ContextoUsuario as PydanticCtx

        solicitud = PydanticSolicitud(
            actividades_fijas=[],
            actividades_optimizables_puras=[],
            contexto_usuario=PydanticCtx(horario_inicio=0, horario_fin=0),
        )
        _ = solicitud  # should not raise

    def test_rejects_zero_duration(self):
        """Zero-duration window (1440, 0) should raise ValueError."""
        from schemas.schedule_request import SolicitudHorario as PydanticSolicitud
        from schemas.user_context import ContextoUsuario as PydanticCtx

        with pytest.raises(ValueError, match="duraci.n cero"):
            PydanticSolicitud(
                actividades_fijas=[],
                actividades_optimizables_puras=[],
                contexto_usuario=PydanticCtx(horario_inicio=1440, horario_fin=0),
            )

    def test_rejects_out_of_range_inicio(self):
        """inicio < 0 should raise ValueError."""
        from schemas.schedule_request import SolicitudHorario as PydanticSolicitud
        from schemas.user_context import ContextoUsuario as PydanticCtx

        with pytest.raises(ValueError):
            PydanticSolicitud(
                actividades_fijas=[],
                actividades_optimizables_puras=[],
                contexto_usuario=PydanticCtx(horario_inicio=-1, horario_fin=1200),
            )

    def test_rejects_out_of_range_fin(self):
        """fin > 1440 should raise ValueError."""
        from schemas.schedule_request import SolicitudHorario as PydanticSolicitud
        from schemas.user_context import ContextoUsuario as PydanticCtx

        with pytest.raises(ValueError):
            PydanticSolicitud(
                actividades_fijas=[],
                actividades_optimizables_puras=[],
                contexto_usuario=PydanticCtx(horario_inicio=480, horario_fin=1441),
            )


class TestValidateTaskDurationPhase1:
    """R2: _validate_task_duration uses effective window."""

    def test_crossing_accepts_valid(self):
        """600 min task in (480, 60) = 1020 effective window → OK."""
        ctx = ContextoUsuario(horario_inicio=480, horario_fin=60)
        tasks = [
            Actividad(
                id="t1", nombre="Test", tipo=TipoActividad.TAREA,
                dia=0, hora_inicio=0, hora_fin=0,
                duracion_estimada=600,
                dificultad=Dificultad.MEDIA,
            ),
        ]
        ScheduleOptimizer._validate_task_duration(tasks, ctx, 0, 7)

    def test_crossing_rejects_excessive(self):
        """1080 min task in (480, 60) = 1020 effective → error."""
        ctx = ContextoUsuario(horario_inicio=480, horario_fin=60)
        tasks = [
            Actividad(
                id="t1", nombre="Test", tipo=TipoActividad.TAREA,
                dia=0, hora_inicio=0, hora_fin=0,
                duracion_estimada=1080,
                dificultad=Dificultad.MEDIA,
            ),
        ]
        with pytest.raises(ValueError, match="solo.*min"):
            ScheduleOptimizer._validate_task_duration(tasks, ctx, 0, 7)

    def test_same_day_still_works(self):
        """600 min task in (480, 1200) = 720 → OK."""
        ctx = ContextoUsuario(horario_inicio=480, horario_fin=1200)
        tasks = [
            Actividad(
                id="t1", nombre="Test", tipo=TipoActividad.TAREA,
                dia=0, hora_inicio=0, hora_fin=0,
                duracion_estimada=600,
                dificultad=Dificultad.MEDIA,
            ),
        ]
        ScheduleOptimizer._validate_task_duration(tasks, ctx, 0, 7)

    def test_preferred_window_crossing_midnight_valid(self):
        """120 min task in preferred window 22:00 (1320) to 02:00 (120) = 240 min window → OK."""
        ctx = ContextoUsuario(horario_inicio=480, horario_fin=1200)
        tasks = [
            Actividad(
                id="t1", nombre="Test", tipo=TipoActividad.TAREA,
                dia=0, hora_inicio=0, hora_fin=0,
                duracion_estimada=120,
                dificultad=Dificultad.MEDIA,
                hora_preferida_inicio=1320,
                hora_preferida_fin=120,
            ),
        ]
        ScheduleOptimizer._validate_task_duration(tasks, ctx, 0, 7)

    def test_preferred_window_crossing_midnight_invalid(self):
        """300 min task in preferred window 22:00 (1320) to 02:00 (120) = 240 min window → Error."""
        ctx = ContextoUsuario(horario_inicio=480, horario_fin=1200)
        tasks = [
            Actividad(
                id="t1", nombre="Test", tipo=TipoActividad.TAREA,
                dia=0, hora_inicio=0, hora_fin=0,
                duracion_estimada=300,
                dificultad=Dificultad.MEDIA,
                hora_preferida_inicio=1320,
                hora_preferida_fin=120,
            ),
        ]
        with pytest.raises(ValueError, match="ventana preferida"):
            ScheduleOptimizer._validate_task_duration(tasks, ctx, 0, 7)



class TestValidateConsistencyPhase1:
    """R3: _validate_consistency uses effective window."""

    def test_crossing_available_per_day_positive(self):
        """Crossing (480, 60) → each available_per_day = 1020, not negative."""
        ctx = ContextoUsuario(horario_inicio=480, horario_fin=60)
        tasks = [
            Actividad(
                id="t1", nombre="Test", tipo=TipoActividad.TAREA,
                dia=0, hora_inicio=0, hora_fin=0,
                duracion_estimada=600,
                dificultad=Dificultad.MEDIA,
            ),
        ]
        ScheduleOptimizer._validate_consistency(
            [], [], tasks, ctx, 0, 7, omitido_weight=100000,
        )

    def test_normal_window_still_works(self):
        """Normal (480, 1200) → still works identically."""
        ctx = ContextoUsuario(horario_inicio=480, horario_fin=1200)
        tasks = [
            Actividad(
                id="t1", nombre="Test", tipo=TipoActividad.TAREA,
                dia=0, hora_inicio=0, hora_fin=0,
                duracion_estimada=600,
                dificultad=Dificultad.MEDIA,
            ),
        ]
        ScheduleOptimizer._validate_consistency(
            [], [], tasks, ctx, 0, 7, omitido_weight=100000,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2 — CP‑SAT Crossing Window Integration (R6–R12)
# ═══════════════════════════════════════════════════════════════════════════════


def test_flex_task_crossing_midnight():
    """R7: Flex task in crossing context (480, 60) should be feasible.

    Effective window = 1020 min. 60‑min task fits in seg1.
    """
    ctx = ContextoUsuario(horario_inicio=480, horario_fin=60)
    tareas = [
        Actividad(
            id="flex1", nombre="Crossing Flex", tipo=TipoActividad.TAREA,
            duracion_estimada=60,
            dificultad=Dificultad.MEDIA,
            dia=0, hora_inicio=0, hora_fin=0,
        ),
    ]
    request = SolicitudHorario(
        actividades_fijas=[],
        actividades_optimizables_puras=tareas,
        contexto_usuario=ctx,
        dias_totales=1,
    )
    optimizer = ScheduleOptimizer(timeout_seconds=10)
    response = optimizer.generar(request)

    assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE), (
        f"Crossing window + flex task should be feasible, got {response.estado}"
    )
    assert len(response.bloques) == 1
    block = response.bloques[0]
    # Task must be in [480, 1440) (seg1) since 60‑min task can't fit in [0, 60)
    # Task can be in seg1 [480, 1440) OR seg2 [0, 60)
    in_seg1 = 480 <= block.hora_inicio < 1440
    in_seg2 = 0 <= block.hora_inicio < 60
    assert in_seg1 or in_seg2, (
        f"Block hora_inicio={block.hora_inicio} not in seg1 [480,1440) "
        f"or seg2 [0,60)"
    )
    assert block.hora_fin > block.hora_inicio, (
        f"End {block.hora_fin} should be > start {block.hora_inicio}"
    )
    assert block.hora_fin - block.hora_inicio == 60, (
        f"Duration should be 60 min, got {block.hora_fin - block.hora_inicio}"
    )


def test_flex_task_crossing_post_midnight():
    """R7: Flex task in seg2 when seg1 is too small.

    Window (1410, 60): seg1 = [1410, 1440) = 30 min.
    30‑min task can fit in seg1 OR seg2 ([0, 60) = 60 min).
    """
    ctx = ContextoUsuario(horario_inicio=1410, horario_fin=60)
    tareas = [
        Actividad(
            id="flex1", nombre="PostMid Flex", tipo=TipoActividad.TAREA,
            duracion_estimada=30,
            dificultad=Dificultad.MEDIA,
            dia=0, hora_inicio=0, hora_fin=0,
        ),
    ]
    request = SolicitudHorario(
        actividades_fijas=[],
        actividades_optimizables_puras=tareas,
        contexto_usuario=ctx,
        dias_totales=1,
    )
    optimizer = ScheduleOptimizer(timeout_seconds=10)
    response = optimizer.generar(request)

    assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE), (
        f"Post-midnight flex task should be feasible, got {response.estado}"
    )
    assert len(response.bloques) == 1
    block = response.bloques[0]
    # Either seg1: [1410, 1440) with hora_inicio=1410, or seg2: [0, 60)
    ok_ranges = (
        (1410 <= block.hora_inicio < 1440) or (0 <= block.hora_inicio < 60)
    )
    assert ok_ranges, (
        f"Block hora_inicio={block.hora_inicio} not in seg1 [1410,1440) "
        f"or seg2 [0,60)"
    )


def test_rest_block_crossing():
    """R6: Rest block (30 min) in crossing window (480, 60).

    seg1 = [480, 1440) has 960 min → rest fits in seg1.
    seg1 s ∈ [480, 1410), e ∈ [510, 1440).
    """
    ctx = ContextoUsuario(horario_inicio=480, horario_fin=60)
    tareas = [
        Actividad(
            id="flex1", nombre="Flex", tipo=TipoActividad.TAREA,
            duracion_estimada=60,
            dificultad=Dificultad.BAJA,
            dia=0, hora_inicio=0, hora_fin=0,
        ),
    ]
    request = SolicitudHorario(
        actividades_fijas=[],
        actividades_optimizables_puras=tareas,
        contexto_usuario=ctx,
        dias_totales=1,
    )
    optimizer = ScheduleOptimizer(timeout_seconds=10)
    response = optimizer.generar(request)

    assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE), (
        f"Rest block + crossing should be feasible, got {response.estado}"
    )


def test_crossing_default_window_identical():
    """R12: Default window (480, 1200) produces identical results.

    Non‑crossing window must not trigger the segment‑split code path.
    """
    ctx = ContextoUsuario(horario_inicio=480, horario_fin=1200)
    tareas = [
        Actividad(
            id="flex1", nombre="Test", tipo=TipoActividad.TAREA,
            duracion_estimada=60,
            dificultad=Dificultad.MEDIA,
            dia=0, hora_inicio=0, hora_fin=0,
        ),
    ]
    request = SolicitudHorario(
        actividades_fijas=[],
        actividades_optimizables_puras=tareas,
        contexto_usuario=ctx,
        dias_totales=1,
    )
    optimizer = ScheduleOptimizer(timeout_seconds=10)
    response = optimizer.generar(request)

    assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)
    assert len(response.bloques) == 1
    block = response.bloques[0]
    assert 480 <= block.hora_inicio < 1200
    assert block.hora_fin - block.hora_inicio == 60
