from abc import ABC, abstractmethod

from domain.entities.activity import Actividad
from domain.entities.schedule_response import BloqueTiempo


class ActividadRepositoryPort(ABC):

    @abstractmethod
    def get_actividades_fijas(self) -> list[Actividad]:
        pass

    @abstractmethod
    def get_tareas_pendientes(self) -> list[Actividad]:
        pass

    @abstractmethod
    def save_resultado(self, bloques: list[BloqueTiempo]) -> None:
        pass
