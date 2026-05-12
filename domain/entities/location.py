from dataclasses import dataclass


@dataclass
class Ubicacion:
    id: str
    nombre: str
    latitud: float
    longitud: float
