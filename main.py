from fastapi import FastAPI
import uvicorn
from api.v1.Schedule import router as horarios_router

app = FastAPI(title="IKEEP Backend", version="1.0.0")

app.include_router(horarios_router)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)