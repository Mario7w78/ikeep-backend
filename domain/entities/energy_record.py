from dataclasses import dataclass

# Se conservan 90 dias de historial. Mas atras no aporta: el patron de
# energia de alguien hace tres meses ya no describe su presente, y la tabla
# creceria sin limite.
DIAS_DE_RETENCION = 90
DIAS_DE_HISTORIAL_POR_DEFECTO = 14


@dataclass(frozen=True)
class RegistroEnergia:
    """Un reporte de energia del usuario en un momento dado."""

    propietario_id: str
    # ISO 8601 con zona horaria.
    momento: str
    # 1 = baja, 2 = normal, 3 = alta.
    nivel: int
    # 0 = lunes ... 6 = domingo. Se guarda derivado del momento para poder
    # agrupar por dia de la semana sin recalcularlo en cada consulta.
    dia_semana: int
    contexto: str | None = None
