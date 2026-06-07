from dataclasses import dataclass, field

from domain.entities.enums import PatronEnergia


@dataclass
class BloqueSueno:
    dia: int
    inicio: int
    fin: int


@dataclass
class RegistroEnergia:
    timestamp: str
    nivel: int
    dia_semana: int
    contexto: str | None = None


@dataclass
class ContextoUsuario:
    nivel_energia: int = 2
    horario_inicio: int | list[int] = 480
    horario_fin: int | list[int] = 1200
    bloques_sueno: list[BloqueSueno] = field(default_factory=list)
    historial_energia: list[RegistroEnergia] = field(default_factory=list)
    patron_energia_manual: PatronEnergia | None = None

    def __post_init__(self):
        """Normalize horario_inicio/fin to list[int] for backward compatibility."""
        if isinstance(self.horario_inicio, int):
            self.horario_inicio = [self.horario_inicio] * 7
        if isinstance(self.horario_fin, int):
            self.horario_fin = [self.horario_fin] * 7
