"""In-memory per-IP rate limiting for the LLM-backed endpoints.

Only the /parse-nl* routes are limited: they are unauthenticated and every
call spends provider quota (Groq/Cerebras/Mistral), so an unthrottled loop
drains the API keys. The solver endpoints are CPU-bound on our own machine
and /health must stay open for the warm-up ping and the uptime cron.

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
    """Sliding-window limiter over the paths in `path_marker`."""

    def __init__(self, app, requests_per_minute: int = 20, path_marker: str = "parse-nl"):
        super().__init__(app)
        self._limit = requests_per_minute
        self._path_marker = path_marker
        self._hits: dict[str, deque[float]] = {}

    def _sweep(self, cutoff: float) -> None:
        for ip in [ip for ip, hits in self._hits.items() if not hits or hits[-1] < cutoff]:
            del self._hits[ip]

    async def dispatch(self, request: Request, call_next):
        if self._limit <= 0 or self._path_marker not in request.url.path:
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
