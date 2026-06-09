from dataclasses import dataclass, field

from domain.entities.enums import PatronEnergia


@dataclass
class DreamBlock:
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
    dream_blocks: list[DreamBlock] = field(default_factory=list)
    historial_energia: list[RegistroEnergia] = field(default_factory=list)
    patron_energia_manual: PatronEnergia | None = None

    def __post_init__(self):
        """Normalize horario_inicio/fin to list[int] for backward compatibility.

        Note: defaults to 7-day length (the standard week). When used within
        a SolicitudHorario with a different dias_totales, the schema-level
        validator expands single int → list[dias_totales] BEFORE the domain
        entity is constructed, so this only applies for standalone use.
        """
        if isinstance(self.horario_inicio, int):
            self.horario_inicio = [self.horario_inicio] * 7
        if isinstance(self.horario_fin, int):
            self.horario_fin = [self.horario_fin] * 7
