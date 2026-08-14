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
    es_fija: bool | None = False,
) -> BloqueTiempo:
    return BloqueTiempo(
        id_actividad=id,
        nombre=nombre,
        tipo=tipo,
        dia=dia,
        hora_inicio=inicio,
        hora_fin=fin,
        ubicacion_id=ubicacion_id,
        es_fija=es_fija,
    )


def _make_current_schedule() -> RespuestaHorario:
    return RespuestaHorario(
        estado=EstadoSolucion.OPTIMA,
        bloques=[
            # Fija porque tiene hora clavada, no porque se llame clase.
            _make_block("c1", nombre="Algebra", tipo=TipoActividad.CLASE, dia=0, inicio=480, fin=540, es_fija=True),
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
        """Lo que tiene hora clavada no se mueve al replanificar."""
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
                _make_block("c1", tipo=TipoActividad.CLASE, dia=0, inicio=480, fin=540, es_fija=True),
            ],
        )
        request = SolicitudReplanificacion(
            horario_actual=current,
            actividad_afectada_id="c1",
            tiempo_perdido_minutos=30,
            contexto_usuario=_make_ctx(),
        )
        result = self.service.replanificar(request)
        # Todo esta clavado: no queda nada que el solver pueda reubicar.
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


class TestQueSePuedeMover:
    """Fijo es una propiedad del horario, no del rotulo.

    El replanificador preguntaba `b.tipo == TipoActividad.CLASE`. Un turno de
    trabajo de 9 a 5 es tan inamovible como una clase, pero caia en el `else`
    y el solver se lo reubicaba al usuario. No era un descuido: es lo que pasa
    cuando se pregunta "que es?" en lugar de "se puede mover?".
    """

    def setup_method(self):
        self.service = RescheduleService(optimizer=ScheduleOptimizer(timeout_seconds=5))

    def _replanificar(self, bloques, afectada, perdidos=30):
        return self.service.replanificar(
            SolicitudReplanificacion(
                horario_actual=RespuestaHorario(
                    estado=EstadoSolucion.OPTIMA, bloques=bloques
                ),
                actividad_afectada_id=afectada,
                tiempo_perdido_minutos=perdidos,
                contexto_usuario=_make_ctx(),
            )
        )

    def test_un_trabajo_con_hora_fija_no_se_mueve(self):
        resultado = self._replanificar(
            [
                _make_block("w1", nombre="Turno", tipo=TipoActividad.TRABAJO,
                            dia=0, inicio=540, fin=1020, es_fija=True),
                _make_block("t1", nombre="Estudiar", tipo=TipoActividad.TAREA,
                            dia=0, inicio=1080, fin=1200),
            ],
            afectada="t1",
        )

        turno = [b for b in resultado.bloques if b.id_actividad == "w1"]
        assert len(turno) == 1
        assert (turno[0].hora_inicio, turno[0].hora_fin) == (540, 1020)

    def test_una_clase_flexible_si_se_mueve(self):
        """El reves tambien: el rotulo no vuelve fija a una actividad.

        Alguien puede tener "Ingles" como clase que estudia cuando puede. Antes
        quedaba clavada solo por llamarse clase.
        """
        resultado = self._replanificar(
            [
                _make_block("c1", nombre="Ingles", tipo=TipoActividad.CLASE,
                            dia=0, inicio=480, fin=600, es_fija=False),
                _make_block("t1", nombre="Estudiar", tipo=TipoActividad.TAREA,
                            dia=0, inicio=480, fin=600),
            ],
            afectada="t1",
        )

        assert any(b.id_actividad == "c1" for b in resultado.bloques)
        assert resultado.mensaje != "Sin actividades optimizables por replanificar."

    def test_la_fijeza_sobrevive_al_viaje_de_ida_y_vuelta(self):
        """El cliente devuelve el horario al replanificar.

        Si `es_fija` no viaja en el DTO se pierde en el camino y el bug vuelve
        en produccion aunque el dominio este bien.
        """
        from schemas.schedule_response import BloqueTiempo as BloqueDto

        assert "es_fija" in BloqueDto.model_fields

    def test_un_bloque_sin_el_campo_usa_la_regla_vieja(self):
        """Compatibilidad con horarios ya guardados en el telefono.

        `es_fija=None` significa "generado antes de que el campo existiera",
        no "se puede mover". Sin esta distincion, alguien que no toco nada
        abriria la app y encontraria sus clases reubicadas.

        Se puede borrar cuando ningun cliente pueda tener horarios viejos:
        basta con que la app regenere al arrancar tras la actualizacion.
        """
        resultado = self._replanificar(
            [
                _make_block("c1", nombre="Algebra", tipo=TipoActividad.CLASE,
                            dia=0, inicio=480, fin=540, es_fija=None),
                _make_block("t1", nombre="Estudiar", tipo=TipoActividad.TAREA,
                            dia=0, inicio=600, fin=720, es_fija=None),
            ],
            afectada="t1",
        )

        clase = [b for b in resultado.bloques if b.id_actividad == "c1"]
        assert len(clase) == 1
        assert (clase[0].hora_inicio, clase[0].hora_fin) == (480, 540)
