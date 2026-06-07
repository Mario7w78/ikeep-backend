from fastapi import APIRouter, Depends

from dependency_injector.wiring import Provide, inject

from domain.services.suggest_service import SuggestService
from infrastructure.config.container import ApplicationContainer
from infrastructure.adapters.inbound.api.mappers import actividad_to_domain
from schemas.suggest_actividad_optimizable import (
    SugerenciaActividadOptimizable,
    SugerirActividadOptimizableRequest,
    SugerirActividadOptimizableResponse,
)

router = APIRouter(prefix="/schedule", tags=["Schedule"])


@router.post("/suggest-actividades-optimizables", response_model=SugerirActividadOptimizableResponse)
@inject
def suggest_actividades_optimizables(
    request: SugerirActividadOptimizableRequest,
    service: SuggestService = Depends(Provide[ApplicationContainer.suggest_service]),
):
    domain_activities = [actividad_to_domain(a) for a in request.actividades_optimizables]
    results = service.sugerir(request.tiempo_libre_minutos, domain_activities)

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
