import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from infrastructure.config.container import ApplicationContainer
from infrastructure.config.settings import get_settings
from infrastructure.adapters.inbound.api.v1.health_router import (
    router as health_router,
)
from infrastructure.adapters.inbound.api.v1.rewards_router import (
    router as rewards_router,
)
from infrastructure.adapters.inbound.api.v1.reschedule_router import (
    router as replanificar_router,
)
from infrastructure.adapters.inbound.api.v1.schedule_router import (
    router as horarios_router,
)
from infrastructure.adapters.inbound.api.v1.suggest_router import (
    router as suggest_router,
)
from infrastructure.adapters.inbound.api.v1.activities_router import (
    router as activities_router,
)
from infrastructure.adapters.inbound.api.v1.assistant_router import (
    router as assistant_router,
)
from infrastructure.adapters.inbound.api.v1.profile_router import (
    router as profile_router,
)
from infrastructure.adapters.inbound.api.v1.stored_schedule_router import (
    router as stored_schedule_router,
)
from infrastructure.adapters.inbound.api.middleware import ErrorHandlerMiddleware
from infrastructure.adapters.inbound.api.rate_limit import RateLimitMiddleware
from infrastructure.adapters.outbound.supabase.client import anon_client, verify_schema


logger = logging.getLogger(__name__)


def _check_schema_on_startup() -> None:
    """Report a broken schema at boot instead of at request time.

    A missing table is a deployment mistake and must be loud. An unreachable
    Supabase is not: the solver endpoints do not touch the database, so a
    transient outage should not keep the whole service from starting.
    """
    if not get_settings().VERIFY_SCHEMA_ON_STARTUP:
        return

    try:
        client = anon_client()
    except RuntimeError as exc:
        logger.warning("Sin acceso a Supabase, no se verifica el esquema: %s", exc)
        return

    try:
        verify_schema(client)
    except RuntimeError:
        raise
    except Exception as exc:
        logger.warning("No se pudo verificar el esquema ahora: %s", exc)


def create_app() -> FastAPI:
    settings = get_settings()
    container = ApplicationContainer()

    # Without this the logger.info/warning calls across the codebase are
    # dropped by Python's default config and we lose the failover and
    # circuit-breaker traces entirely.
    logging.basicConfig(
        level=settings.LOG_LEVEL.upper(),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    app = FastAPI(title="IKEEP Backend", version="1.0.0")

    # Wire DI container
    container.wire()

    # Middleware runs outermost-last: CORS wraps the limiter, which wraps the
    # error handler, so even a 429 or a 500 carries CORS headers.
    app.add_middleware(ErrorHandlerMiddleware)
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_minute=settings.RATE_LIMIT_PER_MINUTE,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        # Auth is Bearer-token based, not cookie based, so credentialed
        # requests are unnecessary — and "*" + credentials is rejected
        # by browsers anyway.
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(horarios_router)
    app.include_router(replanificar_router)
    app.include_router(suggest_router)
    app.include_router(activities_router)
    app.include_router(profile_router)
    app.include_router(stored_schedule_router)
    app.include_router(assistant_router)
    app.include_router(rewards_router)
    app.include_router(health_router)

    _check_schema_on_startup()

    # Store container reference for testing
    app.container = container

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
