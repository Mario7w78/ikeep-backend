from abc import ABC, abstractmethod

from domain.entities.reschedule_request import SolicitudReplanificacion
from domain.entities.schedule_response import RespuestaHorario


class AbstractRescheduleService(ABC):

    @abstractmethod
    def replanificar(self, request: SolicitudReplanificacion) -> RespuestaHorario:
        pass
