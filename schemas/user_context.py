from pydantic import BaseModel, field_validator

from schemas.activity import PatronEnergia


class DreamBlock(BaseModel):
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
    horario_inicio: int | list[int] = 480
    horario_fin: int | list[int] = 1200
    dream_blocks: list[DreamBlock] = []
    historial_energia: list[RegistroEnergia] = []
    patron_energia_manual: PatronEnergia | None = None

    @field_validator("horario_inicio", "horario_fin")
    @classmethod
    def _validate_horario_list(cls, v: int | list[int]) -> int | list[int]:
        if isinstance(v, list):
            for i, val in enumerate(v):
                if not (0 <= val <= 1440):
                    raise ValueError(
                        f"Cada valor en horario debe estar entre 0 y 1440, "
                        f"pero se encontró {val} en la posición {i}."
                    )
        else:
            if not (0 <= v <= 1440):
                raise ValueError(
                    f"horario debe estar entre 0 y 1440, pero se recibió {v}."
                )
        return v
