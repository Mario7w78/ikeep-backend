from dataclasses import dataclass, field


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
    horario_inicio: int = 480
    horario_fin: int = 1200
    bloques_sueno: list[BloqueSueno] = field(default_factory=list)
    historial_energia: list[RegistroEnergia] = field(default_factory=list)
