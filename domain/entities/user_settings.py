from dataclasses import dataclass, field
from typing import Any

# Minutos desde medianoche. 240 = 04:00, 1320 = 22:00. Son los mismos
# defaults que ya usaba el cliente: cambiarlos aca movería el dia de todos
# los usuarios que nunca tocaron la configuracion.
INICIO_DIA_POR_DEFECTO = 240
FIN_DIA_POR_DEFECTO = 1320


@dataclass(frozen=True)
class AjustesUsuario:
    """Preferencias de planificacion de un usuario.

    Hay una sola fila por usuario y siempre existe conceptualmente: si no
    esta en la base, valen los defaults. Por eso la lectura nunca devuelve
    None — devuelve los defaults— y la escritura es siempre un upsert.
    """

    propietario_id: str
    inicio_dia: int = INICIO_DIA_POR_DEFECTO
    fin_dia: int = FIN_DIA_POR_DEFECTO
    dia_inicio: int = 0
    dias_totales: int = 7
    # None significa "sin override": el dia usa inicio_dia/fin_dia. Una lista
    # da un limite distinto por dia de la semana.
    inicio_por_dia: list[Any] | None = None
    fin_por_dia: list[Any] | None = None
    patron_energia_manual: str | None = None
