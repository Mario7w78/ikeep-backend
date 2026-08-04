"""In-memory per-IP rate limiting for the LLM-backed endpoints.

Only the routes that spend provider quota (Groq/Cerebras/Mistral) are limited,
so an unthrottled loop cannot drain the API keys. The solver endpoints are
CPU-bound on our own machine and /health must stay open for the warm-up ping
and the uptime cron.

The assistant endpoint is included even though it requires authentication: a
single turn runs a loop that may call the provider several times, so it is the
most expensive route we expose. Needing an account raises the cost of abusing
it, but does not cap it.

This is a single-process limiter. It is enough while the service runs on a
single Render instance; a multi-instance deployment needs a shared store.
"""

import logging
import time
from collections import deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60
# Rutas que gastan cuota de proveedor. Se identifican por fragmento y no por
# ruta exacta para que sobrevivan a un cambio de prefijo.
LIMITED_PATH_MARKERS = ("parse-nl", "asistente")
# Above this many tracked IPs we sweep out the idle ones, so a caller
# rotating addresses cannot grow the dict without bound.
MAX_TRACKED_IPS = 10_000


def _client_ip(request: Request) -> str:
    """Best-effort client address.

    Render terminates TLS at its proxy, so request.client.host is the proxy
    and the caller is the first entry of X-Forwarded-For. That header is
    spoofable when the app is reached directly, which only lets an attacker
    dodge their own limit — it cannot be used to throttle someone else.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window limiter over the paths matching any of `path_markers`."""

    def __init__(
        self,
        app,
        requests_per_minute: int = 20,
        path_markers: tuple[str, ...] = LIMITED_PATH_MARKERS,
    ):
        super().__init__(app)
        self._limit = requests_per_minute
        self._path_markers = path_markers
        self._hits: dict[str, deque[float]] = {}

    def _esta_limitada(self, path: str) -> bool:
        return any(marcador in path for marcador in self._path_markers)

    def _sweep(self, cutoff: float) -> None:
        for ip in [ip for ip, hits in self._hits.items() if not hits or hits[-1] < cutoff]:
            del self._hits[ip]

    async def dispatch(self, request: Request, call_next):
        if self._limit <= 0 or not self._esta_limitada(request.url.path):
            return await call_next(request)

        now = time.monotonic()
        cutoff = now - WINDOW_SECONDS
        ip = _client_ip(request)

        if len(self._hits) > MAX_TRACKED_IPS:
            self._sweep(cutoff)

        hits = self._hits.setdefault(ip, deque())
        while hits and hits[0] < cutoff:
            hits.popleft()

        if len(hits) >= self._limit:
            retry_after = max(1, int(hits[0] + WINDOW_SECONDS - now) + 1)
            logger.warning(
                "Rate limit hit by %s on %s (%d/%dmin)",
                ip,
                request.url.path,
                len(hits),
                self._limit,
            )
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                content={
                    "error": "RateLimitExceeded",
                    "message": (
                        "Demasiadas solicitudes seguidas. "
                        f"Vuelve a intentarlo en {retry_after} segundos."
                    ),
                },
            )

        hits.append(now)
        return await call_next(request)
