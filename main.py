from fastapi import FastAPI

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


def create_app() -> FastAPI:
    app = FastAPI(title="IKEEP Backend", version="1.0.0")
    app.include_router(horarios_router)
    app.include_router(replanificar_router)
    app.include_router(suggest_router)
    app.include_router(health_router)
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
