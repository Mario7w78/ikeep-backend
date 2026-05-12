from fastapi import APIRouter, HTTPException

from domain.services.suggest_service import SuggestService
from schemas.suggest_task import (
    Actividad,
    SugerenciaTarea,
    SugerirTareaRequest,
    SugerirTareaResponse,
)

router = APIRouter(prefix="/schedule", tags=["Schedule"])

_service = SuggestService()


@router.post("/suggest-task", response_model=SugerirTareaResponse)
def suggest_task(request: SugerirTareaRequest):
    try:
        from infrastructure.adapters.inbound.api.mappers import actividad_to_domain

        domain_tasks = [actividad_to_domain(a) for a in request.tareas_pendientes]
        results = _service.sugerir(request.tiempo_libre_minutos, domain_tasks)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return SugerirTareaResponse(
        sugerencias=[
            SugerenciaTarea(
                id_actividad=r["id_actividad"],
                nombre=r["nombre"],
                tipo=r["tipo"],
                duracion_estimada=r["duracion_estimada"],
                dificultad=r["dificultad"],
                prioridad=r["prioridad"],
                encaja=r["encaja"],
                razon=r["razon"],
            )
            for r in results
        ],
    )
