from pydantic import BaseModel


class Ubicacion(BaseModel):
    id: str
    nombre: str
    latitud: float
    longitud: float
