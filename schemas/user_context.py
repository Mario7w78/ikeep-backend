from pydantic import BaseModel


class BloqueSueno(BaseModel):
    dia: int
    inicio: int
    fin: int


class RegistroEnergia(BaseModel):
    timestamp: str
    nivel: int
    dia_semana: int
    contexto: str | None = None


class ContextoUsuario(BaseModel):
    nivel_energia: int = 2
    horario_inicio: int = 480
    horario_fin: int = 1200
    bloques_sueno: list[BloqueSueno] = []
    historial_energia: list[RegistroEnergia] = []
