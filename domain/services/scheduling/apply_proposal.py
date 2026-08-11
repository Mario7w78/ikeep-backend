"""Aplica una propuesta confirmada: guarda, regenera y persiste.

Hasta ahora esto lo orquestaba el cliente. Confirmar en el chat disparaba tres
viajes de red —guardar la actividad, generar el horario, persistirlo— y la
compensacion ante un fallo vivia escrita a mano en un store de Zustand. Eso es
logica de dominio en la capa de presentacion, y encima paga el arranque en
frio de Render en cada salto.

Aca es un solo viaje, al lado de los datos y del solver.

Lo que NO cambia es quien decide: nada llega hasta aca sin que el usuario haya
confirmado la propuesta. El modelo propone, la persona aprueba, y recien
entonces este servicio actua.
"""

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from domain.entities.user_activity import ActividadUsuario
from domain.services.scheduling.flattener import aplanar

logger = logging.getLogger(__name__)

_INDICE_A_DIA = {
    0: "Lunes",
    1: "Martes",
    2: "Miercoles",
    3: "Jueves",
    4: "Viernes",
    5: "Sabado",
    6: "Domingo",
}


class ErrorAlAplicar(Exception):
    """No se pudo dejar el horario en un estado bueno."""


@dataclass(frozen=True)
class ResultadoAplicar:
    estado: str | None
    mensaje: str | None
    recomendaciones: list[Any]
    tareas_omitidas: list[Any]
    actividades_programadas: list[dict[str, Any]]


class Repositorios(Protocol):
    """Lo que el servicio necesita del mundo exterior."""

    def actividades(self) -> list[ActividadUsuario]: ...
    def guardar_actividad(self, actividad: ActividadUsuario) -> None: ...
    def borrar_actividad(self, activity_id: str) -> None: ...
    def obtener_actividad(self, activity_id: str) -> ActividadUsuario | None: ...
    def ajustes(self) -> Any: ...
    def generar(self, solicitud: dict[str, Any]) -> Any: ...
    def guardar_horario(self, resultado: ResultadoAplicar) -> None: ...


def _minutos_a_hhmm(minutos: int) -> str:
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def _horas_por_dia(valor: Any, defecto: int, dias: int) -> list[int]:
    """El solver espera una lista por dia; los ajustes pueden traer un solo valor."""
    if isinstance(valor, list) and len(valor) == dias:
        return valor
    return [defecto] * dias


def _actividad_del_bloque(
    id_compuesto: str, por_id: dict[str, ActividadUsuario]
) -> ActividadUsuario | None:
    """De que definicion salio este bloque.

    El solver devuelve ids compuestos —`{actividad}-{grupo}-{dia}-{turno}`—.
    El cliente corta en el primer guion, lo que solo funciona mientras los
    ids no tengan guiones: hoy son `Date.now().toString()`, puros digitos.
    El dia que sean UUID, cada bloque perderia su actividad en silencio.

    Aca se busca el prefijo mas largo que sea un id conocido. No supone nada
    sobre la forma del id.
    """
    candidato = str(id_compuesto)
    while candidato:
        if candidato in por_id:
            return por_id[candidato]
        corte = candidato.rfind("-")
        if corte <= 0:
            return None
        candidato = candidato[:corte]
    return None


def _a_actividad_programada(
    bloque: Any, por_id: dict[str, ActividadUsuario]
) -> dict[str, Any]:
    """Da al bloque la forma que el cliente guarda y lee.

    Los bloques de traslado no salen de ninguna definicion del usuario, asi
    que van sin referencia.
    """
    original = _actividad_del_bloque(bloque.id_actividad, por_id)

    programada: dict[str, Any] = {
        "activity": None,
        "assignedStartTime": _minutos_a_hhmm(bloque.hora_inicio),
        "assignedEndTime": _minutos_a_hhmm(bloque.hora_fin),
        "day": _INDICE_A_DIA.get(bloque.dia, "Lunes"),
        "tipo": bloque.tipo,
        "nombre": bloque.nombre,
    }

    if original:
        programada["activity"] = {
            "id": str(original.id),
            "title": original.nombre,
            "type": original.tipo,
            "identity": original.identidad,
            "priority": original.prioridad,
            "difficulty": original.dificultad,
            "deadline": original.fecha_limite,
            "daysEnabled": original.dias_habilitados,
            "daysConfig": original.config_por_dia,
            "optionalDay": original.dia_opcional,
            "dayFrom": original.dia_desde,
            "dayTo": original.dia_hasta,
            "isAnchor": original.es_ancla,
        }

    return programada


