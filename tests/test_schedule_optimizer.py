"""Integration tests for ScheduleOptimizer — full generar() flow.

Tests the complete scheduling pipeline: input validation, CP-SAT model
building, solving, and response construction.
"""

import pytest

from domain.entities.activity import Actividad
from domain.entities.enums import Dificultad, EstadoSolucion, TipoActividad
from domain.entities.schedule_request import SolicitudHorario
from domain.entities.user_context import BloqueSueno, ContextoUsuario, RegistroEnergia
from domain.services.schedule_service import PenaltyWeights, ScheduleOptimizer


# ─── Helpers ──────────────────────────────────────────────────────


def _make_task(
    id: str,
    nombre: str = "Tarea",
    tipo: TipoActividad = TipoActividad.TAREA,
    dia: int = 0,
    duracion: int = 60,
    dificultad: Dificultad = Dificultad.MEDIA,
    prioridad: int = 1,
    hora_inicio: int = 0,
    hora_fin: int = 0,
    ubicacion_id: str | None = None,
) -> Actividad:
    if hora_inicio == 0 and hora_fin == 0:
        hora_inicio = 480  # 08:00
        hora_fin = hora_inicio + duracion
    return Actividad(
        id=id,
        nombre=nombre,
        tipo=tipo,
        dia=dia,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        ubicacion_id=ubicacion_id,
        prioridad=prioridad,
        duracion_estimada=duracion,
        dificultad=dificultad,
    )


def _make_ctx(
    nivel_energia: int = 2,
    horario_inicio: int = 480,
    horario_fin: int = 1200,
    bloques_sueno: list[BloqueSueno] | None = None,
    historial: list[RegistroEnergia] | None = None,
) -> ContextoUsuario:
    return ContextoUsuario(
        nivel_energia=nivel_energia,
        horario_inicio=horario_inicio,
        horario_fin=horario_fin,
        bloques_sueno=bloques_sueno or [],
        historial_energia=historial or [],
    )


# ─── Basic scheduling ─────────────────────────────────────────────


