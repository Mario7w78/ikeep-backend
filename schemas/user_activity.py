"""Contrato HTTP de las actividades guardadas del usuario.

Distinto de schemas/activity.py, que describe la entrada del solver: alli una
actividad es una unidad a colocar en el horario; aca es la definicion que el
usuario administra y de la que luego se derivan esas unidades.

Los nombres de campo son los que ya usa la app —`days_enabled`, `is_anchor`—
y no una traduccion del dominio. El cliente existe desde antes que estos
endpoints; el mapeo al dominio vive en el router, que es su lugar.
"""

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class ActivityPayload(BaseModel):
    """Lo que el cliente manda al crear o actualizar una actividad."""

    id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    type: str = Field(min_length=1, max_length=50)
    #: Uno de los cinco petalos: estudio, trabajo, cuerpo, vinculos, yo.
    area: str = Field(default="estudio", max_length=20)
    #: OBSOLETA, ver `area`. Sigue aceptandose para no romper clientes viejos.
    identity: str = Field(default="tarea", max_length=50)
    priority: int = Field(default=3, ge=1, le=5)
    difficulty: str = Field(default="media", max_length=50)
    deadline: str | None = Field(default=None, max_length=64)
    days_enabled: list[Any] = Field(default_factory=list)
    days_config: dict[str, Any] = Field(default_factory=dict)
    optional_day: bool = False
    # 0 = lunes, 6 = domingo. Se valida aca y no en el solver para que un dia
    # invalido se rechace antes de llegar a la base.
    day_from: int | None = Field(default=None, ge=0, le=6)
    day_to: int | None = Field(default=None, ge=0, le=6)
    is_anchor: bool = False
    #: Si esta puesta, la actividad ocurre una sola vez ese dia.
    fecha_unica: date | None = None


class ActivityResponse(ActivityPayload):
    """El payload mas el dueño, que lo determina el servidor.

    `user_id` nunca se toma del cuerpo de la peticion: sale del token, que
    esta firmado. Si viniera del cliente, cualquiera podria intentar escribir
    en nombre de otro — y aunque RLS lo rechazaria, el error aparecerria como
    un fallo raro de base en vez de como lo que es.
    """

    user_id: str
