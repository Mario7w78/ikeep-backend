from pydantic import BaseModel, model_validator

from schemas.activity import Actividad
from schemas.location import Ubicacion
from schemas.travel_time import TiempoTraslado
from schemas.user_context import ContextoUsuario


class SolicitudHorario(BaseModel):
    actividades_fijas: list[Actividad]
    tareas_pendientes: list[Actividad]
    ubicaciones: list[Ubicacion] = []
    tiempos_traslado: list[TiempoTraslado] = []
    contexto_usuario: ContextoUsuario = ContextoUsuario()
    dia_inicio: int = 0
    dias_totales: int = 7

    @model_validator(mode='after')
    def _validate_rolling_window(self) -> 'SolicitudHorario':
        if self.dia_inicio < 0:
            raise ValueError("dia_inicio debe ser >= 0")
        if not (1 <= self.dias_totales <= 7):
            raise ValueError("dias_totales debe estar entre 1 y 7")
        if self.dia_inicio + self.dias_totales > 7:
            raise ValueError(
                f"dia_inicio ({self.dia_inicio}) + dias_totales ({self.dias_totales}) "
                f"no puede exceder 7"
            )
        return self

    @model_validator(mode='after')
    def _validate_per_day_hours(self) -> 'SolicitudHorario':
        ctx = self.contexto_usuario
        d_tot = self.dias_totales

        # Expand single int → list for backward compat
        if isinstance(ctx.horario_inicio, int):
            ctx.horario_inicio = [ctx.horario_inicio] * d_tot
        if isinstance(ctx.horario_fin, int):
            ctx.horario_fin = [ctx.horario_fin] * d_tot

        # Validate list length
        if len(ctx.horario_inicio) != d_tot:
            raise ValueError(
                f"horario_inicio tiene {len(ctx.horario_inicio)} elementos, "
                f"pero se requieren {d_tot} (dias_totales)"
            )
        if len(ctx.horario_fin) != d_tot:
            raise ValueError(
                f"horario_fin tiene {len(ctx.horario_fin)} elementos, "
                f"pero se requieren {d_tot} (dias_totales)"
            )

        # Validate each day: 0 <= inicio < fin <= 1440
        for i in range(d_tot):
            inicio = ctx.horario_inicio[i]
            fin = ctx.horario_fin[i]
            if not (0 <= inicio < fin <= 1440):
                raise ValueError(
                    f"Para el día {i} (relativo a dia_inicio), "
                    f"horario_inicio ({inicio}) debe ser < horario_fin ({fin}) "
                    f"y ambos deben estar entre 0 y 1440."
                )

        return self
