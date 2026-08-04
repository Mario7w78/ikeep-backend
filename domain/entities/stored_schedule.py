from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class HorarioGuardado:
    """El horario vigente de un usuario. Hay uno solo, o ninguno.

    No confundir con RespuestaHorario, que es lo que devuelve el solver al
    generar. Esto es lo que quedo guardado despues de que el usuario lo
    acepto, y lo que ve al abrir la app.

    `actividades_programadas` se conserva tal como la manda el cliente. Es una
    decision consciente: el solver ya hizo su trabajo, y volver a interpretar
    su salida aca solo agregaria un lugar donde la representacion pueda
    quedar desalineada con la del cliente.
    """

    propietario_id: str
    estado: str | None = None
    mensaje: str | None = None
    recomendaciones: list[Any] = field(default_factory=list)
    tareas_omitidas: list[Any] = field(default_factory=list)
    actividades_programadas: list[Any] = field(default_factory=list)
    # ISO 8601. Lo pone Postgres al crear la fila; el cliente lo necesita
    # porque Schedule.createdAt es obligatorio en su entidad.
    creado_en: str | None = None
