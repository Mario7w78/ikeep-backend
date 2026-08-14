from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ActividadUsuario:
    """Una actividad tal como la define y guarda el usuario.

    No confundir con `Actividad`, que es la entrada del solver: alli una
    actividad es una unidad a colocar en el horario, ya aplanada, con hora de
    inicio, duracion y dia concreto. Aca es la definicion que el usuario
    administra —"Calculo, martes y jueves, con estos turnos"— y de la que se
    derivan varias unidades del solver al generar un horario.

    `config_por_dia` guarda esa estructura por dia sin interpretarla: es del
    cliente, cambia con la UI, y al backend hoy solo le toca conservarla
    intacta. Cuando el solver pase a leerla desde aca habra que darle forma.
    """

    id: str
    propietario_id: str
    nombre: str
    tipo: str
    #: De que parte de la vida es. Los cinco petalos del loto: estudio,
    #: trabajo, cuerpo, vinculos, yo.
    #:
    #: Es una dimension INDEPENDIENTE del comportamiento. "Clase" y "trabajo"
    #: no son dos formas de ocupar el horario —las dos son de hora fija— sino
    #: dos areas distintas, y esa es la unica diferencia real entre ellas.
    area: str = "estudio"
    #: OBSOLETA. Hacia tres trabajos y ninguno bien. Se conserva mientras
    #: haya clientes instalados que la manden.
    identidad: str = "tarea"
    prioridad: int = 3
    dificultad: str = "media"
    fecha_limite: str | None = None
    dias_habilitados: list[Any] = field(default_factory=list)
    config_por_dia: dict[str, Any] = field(default_factory=dict)
    dia_opcional: bool = False
    dia_desde: int | None = None
    dia_hasta: int | None = None
    es_ancla: bool = False
    #: Si esta puesta, la actividad ocurre una sola vez ese dia y los dias de
    #: la semana no aplican. Es lo que permite representar un parcial.
    fecha_unica: str | None = None
