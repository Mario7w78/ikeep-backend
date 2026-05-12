from abc import ABC, abstractmethod

from domain.entities.schedule_request import SolicitudHorario
from domain.entities.schedule_response import RespuestaHorario


class AbstractSchedulerService(ABC):

    @abstractmethod
    def generar(self, solicitud: SolicitudHorario) -> RespuestaHorario:
        pass
