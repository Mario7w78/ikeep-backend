"""Contrato del asistente conversacional.

El borrador es la memoria de la conversacion. Los campos reflejan los de
ParseNLResponse a proposito: el cliente ya sabe mapear esa forma al estado del
formulario, y traducirla aca solo agregaria un lugar donde desincronizarse.

La diferencia con ParseNLResponse es que aca todo es opcional. Un borrador
describe lo que se sabe hasta ahora, no una actividad terminada.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Minutos desde medianoche. El limite superior evita que una hora invalida
# llegue al solver: reemplaza las lineas del prompt que le pedian al modelo no
# confundir la 1 pm con la 1 am, que es algo que un rango valida y un ruego no.
MINUTO_MAXIMO = 1439

DIAS_VALIDOS = {
    "lunes": "Lunes",
    "martes": "Martes",
    "miercoles": "Miercoles",
    "miércoles": "Miercoles",
    "jueves": "Jueves",
    "viernes": "Viernes",
    "sabado": "Sabado",
    "sábado": "Sabado",
    "domingo": "Domingo",
}


class BloqueHorario(BaseModel):
    """Un tramo concreto de un dia."""

    day: str = Field(description="Dia en espanol, ej. 'Martes'")
    start_time: int = Field(ge=0, le=MINUTO_MAXIMO)
    end_time: int = Field(ge=0, le=MINUTO_MAXIMO)

    @model_validator(mode="after")
    def rechazar_duracion_cero(self):
        """Un bloque que empieza y termina a la misma hora no es un horario.

        Los modelos lo usan como marcador cuando el usuario dijo el dia pero
        no la hora ("los martes"). Aceptarlo hacia que el borrador pareciera
        completo y se propusiera una actividad sin horario real.

        No se compara start < end: un bloque de 23:00 a 01:00 cruza medianoche
        y es perfectamente valido.
        """
        if self.start_time == self.end_time:
            raise ValueError(
                "El bloque no puede empezar y terminar a la misma hora; "
                "falta preguntar el horario."
            )
        return self

    @field_validator("day")
    @classmethod
    def normalizar_dia(cls, v: str) -> str:
        # Se acepta con y sin tilde, en cualquier caja, y se guarda en una
        # sola forma: el resto del sistema compara dias por igualdad.
        normalizado = DIAS_VALIDOS.get(v.strip().lower())
        if normalizado is None:
            raise ValueError(f"Dia no reconocido: {v}")
        return normalizado


class BorradorPatch(BaseModel):
    """Lo que el modelo emite cuando extrae informacion nueva.

    Todo opcional y parcial. Un campo ausente significa "no lo toques"; un
    null explicito significa "borralo". La distincion importa para las
    correcciones: "no, no tiene fecha limite" tiene que poder deshacer.
    """

    name: str | None = Field(default=None, max_length=200)
    activity_type: Literal["clase", "trabajo", "tarea", "viaje"] | None = None
    is_fixed: bool | None = None
    is_anchor: bool | None = None
    difficulty: Literal["baja", "media", "alta"] | None = None
    priority: Literal["baja", "media", "alta"] | None = None
    schedule: list[BloqueHorario] | None = None
    duracion_minutos: int | None = Field(default=None, ge=1, le=1440)
    hora_preferida_inicio: int | None = Field(default=None, ge=0, le=MINUTO_MAXIMO)
    hora_preferida_fin: int | None = Field(default=None, ge=0, le=MINUTO_MAXIMO)
    deadline: str | None = Field(default=None, max_length=64)
    location: str | None = Field(default=None, max_length=200)
    travel_to: int | None = Field(default=None, ge=0, le=720)
    travel_from: int | None = Field(default=None, ge=0, le=720)


class Borrador(BaseModel):
    """Lo que se sabe de la actividad hasta este punto de la conversacion."""

    name: str | None = None
    activity_type: str | None = None
    is_fixed: bool | None = None
    is_anchor: bool = False
    difficulty: str | None = None
    priority: str | None = None
    schedule: list[BloqueHorario] = Field(default_factory=list)
    duracion_minutos: int | None = None
    hora_preferida_inicio: int | None = None
    hora_preferida_fin: int | None = None
    deadline: str | None = None
    location: str | None = None
    travel_to: int | None = None
    travel_from: int | None = None

    @property
    def campos_faltantes(self) -> list[str]:
        """Que falta para poder proponer la actividad.

        Los slots vacios del borrador SON la lista de faltantes. Por eso ya no
        existe un campo missing_fields en el contrato: era una segunda fuente
        de verdad sobre lo mismo, y podia contradecir al borrador.
        """
        faltantes = []
        if not self.name:
            faltantes.append("name")
        if not self.activity_type:
            faltantes.append("activity_type")
        if self.is_fixed is None:
            faltantes.append("is_fixed")
        elif self.is_fixed:
            # Una actividad a hora fija necesita saber cuando.
            if not self.schedule:
                faltantes.append("schedule")
        else:
            # Una flexible delega el cuando al solver; lo que no puede faltar
            # es cuanto dura.
            if not self.duracion_minutos:
                faltantes.append("duracion_minutos")
        return faltantes

    @property
    def esta_completo(self) -> bool:
        return not self.campos_faltantes
