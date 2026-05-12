from sqlalchemy import Column, Enum, Integer, String

from domain.entities.enums import Dificultad, TipoActividad
from infrastructure.adapters.outbound.persistence.database import Base


class ActividadModel(Base):
    __tablename__ = "actividades"

    id = Column(String, primary_key=True)
    nombre = Column(String)
    tipo = Column(Enum(TipoActividad))
    dia = Column(Integer)
    hora_inicio = Column(Integer)
    hora_fin = Column(Integer)
    ubicacion_id = Column(String, nullable=True)
    prioridad = Column(Integer, default=0)
    duracion_estimada = Column(Integer)
    fecha_limite = Column(String, nullable=True)
    dificultad = Column(Enum(Dificultad), default=Dificultad.MEDIA)