def aplicar(
    repos: Repositorios,
    *,
    tipo: str,
    actividad: ActividadUsuario | None = None,
    activity_id: str | None = None,
    desfase_utc_minutos: int = 0,
    nivel_energia: int = 2,
) -> ResultadoAplicar:
    """Guarda el cambio, regenera el horario y lo persiste.

    Si el solver falla despues de haber tocado la base, se deshace el cambio y
    se regenera con lo anterior. La compensacion vive aca, junto a los datos:
    en el cliente dependia de que la app siguiera abierta y con red.
    """
    anterior: ActividadUsuario | None = None
    toco_la_base = False

    if tipo in ("crear", "modificar") and actividad is not None:
        anterior = repos.obtener_actividad(actividad.id)
        repos.guardar_actividad(actividad)
        toco_la_base = True
    elif tipo == "eliminar" and activity_id:
        anterior = repos.obtener_actividad(activity_id)
        repos.borrar_actividad(activity_id)
        toco_la_base = True

    try:
        return _regenerar_y_guardar(repos, desfase_utc_minutos, nivel_energia)
    except Exception as error:
        if not toco_la_base:
            raise

        logger.warning("Fallo la regeneracion. Se deshace el cambio: %s", error)
        try:
            if anterior is not None:
                repos.guardar_actividad(anterior)
            elif actividad is not None:
                repos.borrar_actividad(actividad.id)
            _regenerar_y_guardar(repos, desfase_utc_minutos, nivel_energia)
        except Exception:
            # Que falle la vuelta atras es peor que el fallo original: el
            # usuario queda con un cambio aplicado y un horario que no lo
            # refleja. Se registra entero para poder reconstruirlo.
            logger.exception("No se pudo deshacer el cambio.")

        raise ErrorAlAplicar(str(error)) from error


def _regenerar_y_guardar(
    repos: Repositorios, desfase_utc_minutos: int, nivel_energia: int
) -> ResultadoAplicar:
    actividades = repos.actividades()
    ajustes = repos.ajustes()
    aplanado = aplanar(actividades, desfase_utc_minutos)

    dias = ajustes.dias_totales
    solicitud = {
        "actividades_fijas": aplanado.fijas,
        "actividades_ancla": aplanado.ancla,
        "actividades_optimizables_puras": aplanado.optimizables,
        "ubicaciones": [],
        "tiempos_traslado": [],
        "dia_inicio": ajustes.dia_inicio,
        "dias_totales": dias,
        "contexto_usuario": {
            "nivel_energia": nivel_energia,
            "horario_inicio": _horas_por_dia(
                getattr(ajustes, "inicio_por_dia", None), ajustes.inicio_dia, dias
            ),
            "horario_fin": _horas_por_dia(
                getattr(ajustes, "fin_por_dia", None), ajustes.fin_dia, dias
            ),
            "bloques_sueno": [],
        },
    }

    resultado = repos.generar(solicitud)
    por_id = {str(a.id): a for a in actividades}

    aplicado = ResultadoAplicar(
        estado=getattr(resultado.estado, "value", resultado.estado),
        mensaje=resultado.mensaje,
        recomendaciones=list(resultado.recomendaciones or []),
        tareas_omitidas=list(getattr(resultado, "tareas_omitidas", []) or []),
        actividades_programadas=[
            _a_actividad_programada(b, por_id) for b in resultado.bloques
        ],
    )

    repos.guardar_horario(aplicado)
    return aplicado
