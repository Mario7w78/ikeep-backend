from fastapi import APIRouter, HTTPException

from domain.services.suggest_service import SuggestService
from schemas.suggest_actividad_optimizable import (
    Actividad,
    SugerenciaActividadOptimizable,
    SugerirActividadOptimizableRequest,
    SugerirActividadOptimizableResponse,
)

router = APIRouter(prefix="/schedule", tags=["Schedule"])

_service = SuggestService()


@router.post("/suggest-actividades-optimizables", response_model=SugerirActividadOptimizableResponse)
def suggest_actividades_optimizables(request: SugerirActividadOptimizableRequest):
    try:
        from infrastructure.adapters.inbound.api.mappers import actividad_to_domain

        domain_activities = [actividad_to_domain(a) for a in request.actividades_optimizables]
        results = _service.sugerir(request.tiempo_libre_minutos, domain_activities)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return SugerirActividadOptimizableResponse(
        sugerencias=[
            SugerenciaActividadOptimizable(
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
