from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from infrastructure.config.container import ApplicationContainer
from infrastructure.adapters.inbound.api.v1.health_router import (
    router as health_router,
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
from infrastructure.adapters.inbound.api.middleware import (
    ErrorHandlerMiddleware,
    DomainException,
    SolverException,
)


def create_app() -> FastAPI:
    container = ApplicationContainer()

    app = FastAPI(title="IKEEP Backend", version="1.0.0")

    # Wire DI container
    container.wire()

    # Global error middleware (outermost layer)
    app.add_middleware(ErrorHandlerMiddleware)

    # Routers
    app.include_router(horarios_router)
    app.include_router(replanificar_router)
    app.include_router(suggest_router)
    app.include_router(health_router)

    # Store container reference for testing
    app.container = container

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
