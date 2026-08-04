"""Contrato HTTP del perfil y los ajustes de planificacion.

Los nombres de campo son los que ya usa la app, para no obligarla a traducir.
"""

from typing import Any

from pydantic import BaseModel, Field


class ProfilePayload(BaseModel):
    username: str | None = Field(default=None, max_length=100)
    # 1 a 5. No confundir con el nivel de un reporte diario de energia, que va
    # de 1 a 3: son escalas distintas para cosas distintas. La entidad User
    # del cliente valida este rango, y el backend no debe ser mas estricto que
    # el dominio al que sirve —seria un 422 sobre un valor perfectamente
    # valido, y el cliente lo veria como un error inexplicable.
    energy_level: int | None = Field(default=None, ge=1, le=5)
    wake_up_time: str | None = Field(default=None, max_length=10)
    sleep_time: str | None = Field(default=None, max_length=10)


class ProfileResponse(ProfilePayload):
    id: str
    # Lo calcula el servidor para que el cliente no repita la regla de que
    # significa "perfil incompleto".
    is_complete: bool


class SettingsPatch(BaseModel):
    """Todos opcionales: se aplica solo lo que venga.

    Cambiar la hora de inicio no deberia poder pisar el resto de los ajustes,
    asi que un campo ausente significa "no lo toques" y no "ponelo en null".
    """

    start_hour: int | None = Field(default=None, ge=0, le=1440)
    end_hour: int | None = Field(default=None, ge=0, le=1440)
    dia_inicio: int | None = Field(default=None, ge=0, le=6)
    dias_totales: int | None = Field(default=None, ge=1, le=7)
    per_day_start_hours: list[Any] | None = None
    per_day_end_hours: list[Any] | None = None
    custom_energy_pattern: str | None = Field(default=None, max_length=100)


class SettingsResponse(BaseModel):
    user_id: str
    start_hour: int
    end_hour: int
    dia_inicio: int
    dias_totales: int
    per_day_start_hours: list[Any] | None
    per_day_end_hours: list[Any] | None
    custom_energy_pattern: str | None
