from fastapi import APIRouter, HTTPException
from schemas.Entities import HorarioRequest, ActividadProgramada
from services.Scheduler import generar_horario_semanal, EstadoSolucion

router = APIRouter(prefix="/api/v1/horarios", tags=["Horarios"])

@router.post("/generar", response_model=list[ActividadProgramada])
def generar_horario(request: HorarioRequest):
    try:
        for act in request.actividades:
            print(f"[ACT] {act.nombre} | fija={act.es_fija} | dias={act.dias_permitidos} "
                  f"| inicio={act.inicio_minutos} fin={act.fin_minutos} "
                  f"| dur={act.duracion_minutos} traslado={act.tiempo_traslado_minutos}")
            
        resultado = generar_horario_semanal(
            actividades=request.actividades,
            inicio_dia=request.hora_inicio_dia,
            fin_dia=request.hora_fin_dia
        )
    except HTTPException:
        raise  
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if resultado.estado in (EstadoSolucion.INFACTIBLE, EstadoSolucion.DESCONOCIDO):
        raise HTTPException(status_code=409, detail=resultado.mensaje)

    return resultado.actividades