class TestBasicScheduling:
    def test_single_task_scheduled(self):
        """A single flexible task should be scheduled somewhere."""
        task = _make_task("t1", duracion=60)
        solicitud = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=[task],
            contexto_usuario=_make_ctx(),
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        result = optimizer.generar(solicitud)

        assert result.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)
        assert len(result.bloques) >= 1
        assert any(b.id_actividad == "t1" for b in result.bloques)

    def test_multiple_tasks_no_overlap(self):
        """Multiple tasks should not overlap in time."""
        tasks = [
            _make_task("t1", duracion=60),
            _make_task("t2", duracion=90),
            _make_task("t3", duracion=45),
        ]
        solicitud = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tasks,
            contexto_usuario=_make_ctx(),
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        result = optimizer.generar(solicitud)

        assert result.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)
        # Check no overlaps on same day
        day_blocks: dict[int, list] = {}
        for b in result.bloques:
            day_blocks.setdefault(b.dia, []).append(b)
        for dia, blocks in day_blocks.items():
            blocks.sort(key=lambda x: x.hora_inicio)
            for i in range(len(blocks) - 1):
                assert blocks[i].hora_fin <= blocks[i + 1].hora_inicio, (
                    f"Overlap on day {dia}: {blocks[i].nombre} ends {blocks[i].hora_fin} "
                    f"but {blocks[i+1].nombre} starts {blocks[i+1].hora_inicio}"
                )

    def test_fixed_activities_preserved(self):
        """Fixed activities (CLASE) must appear in the result unchanged."""
        fixed = _make_task(
            "c1", nombre="Algebra", tipo=TipoActividad.CLASE,
            dia=0, hora_inicio=480, hora_fin=540, duracion=60,
        )
        task = _make_task("t1", duracion=60)
        solicitud = SolicitudHorario(
            actividades_fijas=[fixed],
            actividades_optimizables=[task],
            contexto_usuario=_make_ctx(),
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        result = optimizer.generar(solicitud)

        fixed_block = next((b for b in result.bloques if b.id_actividad == "c1"), None)
        assert fixed_block is not None
        assert fixed_block.hora_inicio == 480
        assert fixed_block.hora_fin == 540
        assert fixed_block.tipo == TipoActividad.CLASE


# ─── Validation ────────────────────────────────────────────────────


class TestValidation:
    def test_overlapping_fixed_activities_raises(self):
        """Two fixed activities that overlap should raise ValueError."""
        a1 = _make_task("c1", tipo=TipoActividad.CLASE, dia=0, hora_inicio=480, hora_fin=540, duracion=60)
        a2 = _make_task("c2", tipo=TipoActividad.CLASE, dia=0, hora_inicio=510, hora_fin=570, duracion=60)
        solicitud = SolicitudHorario(
            actividades_fijas=[a1, a2],
            actividades_optimizables=[],
            contexto_usuario=_make_ctx(),
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        with pytest.raises(ValueError, match="solapadas"):
            optimizer.generar(solicitud)

    def test_task_longer_than_day_raises(self):
        """A task exceeding the available daily window should raise ValueError."""
        task = _make_task("t1", duracion=800)  # 800 min > 720 available
        solicitud = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=[task],
            contexto_usuario=_make_ctx(horario_inicio=480, horario_fin=1200),
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        with pytest.raises(ValueError, match="dura 800 min"):
            optimizer.generar(solicitud)


# ─── Energy pattern behavior ──────────────────────────────────────


class TestEnergyPatterns:
    def _history(self, low_ratio: float, count: int = 14) -> list[RegistroEnergia]:
        from datetime import datetime, timedelta, timezone

        low_count = int(count * low_ratio)
        high_count = count - low_count
        now = datetime.now(timezone.utc)
        result = []
        for i in range(low_count):
            ts = (now - timedelta(days=i)).isoformat()
            result.append(RegistroEnergia(timestamp=ts, nivel=1, dia_semana=i % 7))
        for i in range(high_count):
            ts = (now - timedelta(days=low_count + i)).isoformat()
            result.append(RegistroEnergia(timestamp=ts, nivel=3, dia_semana=i % 7))
        return result

    def test_transcriptorio_solves_normally(self):
        """TRANSCRIPTORIO (< 20% low energy) should solve without extra constraints."""
        solicitud = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=[_make_task("t1", duracion=60)],
            contexto_usuario=_make_ctx(
                nivel_energia=3,
                historial=self._history(0.1),
            ),
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        result = optimizer.generar(solicitud)
        assert result.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)

    def test_tendencia_limits_alta_per_day(self):
        """TENDENCIA (20-60% low) enforces max 1 ALTA per day."""
        tasks = [
            _make_task(f"t{i}", duracion=30, dificultad=Dificultad.ALTA)
            for i in range(3)
        ]
        # Give each task multiple days so the constraint can be satisfied
        for t in tasks:
            t.dia = 6  # deadline: can be scheduled on days 0-6
        solicitud = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tasks,
            contexto_usuario=_make_ctx(
                nivel_energia=1,
                historial=self._history(0.4),
            ),
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        result = optimizer.generar(solicitud)

        assert result.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)
        # Check max 1 ALTA per day
        day_alta: dict[int, int] = {}
        for b in result.bloques:
            if any(t.id == b.id_actividad and t.dificultad == Dificultad.ALTA for t in tasks):
                day_alta[b.dia] = day_alta.get(b.dia, 0) + 1
        for dia, count in day_alta.items():
            assert count <= 1, f"TENDENCIA: {count} ALTA tasks on day {dia}"

    def test_cronico_solves_with_high_energy_tasks(self):
        """CRONICO (> 60% low) should still find a solution."""
        tasks = [
            _make_task("t1", duracion=60, dificultad=Dificultad.ALTA),
            _make_task("t2", duracion=45, dificultad=Dificultad.BAJA),
        ]
        solicitud = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=tasks,
            contexto_usuario=_make_ctx(
                nivel_energia=1,
                historial=self._history(0.8),
            ),
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        result = optimizer.generar(solicitud)
        assert result.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)


