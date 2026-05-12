from pydantic import BaseModel


class TiempoTraslado(BaseModel):
    origen_id: str
    destino_id: str
    tiempo_estimado_minutos: int
