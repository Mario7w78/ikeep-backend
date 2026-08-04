"""Fuente de datos del asistente sobre los repositorios.

Cruza la frontera entre dos vocabularios. Lo que guarda el cliente usa el
suyo —dias por nombre, horas como "HH:mm"— y el contexto del modelo usa
minutos e ids. Traducir aca, en un solo lugar, evita que cada tool lo haga a
su manera.

Todo lo ilegible se descarta en vez de propagarse: perder un bloque deja al
asistente con menos informacion, pero un error deja al usuario sin asistente.
"""

import logging
from typing import Any

from domain.ports.outbound.schedule_repository_port import HorarioRepositoryPort
from domain.ports.outbound.user_activity_repository_port import (
    ActividadUsuarioRepositoryPort,
)
from domain.services.assistant.context_builder import BloqueAgenda
from domain.services.assistant.conversation import FuenteDeDatos, coincidencias

logger = logging.getLogger(__name__)

_DIAS = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "miércoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sabado": 5,
    "sábado": 5,
    "domingo": 6,
}


def indice_de_dia(dia: Any) -> int | None:
    """0 = lunes. None si no se reconoce."""
    if not isinstance(dia, str):
        return None
    return _DIAS.get(dia.strip().lower())


def a_minutos(hora: Any) -> int | None:
    """Convierte "HH:mm" a minutos desde medianoche. None si es ilegible."""
    if not isinstance(hora, str) or ":" not in hora:
        return None
    try:
        horas, minutos = hora.split(":", 1)
        total = int(horas) * 60 + int(minutos)
    except (ValueError, TypeError):
        return None

    return total if 0 <= total <= 1439 else None


class RepositorioFuenteDeDatos(FuenteDeDatos):
    def __init__(
        self,
        access_token: str,
        horarios: HorarioRepositoryPort,
        actividades: ActividadUsuarioRepositoryPort,
    ):
        self._token = access_token
        self._horarios = horarios
        self._actividades = actividades

    def agenda(self) -> list[BloqueAgenda]:
        horario = self._horarios.get(self._token)
        if not horario:
            return []

        bloques = []
        for item in horario.actividades_programadas:
            bloque = self._a_bloque(item)
            if bloque:
                bloques.append(bloque)
        return bloques

    def _a_bloque(self, item: Any) -> BloqueAgenda | None:
        if not isinstance(item, dict):
            return None

        # Los tramos de viaje vienen sin actividad: no son algo que el usuario
        # pueda modificar ni eliminar.
        actividad = item.get("activity")
        if not isinstance(actividad, dict) or not actividad.get("id"):
            return None

        dia = indice_de_dia(item.get("day"))
        inicio = a_minutos(item.get("assignedStartTime"))
        fin = a_minutos(item.get("assignedEndTime"))
        if dia is None or inicio is None or fin is None:
            logger.debug("Bloque ilegible en el horario, se descarta: %r", item)
            return None

        return BloqueAgenda(
            id_actividad=str(actividad["id"]),
            nombre=str(actividad.get("title") or "Sin nombre"),
            dia=dia,
            inicio=inicio,
            fin=fin,
        )

    def buscar_actividad(self, texto: str) -> list[dict[str, Any]]:
        actividades = [
            {"id": a.id, "nombre": a.nombre, "tipo": a.tipo}
            for a in self._actividades.list_all(self._token)
        ]
        return coincidencias(actividades, texto)

    def sugerir_tarea(self) -> dict[str, Any]:
        """Que podria hacer ahora, entre lo que no tiene hora fija.

        No usa el solver: aca alcanza con darle al modelo los candidatos y su
        dificultad para que elija con el contexto de la conversacion, que es
        justamente lo que el solver no tiene.
        """
        candidatas = [
            {
                "id": a.id,
                "nombre": a.nombre,
                "dificultad": a.dificultad,
                "prioridad": a.prioridad,
                "fecha_limite": a.fecha_limite,
            }
            for a in self._actividades.list_all(self._token)
            if a.tipo != "fija"
        ]
        return {"candidatas": candidatas, "cantidad": len(candidatas)}