# ─── Sleep blocks ──────────────────────────────────────────────────


class TestSleepBlocks:
    def test_tasks_dont_overlap_sleep(self):
        """No task should be scheduled during sleep blocks."""
        sleep = BloqueSueno(dia=0, inicio=0, fin=420)  # 00:00–07:00
        task = _make_task("t1", duracion=60)
        solicitud = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=[task],
            contexto_usuario=_make_ctx(bloques_sueno=[sleep]),
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        result = optimizer.generar(solicitud)

        for b in result.bloques:
            if b.dia == 0 and b.id_actividad == "t1":
                assert b.hora_inicio >= 420, (
                    f"Task scheduled during sleep: starts at {b.hora_inicio}, sleep ends at 420"
                )


# ─── Travel constraints ────────────────────────────────────────────


class TestTravelConstraints:
    def test_tasks_at_different_locations_get_travel_time(self):
        """Tasks at different locations should have travel blocks inserted."""
        from domain.entities.location import Ubicacion
        from domain.entities.travel_time import TiempoTraslado

        loc1 = Ubicacion(id="loc1", nombre="Casa", latitud=-34.6, longitud=-58.4)
        loc2 = Ubicacion(id="loc2", nombre="Trabajo", latitud=-34.5, longitud=-58.3)

        fixed = _make_task(
            "c1", tipo=TipoActividad.CLASE, dia=0,
            hora_inicio=480, hora_fin=540, duracion=60, ubicacion_id="loc1",
        )
        task = _make_task(
            "t1", duracion=60, dia=0, ubicacion_id="loc2",
        )

        solicitud = SolicitudHorario(
            actividades_fijas=[fixed],
            actividades_optimizables=[task],
            ubicaciones=[loc1, loc2],
            tiempos_traslado=[TiempoTraslado(origen_id="loc1", destino_id="loc2", tiempo_estimado_minutos=15)],
            contexto_usuario=_make_ctx(),
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        result = optimizer.generar(solicitud)

        # Should have at least the task + a travel block
        travel_blocks = [b for b in result.bloques if b.id_actividad.startswith("viaje_")]
        assert len(travel_blocks) >= 1


# ─── Edge cases ────────────────────────────────────────────────────


class TestEdgeCases:
    def test_no_flexible_tasks(self):
        """With only fixed activities, should return them as-is."""
        fixed = _make_task("c1", tipo=TipoActividad.CLASE, dia=0, hora_inicio=480, hora_fin=540, duracion=60)
        solicitud = SolicitudHorario(
            actividades_fijas=[fixed],
            actividades_optimizables=[],
            contexto_usuario=_make_ctx(),
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        result = optimizer.generar(solicitud)
        assert result.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)
        assert len(result.bloques) == 1
        assert result.bloques[0].id_actividad == "c1"

    def test_empty_request(self):
        """Empty request should return OPTIMAL with no blocks."""
        solicitud = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=[],
            contexto_usuario=_make_ctx(),
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5)
        result = optimizer.generar(solicitud)
        assert result.estado == EstadoSolucion.OPTIMA
        assert result.bloques == []

    def test_custom_penalty_weights(self):
        """Custom weights should be accepted without errors."""
        weights = PenaltyWeights(rb_01=20, rb_02=15, rb_03=0)
        solicitud = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables=[_make_task("t1", duracion=60)],
            contexto_usuario=_make_ctx(),
        )
        optimizer = ScheduleOptimizer(timeout_seconds=5, weights=weights)
        result = optimizer.generar(solicitud)
        assert result.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)
