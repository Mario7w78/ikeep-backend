import httpx

from domain.ports.outbound.clima_api_port import ClimaApiPort
from infrastructure.config.settings import get_settings


class HttpxClimaApi(ClimaApiPort):
    def __init__(self, api_key: str, base_url: str = "https://api.clima.com"):
        self.api_key = api_key
        self.base_url = base_url

    def obtener_clima(self, fecha: str, lat: float, lon: float) -> dict:
        settings = get_settings()
        with httpx.Client(base_url=self.base_url) as client:
            resp = client.get(
                "/weather",
                params={
                    "date": fecha,
                    "lat": lat,
                    "lon": lon,
                    "api_key": self.api_key or settings.CLIMA_API_KEY,
                },
            )
            resp.raise_for_status()
            return resp.json()
