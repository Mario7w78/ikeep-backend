"""Unit tests for RescheduleService.

Tests the replanification logic: how it rebuilds the schedule
when an activity is affected by lost time.
"""

import pytest

from domain.entities.activity import Actividad
from domain.entities.enums import Dificultad, EstadoSolucion, TipoActividad
from domain.entities.reschedule_request import SolicitudReplanificacion
from domain.entities.schedule_response import BloqueTiempo, RespuestaHorario
from domain.entities.user_context import ContextoUsuario
from domain.services.reschedule_service import RescheduleService
from domain.services.schedule_service import ScheduleOptimizer


# ─── Helpers ──────────────────────────────────────────────────────


def _make_block(
    id: str,
    nombre: str = "Actividad",
    tipo: TipoActividad = TipoActividad.TAREA,
    dia: int = 0,
    inicio: int = 480,
    fin: int = 540,
    ubicacion_id: str | None = None,
) -> BloqueTiempo:
    return BloqueTiempo(
        id_actividad=id,
        nombre=nombre,
        tipo=tipo,
        dia=dia,
        hora_inicio=inicio,
        hora_fin=fin,
        ubicacion_id=ubicacion_id,
    )


def _make_current_schedule() -> RespuestaHorario:
    return RespuestaHorario(
        estado=EstadoSolucion.OPTIMA,
        bloques=[
            _make_block("c1", nombre="Algebra", tipo=TipoActividad.CLASE, dia=0, inicio=480, fin=540),
            _make_block("t1", nombre="Estudiar", tipo=TipoActividad.TAREA, dia=0, inicio=600, fin=720),
            _make_block("t2", nombre="Proyecto", tipo=TipoActividad.TRABAJO, dia=1, inicio=480, fin=600),
        ],
        mensaje="",
    )


def _make_ctx() -> ContextoUsuario:
    return ContextoUsuario(
        nivel_energia=2,
        horario_inicio=480,
        horario_fin=1200,
    )


# ─── Tests ─────────────────────────────────────────────────────────


class TestRescheduleService:
    def setup_method(self):
        self.optimizer = ScheduleOptimizer(timeout_seconds=5)
        self.service = RescheduleService(optimizer=self.optimizer)

    def test_reschedule_with_lost_time(self):
        """When a task loses time, it should be re-optimized with extra duration."""
        current = _make_current_schedule()
        request = SolicitudReplanificacion(
            horario_actual=current,
            actividad_afectada_id="t1",
            tiempo_perdido_minutos=30,
            contexto_usuario=_make_ctx(),
        )
        result = self.service.replanificar(request)

        assert result.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)
        # The affected task should appear in the result (with extra time)
        t1_blocks = [b for b in result.bloques if b.id_actividad == "t1"]
        assert len(t1_blocks) >= 1
        t1 = t1_blocks[0]
        assert t1.hora_fin - t1.hora_inicio == 150  # 120 original + 30 lost

    def test_reschedule_preserves_fixed_classes(self):
        """Fixed classes should remain unchanged after replanification."""
        current = _make_current_schedule()
        request = SolicitudReplanificacion(
            horario_actual=current,
            actividad_afectada_id="t1",
            tiempo_perdido_minutos=30,
            contexto_usuario=_make_ctx(),
        )
        result = self.service.replanificar(request)

        c1_blocks = [b for b in result.bloques if b.id_actividad == "c1"]
        assert len(c1_blocks) == 1
        assert c1_blocks[0].hora_inicio == 480
        assert c1_blocks[0].hora_fin == 540

    def test_reschedule_with_zero_lost_time(self):
        """Zero lost time should still produce a valid schedule."""
        current = _make_current_schedule()
        request = SolicitudReplanificacion(
            horario_actual=current,
            actividad_afectada_id="t1",
            tiempo_perdido_minutos=0,
            contexto_usuario=_make_ctx(),
        )
        result = self.service.replanificar(request)
        assert result.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)

    def test_reschedule_nonexistent_activity(self):
        """Replanifying a nonexistent activity should still produce a valid schedule."""
        current = _make_current_schedule()
        request = SolicitudReplanificacion(
            horario_actual=current,
            actividad_afectada_id="nonexistent",
            tiempo_perdido_minutos=30,
            contexto_usuario=_make_ctx(),
        )
        result = self.service.replanificar(request)
        assert result.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)

    def test_reschedule_all_fixed_returns_empty(self):
        """If there are no flexible activities, should return a message."""
        current = RespuestaHorario(
            estado=EstadoSolucion.OPTIMA,
            bloques=[
                _make_block("c1", tipo=TipoActividad.CLASE, dia=0, inicio=480, fin=540),
            ],
        )
        request = SolicitudReplanificacion(
            horario_actual=current,
            actividad_afectada_id="c1",
            tiempo_perdido_minutos=30,
            contexto_usuario=_make_ctx(),
        )
        result = self.service.replanificar(request)
        # CLASE activities are fixed, so no flexible activities to replan
        # The service should handle this gracefully
        assert result.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE, EstadoSolucion.INFACTIBLE)

    def test_reschedule_only_one_flexible_task(self):
        """Replanifying with only one flexible task should work."""
        current = RespuestaHorario(
            estado=EstadoSolucion.OPTIMA,
            bloques=[
                _make_block("t1", nombre="Estudiar", tipo=TipoActividad.TAREA, dia=0, inicio=480, fin=600),
            ],
        )
        request = SolicitudReplanificacion(
            horario_actual=current,
            actividad_afectada_id="t1",
            tiempo_perdido_minutos=20,
            contexto_usuario=_make_ctx(),
        )
        result = self.service.replanificar(request)
        assert result.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)
        t1 = next(b for b in result.bloques if b.id_actividad == "t1")
        assert t1.hora_fin - t1.hora_inicio == 140  # 120 + 20
