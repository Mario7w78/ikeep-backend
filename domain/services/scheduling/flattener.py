"""Convierte las actividades del usuario en entrada para el solver.

`ActividadUsuario` es la definicion que el usuario administra —"Calculo,
martes y jueves, con estos turnos"—. `Actividad` es una unidad concreta a
colocar. Una definicion produce varias unidades: una por turno y por dia.

Hasta ahora este aplanado vivia en el cliente y el servidor recibia el
resultado ya masticado. Eso obligaba a que el telefono leyera todas las
actividades, las transformara y las mandara de vuelta al mismo servidor que
ya las tenia guardadas. Aca esta al lado de los datos y del solver.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from domain.entities.user_activity import ActividadUsuario

DIA_A_INDICE: dict[str, int] = {
    "Lunes": 0,
    "Martes": 1,
    "Miercoles": 2,
    "Miércoles": 2,
    "Jueves": 3,
    "Viernes": 4,
    "Sabado": 5,
    "Sábado": 5,
    "Domingo": 6,
}

_TIPO_FIJO = "FIXED"


@dataclass(frozen=True)
class Aplanado:
    """Las tres canastas que el solver espera, ya separadas."""

    fijas: list[dict[str, Any]]
    ancla: list[dict[str, Any]]
    optimizables: list[dict[str, Any]]


def minuto_del_dia(instante: Any, desfase_utc_minutos: int) -> int:
    """El minuto del dia que el usuario ve, no el que dice el UTC.

    Los turnos se guardan como texto ISO en UTC porque asi los serializa el
    cliente. Pero la hora que importa es la local: una clase a las 10:00 en
    Lima viaja como las 15:00Z, y leerla tal cual la pondria cinco horas mas
    tarde en el horario.

    Es el mismo error que ya tiene `GET /energia/hoy` con la medianoche UTC.
    Aca se evita exigiendo el desfase en vez de suponerlo.
    """
    if isinstance(instante, (int, float)):
        return int(instante) % 1440

    texto = str(instante).replace("Z", "+00:00")
    momento = datetime.fromisoformat(texto)
    minutos = momento.hour * 60 + momento.minute + desfase_utc_minutos
    return minutos % 1440


def _indices_de(dias: list[Any]) -> list[int]:
    return [DIA_A_INDICE[d] for d in dias if d in DIA_A_INDICE]


def _base(
    actividad: ActividadUsuario,
    particion: dict[str, Any],
    desfase: int,
    identificador: str,
) -> dict[str, Any]:
    return {
        "id": identificador,
        "nombre": actividad.nombre or "Actividad sin nombre",
        "tipo": actividad.identidad or "tarea",
        "hora_inicio": minuto_del_dia(particion.get("startHour"), desfase),
        "hora_fin": minuto_del_dia(particion.get("endHour"), desfase),
        "ubicacion_id": None,
        "prioridad": actividad.prioridad if actividad.prioridad is not None else 5,
        "duracion_estimada": particion.get("durationTime") or 0,
        "fecha_limite": actividad.fecha_limite,
        "dificultad": actividad.dificultad or "media",
        "travel_to": particion.get("travelTo"),
        "travel_from": particion.get("travelFrom"),
    }


def _preferencias(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "hora_preferida_inicio": config.get("preferredStartTime"),
        "hora_preferida_fin": config.get("preferredEndTime"),
    }


def _particiones(config: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(config, dict):
        return []
    particiones = config.get("partitions")
    return particiones if isinstance(particiones, list) else []


def aplanar(
    actividades: list[ActividadUsuario], desfase_utc_minutos: int = 0
) -> Aplanado:
    """Separa las actividades en las tres canastas del solver.

    Una actividad sin dias o sin configuracion se omite en vez de romper: el
    usuario puede tener guardado algo a medias, y una excepcion aca dejaria
    sin horario a alguien por una sola definicion incompleta.
    """
    fijas: list[dict[str, Any]] = []
    ancla: list[dict[str, Any]] = []
    optimizables: list[dict[str, Any]] = []

    def guardar_optimizable(entrada: dict[str, Any], es_ancla: bool) -> None:
        (ancla if es_ancla else optimizables).append(entrada)

    for actividad in actividades:
        es_ancla = bool(actividad.es_ancla)
        es_fija = actividad.tipo == _TIPO_FIJO
        permitidos = _indices_de(actividad.dias_habilitados)
        tiene_rango = actividad.dia_desde is not None and actividad.dia_hasta is not None

        # Dia opcional: el solver elige el dia, asi que la definicion aporta
        # un solo turno de referencia y la lista de dias donde puede caer.
        if not es_fija and actividad.dia_opcional:
            primer_dia = _primer_dia(actividad)
            config = actividad.config_por_dia.get(primer_dia) if primer_dia else None
            for indice, particion in enumerate(_particiones(config)):
                entrada = {
                    **_base(
                        actividad,
                        particion,
                        desfase_utc_minutos,
                        f"{actividad.id}-{config.get('groupId')}-{indice}",
                    ),
                    **_preferencias(config),
                    "dias_permitidos": permitidos,
                    "es_ancla": es_ancla or None,
                }
                if tiene_rango:
                    entrada["dia_desde"] = actividad.dia_desde
                    entrada["dia_hasta"] = actividad.dia_hasta
                guardar_optimizable(entrada, es_ancla)
            continue

        # Rango de dias explicito.
        if not es_fija and tiene_rango:
            primer_dia = _primer_dia(actividad)
            config = actividad.config_por_dia.get(primer_dia) if primer_dia else None
            for indice, particion in enumerate(_particiones(config)):
                entrada = {
                    **_base(
                        actividad,
                        particion,
                        desfase_utc_minutos,
                        f"{actividad.id}-{config.get('groupId')}-{indice}",
                    ),
                    **_preferencias(config),
                    "dias_permitidos": permitidos,
                    "dia_desde": actividad.dia_desde,
                    "dia_hasta": actividad.dia_hasta,
                    "es_ancla": es_ancla or None,
                }
                guardar_optimizable(entrada, es_ancla)
            continue

        # Lo habitual: un turno por dia habilitado.
        for dia in actividad.dias_habilitados:
            if dia not in DIA_A_INDICE:
                continue
            config = actividad.config_por_dia.get(dia)
            for indice, particion in enumerate(_particiones(config)):
                entrada = _base(
                    actividad,
                    particion,
                    desfase_utc_minutos,
                    f"{actividad.id}-{config.get('groupId')}-{dia}-{indice}",
                )
                entrada["dia"] = DIA_A_INDICE[dia]

                if es_fija:
                    fijas.append(entrada)
                else:
                    guardar_optimizable(
                        {**entrada, **_preferencias(config), "es_ancla": es_ancla or None},
                        es_ancla,
                    )

    return Aplanado(fijas=fijas, ancla=ancla, optimizables=optimizables)


def _primer_dia(actividad: ActividadUsuario) -> str | None:
    for dia in actividad.dias_habilitados:
        if dia in actividad.config_por_dia:
            return dia
    claves = list(actividad.config_por_dia.keys())
    return claves[0] if claves else None
