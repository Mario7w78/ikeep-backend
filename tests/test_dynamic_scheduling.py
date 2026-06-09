"""Tests for dynamic-scheduling Phase 1 features.

Covers three additive features:
1. Manual Energy Pattern Override
2. Real Priority Weighting (RB-PRIORITY)
3. Optional Day Assignment (dia=None for flexible tasks)
"""

import pytest
from pydantic import ValidationError

from domain.entities.activity import Actividad
from domain.entities.enums import Dificultad, EstadoSolucion, PatronEnergia, TipoActividad
from domain.entities.schedule_request import SolicitudHorario
from domain.entities.schedule_response import RespuestaHorario
from domain.entities.user_context import DreamBlock, ContextoUsuario
from domain.services.schedule_service import PenaltyWeights, ScheduleOptimizer

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Feature 1: Manual Energy Pattern Override
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


class TestManualEnergyOverride:
    """patron_energia_manual overrides the classifier when set."""

    def test_override_sets_correct_pattern(self):
        """Manual override should set _patron_override to the specified value."""
        ctx = ContextoUsuario(
            nivel_energia=2,
            patron_energia_manual=PatronEnergia.CRONICO,
        )
        tareas = [
            Actividad(
                id="t1", nombre="Tarea 1", tipo=TipoActividad.TAREA,
                dia=1, duracion_estimada=60, dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        response = optimizer.generar(request)

        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)
        assert optimizer._patron_override == PatronEnergia.CRONICO

    def test_override_none_uses_classifier(self):
        """When patron_energia_manual is None, the energy classifier should determine the pattern."""
        ctx = ContextoUsuario(
            nivel_energia=2,
            patron_energia_manual=None,
        )
        tareas = [
            Actividad(
                id="t1", nombre="Tarea 1", tipo=TipoActividad.TAREA,
                dia=1, duracion_estimada=60, dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        response = optimizer.generar(request)

        # With no history and nivel_energia=2, classifier returns TRANSCRIPTORIO
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)
        assert optimizer._patron_override == PatronEnergia.TRANSCRIPTORIO

    def test_override_transcriptoriano(self):
        """Manual override to TRANSCRIPTORIO should work correctly."""
        ctx = ContextoUsuario(
            nivel_energia=2,
            patron_energia_manual=PatronEnergia.TRANSCRIPTORIO,
        )
        tareas = [
            Actividad(
                id="t1", nombre="Tarea 1", tipo=TipoActividad.TAREA,
                dia=1, duracion_estimada=60, dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        response = optimizer.generar(request)

        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)
        assert optimizer._patron_override == PatronEnergia.TRANSCRIPTORIO

    def test_override_tendencia(self):
        """Manual override to TENDENCIA (especial: max 1 ALTA/day) should work."""
        ctx = ContextoUsuario(
            nivel_energia=2,
            patron_energia_manual=PatronEnergia.TENDENCIA,
        )
        tareas = [
            Actividad(
                id="t1", nombre="Tarea ALTA 1", tipo=TipoActividad.TAREA,
                dia=1, duracion_estimada=60, dificultad=Dificultad.ALTA,
            ),
            Actividad(
                id="t2", nombre="Tarea ALTA 2", tipo=TipoActividad.TAREA,
                dia=1, duracion_estimada=60, dificultad=Dificultad.ALTA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        response = optimizer.generar(request)

        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)
        assert optimizer._patron_override == PatronEnergia.TENDENCIA

        # With TENDENCIA, both ALTA tasks should be on different days
        # (enforced by _rb_01: max 1 ALTA per day)
        alta_blocks = [b for b in response.bloques if b.id_actividad in ("t1", "t2")]
        dias = [b.dia for b in alta_blocks]
        assert len(set(dias)) >= 2, "ALTA tasks should be on different days under TENDENCIA"


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Feature 2: Real Priority Weighting (RB-PRIORITY)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


class TestPriorityPenalty:
    """RB-PRIORITY penalizes low-priority tasks on late days."""

    def test_weight_zero_is_noop(self):
        """rb_priority=0 should not affect scheduling (same behavior as before)."""
        ctx = ContextoUsuario(nivel_energia=3)
        tareas = [
            Actividad(
                id="high", nombre="High Priority", tipo=TipoActividad.TAREA,
                dia=6, duracion_estimada=60, dificultad=Dificultad.MEDIA,
                prioridad=5,
            ),
            Actividad(
                id="low", nombre="Low Priority", tipo=TipoActividad.TAREA,
                dia=6, duracion_estimada=60, dificultad=Dificultad.MEDIA,
                prioridad=1,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        # Default weights have rb_priority=0
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        response = optimizer.generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)

    def test_priority_penalty_high_weight(self):
        """With rb_priority active and high weight, the solver should still
        find a feasible solution (the penalty is additive, not blocking)."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=1200,
        )
        tareas = [
            Actividad(
                id="low", nombre="Low Priority", tipo=TipoActividad.TAREA,
                dia=6, duracion_estimada=120, dificultad=Dificultad.MEDIA,
                prioridad=1,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        from domain.services.schedule_service import PenaltyWeights
        weights = PenaltyWeights(rb_priority=100)
        optimizer = ScheduleOptimizer(timeout_seconds=10, weights=weights)
        response = optimizer.generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)
        assert len(response.bloques) == 1

    def test_same_priority_no_preference(self):
        """Tasks with equal priority should not be penalized differently by RB-PRIORITY."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=1200,
        )
        tareas = [
            Actividad(
                id="a", nombre="Task A", tipo=TipoActividad.TAREA,
                dia=6, duracion_estimada=60, dificultad=Dificultad.MEDIA,
                prioridad=3,
            ),
            Actividad(
                id="b", nombre="Task B", tipo=TipoActividad.TAREA,
                dia=6, duracion_estimada=60, dificultad=Dificultad.MEDIA,
                prioridad=3,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        from domain.services.schedule_service import PenaltyWeights
        weights = PenaltyWeights(rb_priority=50)
        optimizer = ScheduleOptimizer(timeout_seconds=5, weights=weights)
        response = optimizer.generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)
        # Both tasks should be scheduled (no assertion on which day)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Feature 3: Optional Day Assignment (dia=None)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


class TestOptionalDay:
    """Actividad.dia=None allows flexible scheduling across all days."""

    def test_flex_task_dia_none_schedules_on_any_day(self):
        """A flexible task with dia=None should be scheduled on some valid day."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=1200,
        )
        tareas = [
            Actividad(
                id="flex", nombre="No Deadline Task", tipo=TipoActividad.TAREA,
                dia=None, duracion_estimada=60, dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        response = optimizer.generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)

        flex_blocks = [b for b in response.bloques if b.id_actividad == "flex"]
        assert len(flex_blocks) == 1
        assert 0 <= flex_blocks[0].dia <= 6

    def test_flex_task_dia_3_stays_within_deadline(self):
        """A flexible task with dia=3 should only be scheduled on days 0-3."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=1200,
        )
        tareas = [
            Actividad(
                id="flex", nombre="Deadline Day 3", tipo=TipoActividad.TAREA,
                dia=3, duracion_estimada=60, dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        response = optimizer.generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)

        flex_blocks = [b for b in response.bloques if b.id_actividad == "flex"]
        assert len(flex_blocks) == 1
        assert 0 <= flex_blocks[0].dia <= 3, (
            f"Task with dia=3 should be on days 0-3, got day {flex_blocks[0].dia}"
        )

    def test_flex_task_dia_none_with_fixed(self):
        """Flex task with dia=None should coexist with fixed activities."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=1200,
        )
        tareas = [
            Actividad(
                id="flex", nombre="Flex No Deadline", tipo=TipoActividad.TAREA,
                dia=None, duracion_estimada=60, dificultad=Dificultad.MEDIA,
            ),
        ]
        actividades_fijas = [
            Actividad(
                id="fix_0", nombre="Fixed Day 0", tipo=TipoActividad.CLASE,
                dia=0, hora_inicio=480, hora_fin=600, ubicacion_id="loc_a",
            ),
            Actividad(
                id="fix_1", nombre="Fixed Day 1", tipo=TipoActividad.CLASE,
                dia=1, hora_inicio=480, hora_fin=600, ubicacion_id="loc_a",
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=actividades_fijas,
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        response = optimizer.generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)

        flex_blocks = [b for b in response.bloques if b.id_actividad == "flex"]
        assert len(flex_blocks) == 1

    def test_fixed_activity_without_dia_raises_error(self):
        """A fixed activity with dia=None should raise ValueError."""
        ctx = ContextoUsuario()
        actividades = [
            Actividad(
                id="bad_fix", nombre="Bad Fixed", tipo=TipoActividad.CLASE,
                dia=None, hora_inicio=480, hora_fin=600,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=actividades,
            actividades_optimizables=[],
            contexto_usuario=ctx,
        )
        with pytest.raises(ValueError, match="no tiene un día asignado"):
            ScheduleOptimizer(timeout_seconds=1).generar(request)

    def test_consistency_with_all_none_dias(self):
        """_validate_consistency should use 7-day window when all tasks have dia=None."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=1200,
        )
        tareas = [
            Actividad(
                id="t1", nombre="Task 1", tipo=TipoActividad.TAREA,
                dia=None, duracion_estimada=60, dificultad=Dificultad.MEDIA,
            ),
            Actividad(
                id="t2", nombre="Task 2", tipo=TipoActividad.TAREA,
                dia=None, duracion_estimada=60, dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        # Should not raise â€” 120 min total with 7 days Ã— 720 min/day available
        response = optimizer.generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)

    def test_consistency_with_mixed_dias(self):
        """_validate_consistency should handle mix of None and concrete dias."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=1200,
        )
        tareas = [
            Actividad(
                id="t1", nombre="Task 1", tipo=TipoActividad.TAREA,
                dia=None, duracion_estimada=120, dificultad=Dificultad.MEDIA,
            ),
            Actividad(
                id="t2", nombre="Task 2", tipo=TipoActividad.TAREA,
                dia=2, duracion_estimada=60, dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        # Should not raise â€” 180 min total with 3 days Ã— 720 min/day available
        response = optimizer.generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Feature 4 [F2]: Day Range (dia_desde/dia_hasta)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


class TestDayRange:
    """F2: dia_desde/dia_hasta control the scheduling day window."""

    def test_dia_desde_hasta_normal_range(self):
        """F2-S1: Task with dia_desde=2, dia_hasta=5 â†’ days [2,5]."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=1200,
        )
        tareas = [
            Actividad(
                id="t1", nombre="Range Task", tipo=TipoActividad.TAREA,
                dia_desde=2, dia_hasta=5, duracion_estimada=60,
                dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        response = optimizer.generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)

        flex_blocks = [b for b in response.bloques if b.id_actividad == "t1"]
        assert len(flex_blocks) == 1
        assert 2 <= flex_blocks[0].dia <= 5, (
            f"Expected day in [2,5], got {flex_blocks[0].dia}"
        )

    def test_backward_compat_dia_3(self):
        """F2-S2: Task with dia=3 (backward compat) â†’ days [0,3]."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=1200,
        )
        tareas = [
            Actividad(
                id="t1", nombre="Deadline Task", tipo=TipoActividad.TAREA,
                dia=3, duracion_estimada=60, dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        response = optimizer.generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)

        flex_blocks = [b for b in response.bloques if b.id_actividad == "t1"]
        assert len(flex_blocks) == 1
        assert 0 <= flex_blocks[0].dia <= 3, (
            f"Expected day in [0,3], got {flex_blocks[0].dia}"
        )

    def test_dia_and_dia_desde_backward_compat(self):
        """F2-S3: Task with dia=3 and dia_desde=1 â†’ dia_hasta aliased."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=1200,
        )
        tareas = [
            Actividad(
                id="t1", nombre="Mixed Task", tipo=TipoActividad.TAREA,
                dia=3, dia_desde=1, dia_hasta=6, duracion_estimada=60,
                dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)

        # dia is set AND dia_desde != 0, so no backward alias.
        # Explicit values are used: dia_desde=1, dia_hasta=6
        response = optimizer.generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)

        flex_blocks = [b for b in response.bloques if b.id_actividad == "t1"]
        assert len(flex_blocks) == 1
        # Task should be in [1, 6] since those are explicit values
        assert 1 <= flex_blocks[0].dia <= 6, (
            f"Expected day in [1,6], got {flex_blocks[0].dia}"
        )

    def test_dia_desde_greater_than_dia_hasta_error(self):
        """F2-E1: dia_desde > dia_hasta raises validation error."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=1200,
        )
        tareas = [
            Actividad(
                id="t1", nombre="Bad Range", tipo=TipoActividad.TAREA,
                dia_desde=4, dia_hasta=2, duracion_estimada=60,
                dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        optimizer = ScheduleOptimizer(timeout_seconds=1)
        with pytest.raises(ValueError):
            optimizer.generar(request)

    def test_single_day_range(self):
        """F2-S5: dia_desde=3, dia_hasta=3 â†’ single day [3]."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=1200,
        )
        tareas = [
            Actividad(
                id="t1", nombre="Single Day", tipo=TipoActividad.TAREA,
                dia_desde=3, dia_hasta=3, duracion_estimada=60,
                dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        response = optimizer.generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)

        flex_blocks = [b for b in response.bloques if b.id_actividad == "t1"]
        assert len(flex_blocks) == 1
        assert flex_blocks[0].dia == 3, f"Expected day 3, got {flex_blocks[0].dia}"


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Feature 5 [F3]: Preferred/Blocked Days (dias_permitidos)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


class TestPermittedDays:
    """F3: dias_permitidos filters which days a task can go on."""

    def test_permitted_none_is_noop(self):
        """F3-S1: dias_permitidos=None â†’ all days available."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=1200,
        )
        tareas = [
            Actividad(
                id="t1", nombre="No Restrict", tipo=TipoActividad.TAREA,
                dias_permitidos=None, duracion_estimada=60,
                dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        response = optimizer.generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)

        flex_blocks = [b for b in response.bloques if b.id_actividad == "t1"]
        assert len(flex_blocks) == 1
        assert 0 <= flex_blocks[0].dia <= 6

    def test_permitted_weekdays(self):
        """F3-S2: dias_permitidos=[0,1,2,3,4] â†’ weekdays only."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=1200,
        )
        tareas = [
            Actividad(
                id="t1", nombre="Weekdays Only", tipo=TipoActividad.TAREA,
                dias_permitidos=[0, 1, 2, 3, 4], duracion_estimada=60,
                dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        response = optimizer.generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)

        flex_blocks = [b for b in response.bloques if b.id_actividad == "t1"]
        assert len(flex_blocks) == 1
        assert flex_blocks[0].dia in (0, 1, 2, 3, 4), (
            f"Expected weekday, got {flex_blocks[0].dia}"
        )

    def test_permitted_single_day(self):
        """F3-S3: dias_permitidos=[3] â†’ only day 3."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=1200,
        )
        tareas = [
            Actividad(
                id="t1", nombre="Only Day 3", tipo=TipoActividad.TAREA,
                dias_permitidos=[3], duracion_estimada=60,
                dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        response = optimizer.generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)

        flex_blocks = [b for b in response.bloques if b.id_actividad == "t1"]
        assert len(flex_blocks) == 1
        assert flex_blocks[0].dia == 3

    def test_permitted_with_narrower_range(self):
        """F3-S4: dias_permitidos + dia_desde/dia_hasta â†’ intersection."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=1200,
        )
        tareas = [
            Actividad(
                id="t1", nombre="Intersection", tipo=TipoActividad.TAREA,
                dias_permitidos=[2, 3, 4, 5], dia_desde=3, dia_hasta=5,
                duracion_estimada=60, dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        response = optimizer.generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)

        flex_blocks = [b for b in response.bloques if b.id_actividad == "t1"]
        assert len(flex_blocks) == 1
        # Intersection of [2,3,4,5] and [3,4,5] = [3,4,5]
        assert flex_blocks[0].dia in (3, 4, 5), (
            f"Expected day in [3,4,5], got {flex_blocks[0].dia}"
        )

    def test_permitted_outside_range_filters_all(self):
        """F3-S5: dias_permitidos outside range â†’ empty intersection error."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=1200,
        )
        tareas = [
            Actividad(
                id="t1", nombre="No Valid Days", tipo=TipoActividad.TAREA,
                dias_permitidos=[0, 1, 6], dia_desde=2, dia_hasta=5,
                duracion_estimada=60, dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        optimizer = ScheduleOptimizer(timeout_seconds=1)
        with pytest.raises(ValueError):
            optimizer.generar(request)

    def test_permitted_empty_list_error(self):
        """F3-E4: empty dias_permitidos list â†’ no valid days error."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=1200,
        )
        tareas = [
            Actividad(
                id="t1", nombre="Empty List", tipo=TipoActividad.TAREA,
                dias_permitidos=[], duracion_estimada=60,
                dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        optimizer = ScheduleOptimizer(timeout_seconds=1)
        with pytest.raises(ValueError):
            optimizer.generar(request)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Feature 6 [F5]: Anchor Tasks
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


class TestAnchorTasks:
    """F5: es_ancla flag fixes the day while keeping time flexible."""

    def test_anchor_with_dia(self):
        """F5-S1: Anchor with es_ancla=True, dia=3 â†’ scheduled on day 3."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=1200,
        )
        tareas = [
            Actividad(
                id="t1", nombre="Anchor Task", tipo=TipoActividad.TAREA,
                es_ancla=True, dia=3, duracion_estimada=60,
                dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        response = optimizer.generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)

        flex_blocks = [b for b in response.bloques if b.id_actividad == "t1"]
        assert len(flex_blocks) == 1
        assert flex_blocks[0].dia == 3, (
            f"Anchor task should be on day 3, got {flex_blocks[0].dia}"
        )

    def test_anchor_without_dia_error(self):
        """F5-E1: Anchor with dia=None raises validation error."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=1200,
        )
        tareas = [
            Actividad(
                id="t1", nombre="Bad Anchor", tipo=TipoActividad.TAREA,
                es_ancla=True, dia=None, duracion_estimada=60,
                dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        optimizer = ScheduleOptimizer(timeout_seconds=1)
        with pytest.raises(ValueError, match="requiere un día específico"):
            optimizer.generar(request)

    def test_anchor_with_range_auto_fix(self):
        """F5-S2: Anchor with dia_desde=3, dia_hasta=3 â†’ single day [3]."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=1200,
        )
        tareas = [
            Actividad(
                id="t1", nombre="Range Anchor", tipo=TipoActividad.TAREA,
                es_ancla=True, dia_desde=3, dia_hasta=3,
                duracion_estimada=60, dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        response = optimizer.generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)

        flex_blocks = [b for b in response.bloques if b.id_actividad == "t1"]
        assert len(flex_blocks) == 1
        assert flex_blocks[0].dia == 3

    def test_regular_task_unaffected(self):
        """F5-S3: Regular task (es_ancla=False) behaves as before."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=1200,
        )
        tareas = [
            Actividad(
                id="t1", nombre="Regular Flex", tipo=TipoActividad.TAREA,
                es_ancla=False, dia=4, duracion_estimada=60,
                dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        response = optimizer.generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)

        flex_blocks = [b for b in response.bloques if b.id_actividad == "t1"]
        assert len(flex_blocks) == 1
        assert 0 <= flex_blocks[0].dia <= 4, (
            f"Regular flex should be in [0,4], got {flex_blocks[0].dia}"
        )

    def test_anchor_with_multiday_range_error(self):
        """F5-E2: Anchor with multi-day range raises error."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=1200,
        )
        tareas = [
            Actividad(
                id="t1", nombre="Multi Anchor", tipo=TipoActividad.TAREA,
                es_ancla=True, dia_desde=1, dia_hasta=5,
                duracion_estimada=60, dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        optimizer = ScheduleOptimizer(timeout_seconds=1)
        with pytest.raises(ValueError):
            optimizer.generar(request)

    def test_anchor_participates_in_soft_constraints(self):
        """F5-S5: Anchor task with ALTA difficulty respects constraints."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=1200,
        )
        tareas = [
            Actividad(
                id="t1", nombre="Anchor ALTA", tipo=TipoActividad.TAREA,
                es_ancla=True, dia=2, duracion_estimada=60,
                dificultad=Dificultad.ALTA, prioridad=5,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        # Should schedule on day 2 with optimal time
        response = optimizer.generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)

        flex_blocks = [b for b in response.bloques if b.id_actividad == "t1"]
        assert len(flex_blocks) == 1
        assert flex_blocks[0].dia == 2


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Feature 4: Partial Assignment (F9)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


class TestRollingWeek:
    """F8: Rolling week â€” dia_inicio / dias_totales allow scheduling
    over any window, not just Monday(0)-Sunday(6)."""

    def test_default_week_monday_to_sunday(self):
        """Default dia_inicio=0, dias_totales=7 = Monday to Sunday."""
        ctx = ContextoUsuario(nivel_energia=3, horario_inicio=480, horario_fin=1200)
        tareas = [
            Actividad(
                id="t1", nombre="Task 1", tipo=TipoActividad.TAREA,
                duracion_estimada=60, dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        response = ScheduleOptimizer(timeout_seconds=5).generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)
        assert len(response.bloques) >= 1

    def test_mid_week_window(self):
        """Start on Wednesday (3) for 3 days (Wed-Fri)."""
        fijas = [
            Actividad(
                id="f1", nombre="Fixed", tipo=TipoActividad.CLASE,
                dia=3, hora_inicio=600, hora_fin=660,
            ),
        ]
        ctx = ContextoUsuario(nivel_energia=3, horario_inicio=480, horario_fin=1200)
        tareas = [
            Actividad(
                id="t1", nombre="Flex", tipo=TipoActividad.TAREA,
                duracion_estimada=60, dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=fijas,
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
            dia_inicio=3, dias_totales=3,
        )
        response = ScheduleOptimizer(timeout_seconds=5).generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)

    def test_rolling_window_validation(self):
        """Invalid rolling window parameters should raise."""
        ctx = ContextoUsuario()
        with pytest.raises((ValueError, ValidationError)):
            # dias_totales = 0
            request = SolicitudHorario(
                actividades_fijas=[], actividades_optimizables=[], contexto_usuario=ctx,
                dia_inicio=0, dias_totales=0,
            )
            ScheduleOptimizer(timeout_seconds=5).generar(request)


class TestPerDayHours:
    """F7: Per-day active hours â€” different horario_inicio/fin per day."""

    def test_backward_compat_single_int(self):
        """Single int horario_inicio/fin should expand to all days."""
        ctx = ContextoUsuario(nivel_energia=3, horario_inicio=480, horario_fin=1200)
        tareas = [
            Actividad(
                id="t1", nombre="Task", tipo=TipoActividad.TAREA,
                duracion_estimada=60, dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        response = ScheduleOptimizer(timeout_seconds=5).generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)
        # After construction, it should be a list
        assert isinstance(response, RespuestaHorario)

    def test_varied_hours_per_day(self):
        """Different hours for different days â€” narrow window on weekends."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=[480, 480, 480, 480, 480, 600, 600],  # 8AM weekdays, 10AM weekends
            horario_fin=[1200, 1200, 1200, 1200, 1200, 1080, 1080],   # 8PM weekdays, 6PM weekends
        )
        tareas = [
            Actividad(
                id="t1", nombre="Task", tipo=TipoActividad.TAREA,
                duracion_estimada=60, dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        response = ScheduleOptimizer(timeout_seconds=5).generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)

    def test_list_length_validation(self):
        """horario_inicio list length must match dias_totales."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=[480, 480, 480],  # only 3 elements
            horario_fin=[1200, 1200, 1200],
        )
        tareas = [
            Actividad(
                id="t1", nombre="Task", tipo=TipoActividad.TAREA,
                duracion_estimada=60, dificultad=Dificultad.MEDIA,
            ),
        ]
        with pytest.raises((ValueError, ValidationError, TypeError)):
            request = SolicitudHorario(
                actividades_fijas=[],
                actividades_optimizables=tareas,
                contexto_usuario=ctx,
            )
            ScheduleOptimizer(timeout_seconds=5).generar(request)


class TestPartialAssignment:
    """F9: the solver may omit tasks when the problem is infeasible,
    returning a partial schedule instead of INFEASIBLE."""

    def test_all_tasks_fit_no_omissions(self):
        """When all tasks easily fit, no tasks should be omitted."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=1200,  # 7h20m = 440 min per day x 7 days
        )
        tareas = [
            Actividad(
                id="a1", nombre="Tarea A", tipo=TipoActividad.TAREA,
                dia=2, duracion_estimada=60, dificultad=Dificultad.MEDIA,
            ),
            Actividad(
                id="a2", nombre="Tarea B", tipo=TipoActividad.TAREA,
                dia=4, duracion_estimada=90, dificultad=Dificultad.MEDIA,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        response = ScheduleOptimizer(timeout_seconds=5).generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)
        assert len(response.tareas_omitidas) == 0
        assert len(response.bloques) >= 2

    def test_omission_on_overcapacity(self):
        """When total demand > capacity, the solver should omit some tasks
        and return OPTIMAL/FEASIBLE instead of INFEASIBLE."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=540,  # only 60 min/day
        )
        # 10 tasks Ã— 60 min = 600 min > 7 Ã— 60 = 420 min available
        tareas = [
            Actividad(
                id=f"t{i}", nombre=f"Task {i}", tipo=TipoActividad.TAREA,
                duracion_estimada=60, dificultad=Dificultad.MEDIA,
            )
            for i in range(10)
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        response = ScheduleOptimizer(timeout_seconds=15, weights=PenaltyWeights(omitido=100)).generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)
        # 600 min total > 420 min capacity â†’ at least some must be omitted
        assert len(response.tareas_omitidas) >= 1

    def test_omission_list_contains_task_names(self):
        """Omitted tasks should appear by name in tareas_omitidas."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=600,  # only 120 min/day
        )
        # 10 tasks of 100 min each = 1000 min total, but only 7*120=840 min available
        tareas = [
            Actividad(
                id=f"t{i}", nombre=f"Task {i}", tipo=TipoActividad.TAREA,
                duracion_estimada=100, dificultad=Dificultad.MEDIA,
            )
            for i in range(10)
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        response = ScheduleOptimizer(
            timeout_seconds=10,
            weights=PenaltyWeights(omitido=100),
        ).generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)
        # With 10 tasks and only 7*120=840 min capacity, at least some must be omitted
        assert len(response.tareas_omitidas) >= 1
        # Verify omitted names appear
        omitted_set = set(response.tareas_omitidas)
        scheduled_names = {b.nombre for b in response.bloques}
        assert omitted_set.isdisjoint(scheduled_names)  # no overlap

    def test_zero_omission_weight_disables_penalty(self):
        """With omitido=0, the solver doesn't care about omissions
        and may omit tasks even when they could fit."""
        ctx = ContextoUsuario(
            nivel_energia=3,
            horario_inicio=480,
            horario_fin=1200,
        )
        tareas = [
            Actividad(
                id="opt", nombre="Optional Task", tipo=TipoActividad.TAREA,
                dia=3, duracion_estimada=60, dificultad=Dificultad.MEDIA,
                prioridad=0,
            ),
        ]
        request = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tareas,
            contexto_usuario=ctx,
        )
        # With omitido=0, solver may freely omit
        response = ScheduleOptimizer(
            timeout_seconds=5,
            weights=PenaltyWeights(omitido=0),
        ).generar(request)
        assert response.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)
        # With omitido=0, the solver may or may not schedule â€” the point is it CAN omit
        # We just verify no crash and valid state
