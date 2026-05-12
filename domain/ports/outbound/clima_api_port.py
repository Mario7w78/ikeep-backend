from abc import ABC, abstractmethod


class ClimaApiPort(ABC):

    @abstractmethod
    def obtener_clima(self, fecha: str, lat: float, lon: float) -> dict:
        pass
