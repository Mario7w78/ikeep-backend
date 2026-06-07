from enum import Enum

from pydantic import BaseModel, model_validator


class TipoActividad(str, Enum):
    CLASE = "clase"
    TRABAJO = "trabajo"
    TAREA = "tarea"


class Dificultad(str, Enum):
    BAJA = "baja"
    MEDIA = "media"
    ALTA = "alta"


class PatronEnergia(str, Enum):
    TRANSCRIPTORIO = "transcriptoriano"
    TENDENCIA = "tendencia"
    CRONICO = "cronico"


class Actividad(BaseModel):
    id: str
    nombre: str
    tipo: TipoActividad
    dia: int | None = None
    dia_desde: int = 0
    dia_hasta: int = 6
    dias_permitidos: list[int] | None = None
    es_ancla: bool = False
    hora_inicio: int
    hora_fin: int
    ubicacion_id: str | None = None
    prioridad: int = 0
    duracion_estimada: int
    fecha_limite: str | None = None
    dificultad: Dificultad = Dificultad.MEDIA

    @model_validator(mode='after')
    def _validate_day_fields(self) -> 'Actividad':
        # F2: dia → dia_hasta alias (only if dia_hasta is still the default)
        if self.dia is not None:
            if 'dia_hasta' in self.model_fields_set:
                raise ValueError(
                    "No puedes establecer 'dia' y 'dia_hasta' al mismo tiempo. "
                    "Usa 'dia' (alias obsoleto) o 'dia_hasta', pero no ambos."
                )
            self.dia_hasta = self.dia
            self.dia_desde = 0

        # F2: Validate day range bounds
        if not (0 <= self.dia_desde <= self.dia_hasta <= 6):
            raise ValueError(
                f"El rango de días debe cumplir 0 <= dia_desde <= dia_hasta <= 6, "
                f"pero se recibió dia_desde={self.dia_desde}, dia_hasta={self.dia_hasta}."
            )

        # F3: Validate dias_permitidos values
        if self.dias_permitidos is not None:
            seen: set[int] = set()
            deduped: list[int] = []
            for d in self.dias_permitidos:
                if not (0 <= d <= 6):
                    raise ValueError(
                        f"Cada valor en dias_permitidos debe estar entre 0 y 6, "
                        f"pero se encontró {d}."
                    )
                if d not in seen:
                    seen.add(d)
                    deduped.append(d)
            self.dias_permitidos = deduped

        # F5: Anchor task constraints
        if self.es_ancla:
            have_concrete_day = self.dia is not None or self.dia_desde == self.dia_hasta
            if not have_concrete_day:
                raise ValueError(
                    "Una tarea ancla (es_ancla=True) requiere un día específico: "
                    "establece 'dia' o usa dia_desde == dia_hasta."
                )
            if self.dias_permitidos is not None:
                anchor_day = self.dia if self.dia is not None else self.dia_desde
                if len(self.dias_permitidos) > 1 or (
                    len(self.dias_permitidos) == 1 and self.dias_permitidos[0] != anchor_day
                ):
                    raise ValueError(
                        "Una tarea ancla no puede tener dias_permitidos con múltiples valores "
                        "o un valor diferente al día ancla."
                    )
            if self.dia is not None:
                self.dia_desde = self.dia
                self.dia_hasta = self.dia

        return self
