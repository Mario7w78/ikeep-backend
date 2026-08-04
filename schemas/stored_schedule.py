"""Contrato HTTP del horario guardado y del historial de energia."""

from typing import Any

from pydantic import BaseModel, Field

from domain.entities.energy_record import DIAS_DE_HISTORIAL_POR_DEFECTO


class SchedulePayload(BaseModel):
    """El horario que el usuario acepto.

    `scheduled_activities` se pasa sin interpretar: es la salida del solver
    tal como la arma el cliente, y darle forma aca crearia una segunda
    definicion de la misma estructura.
    """

    estado: str | None = Field(default=None, max_length=50)
    mensaje: str | None = Field(default=None, max_length=2000)
    recomendaciones: list[Any] = Field(default_factory=list)
    tareas_omitidas: list[Any] = Field(default_factory=list)
    scheduled_activities: list[Any] = Field(default_factory=list)


class ScheduleResponse(SchedulePayload):
    user_id: str
    # Lo asigna Postgres; el cliente no lo manda pero si lo necesita.
    created_at: str | None = None


class EnergyPayload(BaseModel):
    # 1 = baja, 2 = normal, 3 = alta.
    nivel: int = Field(ge=1, le=3)
    # Opcional: si no viene, lo pone el servidor con la hora de recepcion.
    timestamp: str | None = Field(default=None, max_length=64)
    contexto: str | None = Field(default=None, max_length=500)


class EnergyResponse(BaseModel):
    timestamp: str
    nivel: int
    # 0 = lunes ... 6 = domingo.
    dia_semana: int
    contexto: str | None = None


class EnergyTodayResponse(BaseModel):
    reportado: bool


DIAS_HISTORIAL = Field(
    default=DIAS_DE_HISTORIAL_POR_DEFECTO,
    ge=1,
    le=90,
    description="Cuantos dias de historial devolver.",
)
