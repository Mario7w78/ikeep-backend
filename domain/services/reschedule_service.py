from domain.entities.activity import Actividad
from domain.entities.enums import TipoActividad
from domain.entities.reschedule_request import SolicitudReplanificacion
from domain.entities.schedule_request import SolicitudHorario
from domain.entities.schedule_response import RespuestaHorario
from domain.entities.user_context import ContextoUsuario
from domain.ports.inbound.reschedule_port import AbstractRescheduleService
from domain.ports.inbound.scheduler_port import AbstractSchedulerService


class RescheduleService(AbstractRescheduleService):

    def __init__(self, optimizer: AbstractSchedulerService):
        self.optimizer = optimizer

    def replanificar(self, request: SolicitudReplanificacion) -> RespuestaHorario:
        affected_id = request.actividad_afectada_id
        lost = request.tiempo_perdido_minutos
        ctx = request.contexto_usuario

        affected = next(
            (
                b
                for b in request.horario_actual.bloques
                if b.id_actividad == affected_id
            ),
            None,
        )

        actividades_fijas: list[Actividad] = []
        tareas_pendientes: list[Actividad] = []
        seen_flex: set[str] = set()

        for b in request.horario_actual.bloques:
            if b.tipo == TipoActividad.CLASE:
                if b.id_actividad == affected_id:
                    continue
                actividades_fijas.append(self._to_actividad(b))

            else:
                if b.id_actividad not in seen_flex:
                    seen_flex.add(b.id_actividad)
                    extra = lost if b.id_actividad == affected_id else 0
                    tareas_pendientes.append(self._to_actividad(b, extra))

        if affected and affected.tipo != TipoActividad.CLASE:
            if affected.id_actividad not in seen_flex:
                tareas_pendientes.append(
                    self._to_actividad(affected, lost)
                )

        if not tareas_pendientes:
            return RespuestaHorario(
                estado=request.horario_actual.estado,
                bloques=[b for b in request.horario_actual.bloques if b.id_actividad != affected_id],
                mensaje="Sin tareas pendientes por replanificar.",
            )

        solicitud = SolicitudHorario(
            actividades_fijas=actividades_fijas,
            tareas_pendientes=tareas_pendientes,
            contexto_usuario=ContextoUsuario(
                nivel_energia=ctx.nivel_energia,
                horario_inicio=ctx.horario_inicio,
                horario_fin=ctx.horario_fin,
                bloques_sueno=list(ctx.bloques_sueno),
            ),
        )

        return self.optimizer.generar(solicitud)

    @staticmethod
    def _to_actividad(
        bloque,
        extra_duracion: int = 0,
    ) -> Actividad:
        base_duracion = bloque.hora_fin - bloque.hora_inicio
        return Actividad(
            id=bloque.id_actividad,
            nombre=bloque.nombre,
            tipo=bloque.tipo,
            dia=bloque.dia,
            hora_inicio=bloque.hora_inicio,
            hora_fin=bloque.hora_fin,
            ubicacion_id=bloque.ubicacion_id,
            duracion_estimada=base_duracion + extra_duracion,
        )
