from sqlalchemy.orm import Session

from domain.entities.activity import Actividad
from domain.entities.enums import TipoActividad
from domain.entities.schedule_response import BloqueTiempo
from domain.ports.outbound.actividad_repository_port import ActividadRepositoryPort
from infrastructure.adapters.outbound.persistence.orm_models import ActividadModel


class SQLAlchemyActividadRepository(ActividadRepositoryPort):
    def __init__(self, db: Session):
        self.db = db

    def get_actividades_fijas(self) -> list[Actividad]:
        models = (
            self.db.query(ActividadModel)
            .filter(ActividadModel.tipo == TipoActividad.CLASE)
            .all()
        )
        return [_model_to_domain(m) for m in models]

    def get_tareas_pendientes(self) -> list[Actividad]:
        models = (
            self.db.query(ActividadModel)
            .filter(ActividadModel.tipo.in_([TipoActividad.TRABAJO, TipoActividad.TAREA]))
            .all()
        )
        return [_model_to_domain(m) for m in models]

    def save_resultado(self, bloques: list[BloqueTiempo]) -> None:
        pass


def _model_to_domain(m: ActividadModel) -> Actividad:
    return Actividad(
        id=m.id,
        nombre=m.nombre,
        tipo=m.tipo,
        dia=m.dia,
        hora_inicio=m.hora_inicio,
        hora_fin=m.hora_fin,
        ubicacion_id=m.ubicacion_id,
        prioridad=m.prioridad,
        duracion_estimada=m.duracion_estimada,
        fecha_limite=m.fecha_limite,
        dificultad=m.dificultad,
    )
