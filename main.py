from fastapi import FastAPI, HTTPException
from Domain.Entities import HorarioRequest, ActividadProgramada
from UseCases.Scheluder import generar_horario_optimizado
import uvicorn

app = FastAPI(title="IKEEP Backend", version="1.0.0")

@app.post("/api/v1/horarios/generar", response_model=list[ActividadProgramada])
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

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)