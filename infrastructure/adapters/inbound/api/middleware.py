"""Global error handling middleware for FastAPI.

Catches domain-level exceptions and returns structured JSON responses
instead of letting FastAPI's default 500 handlers take over.
"""

import logging
import traceback

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


# ─── Domain Exceptions ───────────────────────────────────────────


class DomainException(Exception):
    """Base class for domain-level errors that should map to 422."""

    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message)
        self.detail = detail or {}


class SolverException(DomainException):
    """Raised when the CP-SAT solver cannot find a solution."""

    pass


class ValidationException(DomainException):
    """Raised when input data violates domain invariants."""

    pass


class LLMServiceException(DomainException):
    """Raised when the LLM service returns an error or malformed response."""

    pass


class LLMTimeoutException(DomainException):
    """Raised when the LLM service request times out."""

    pass


# ─── Status code mapping ─────────────────────────────────────────

EXCEPTION_STATUS_MAP: dict[type, int] = {
    ValidationException: 422,
    SolverException: 409,
    LLMServiceException: 503,
    LLMTimeoutException: 503,
    DomainException: 422,
    ValueError: 422,
    TypeError: 422,
}


# ─── Middleware ───────────────────────────────────────────────────


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """Catches unhandled exceptions and returns structured JSON errors.

    Priority:
    1. Domain exceptions → mapped status codes
    2. Known Python exceptions → 422
    3. Everything else → 500 with sanitized message
    """

    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)

        except DomainException as exc:
            status = EXCEPTION_STATUS_MAP.get(type(exc), 422)
            logger.warning(
                "Domain error on %s %s: %s",
                request.method,
                request.url.path,
                exc,
            )
            return JSONResponse(
                status_code=status,
                content={
                    "error": type(exc).__name__,
                    "message": str(exc),
                    "detail": getattr(exc, "detail", {}),
                },
            )

        except ValueError as exc:
            logger.warning(
                "Validation error on %s %s: %s",
                request.method,
                request.url.path,
                exc,
            )
            return JSONResponse(
                status_code=422,
                content={
                    "error": "ValidationException",
                    "message": str(exc),
                },
            )

        except Exception as exc:
            logger.error(
                "Unhandled error on %s %s: %s\n%s",
                request.method,
                request.url.path,
                exc,
                traceback.format_exc(),
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": "InternalServerError",
                    "message": "An unexpected error occurred. Check logs for details.",
                },
            )
