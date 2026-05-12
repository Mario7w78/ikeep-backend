from dataclasses import dataclass


@dataclass
class TiempoTraslado:
    origen_id: str
    destino_id: str
    tiempo_estimado_minutos: int
