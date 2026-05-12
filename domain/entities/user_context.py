from dataclasses import dataclass, field


@dataclass
class BloqueSueno:
    dia: int
    inicio: int
    fin: int


@dataclass
class ContextoUsuario:
    nivel_energia: int = 5
    horario_inicio: int = 480
    horario_fin: int = 1200
    bloques_sueno: list[BloqueSueno] = field(default_factory=list)
