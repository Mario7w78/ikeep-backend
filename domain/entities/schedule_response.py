from dataclasses import dataclass, field

from domain.entities.enums import EstadoSolucion, TipoActividad


@dataclass
class BloqueTiempo:
    id_actividad: str
    nombre: str
    tipo: TipoActividad
    dia: int
    hora_inicio: int
    hora_fin: int
    ubicacion_id: str | None = None
    #: Si su hora esta clavada. Es lo unico que el replanificador necesita
    #: saber para decidir si puede tocarla, y `tipo` no lo dice: un turno de
    #: trabajo de 9 a 5 es tan inamovible como una clase, y una clase de
    #: idiomas que estudias cuando puedes no lo es. Preguntar "que es?" en vez
    #: de "se puede mover?" le reubicaba el trabajo al usuario.
    #:
    #: `None` = el bloque es anterior al campo. No se asume nada; se resuelve
    #: con la regla vieja en `es_fija_efectiva`.
    es_fija: bool | None = None

    @property
    def es_fija_efectiva(self) -> bool:
        """Si se puede mover, resolviendo tambien los bloques viejos.

        Los horarios generados antes de que existiera `es_fija` siguen
        guardados en el telefono y vuelven tal cual al replanificar. Para
        esos —y solo para esos— vale la regla anterior: era clase, era fija.
        """
        if self.es_fija is None:
            return self.tipo == TipoActividad.CLASE
        return self.es_fija


@dataclass
class RespuestaHorario:
    estado: EstadoSolucion
    bloques: list[BloqueTiempo] = field(default_factory=list)
    mensaje: str = ""
    recomendaciones: list[str] = field(default_factory=list)
    tareas_omitidas: list[str] = field(default_factory=list)
