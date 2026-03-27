from fastapi import APIRouter, HTTPException
from schemas.Entities import HorarioRequest, ActividadProgramada
from services.Scheluder import generar_horario_optimizado

router = APIRouter(prefix="/api/v1/horarios", tags=["Horarios"])

@router.post("/generar", response_model=list[ActividadProgramada])
def generar_horario(request: HorarioRequest):
    try:
        horario = generar_horario_optimizado(
            actividades=request.actividades,
            inicio_dia=request.hora_inicio_dia,
            fin_dia=request.hora_fin_dia
        )
        if not horario:
            raise HTTPException(status_code=400, detail="No se encontró una solución factible para este horario.")
        return horario
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))