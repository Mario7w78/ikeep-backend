from pydantic import BaseModel


class BloqueSueno(BaseModel):
    dia: int
    inicio: int
    fin: int


class ContextoUsuario(BaseModel):
    nivel_energia: int = 5
    horario_inicio: int = 480
    horario_fin: int = 1200
    bloques_sueno: list[BloqueSueno] = []
