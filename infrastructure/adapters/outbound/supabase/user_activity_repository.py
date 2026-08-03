"""Repositorio de actividades sobre PostgREST.

El adaptador nunca agrega `where user_id = ...`. Adjunta el token de quien
pide y deja que RLS resuelva la visibilidad en Postgres. Reimplementar ese
filtro aca no agregaria seguridad —RLS ya lo hace, y no se puede saltear
desde el cliente— pero si agregaria un segundo lugar donde olvidarlo.
"""

from typing import Any

from domain.entities.user_activity import ActividadUsuario
from domain.ports.outbound.user_activity_repository_port import (
    ActividadUsuarioRepositoryPort,
)
from infrastructure.adapters.outbound.supabase.client import client_for_user

TABLA = "activities"


def fila_a_dominio(fila: dict[str, Any]) -> ActividadUsuario:
    """Convierte una fila de PostgREST en la entidad.

    Los defaults son deliberados: una fila escrita antes de que existiera una
    columna debe poder leerse igual, en vez de tumbar la lista entera.
    """
    return ActividadUsuario(
        id=str(fila["id"]),
        propietario_id=str(fila["user_id"]),
        nombre=fila["title"],
        tipo=fila["type"],
        identidad=fila.get("identity") or "tarea",
        prioridad=fila.get("priority") if fila.get("priority") is not None else 3,
        dificultad=fila.get("difficulty") or "media",
        fecha_limite=fila.get("deadline"),
        dias_habilitados=fila.get("days_enabled") or [],
        config_por_dia=fila.get("days_config") or {},
        dia_opcional=bool(fila.get("optional_day", False)),
        dia_desde=fila.get("day_from"),
        dia_hasta=fila.get("day_to"),
        es_ancla=bool(fila.get("is_anchor", False)),
    )


def dominio_a_fila(actividad: ActividadUsuario) -> dict[str, Any]:
    return {
        "id": actividad.id,
        "user_id": actividad.propietario_id,
        "title": actividad.nombre,
        "type": actividad.tipo,
        "identity": actividad.identidad,
        "priority": actividad.prioridad,
        "difficulty": actividad.dificultad,
        "deadline": actividad.fecha_limite,
        "days_enabled": actividad.dias_habilitados,
        "days_config": actividad.config_por_dia,
        "optional_day": actividad.dia_opcional,
        "day_from": actividad.dia_desde,
        "day_to": actividad.dia_hasta,
        "is_anchor": actividad.es_ancla,
    }


class SupabaseActividadUsuarioRepository(ActividadUsuarioRepositoryPort):
    def list_all(self, access_token: str) -> list[ActividadUsuario]:
        respuesta = client_for_user(access_token).table(TABLA).select("*").execute()
        return [fila_a_dominio(f) for f in (respuesta.data or [])]

    def get(self, access_token: str, activity_id: str) -> ActividadUsuario | None:
        respuesta = (
            client_for_user(access_token)
            .table(TABLA)
            .select("*")
            .eq("id", activity_id)
            .execute()
        )
        filas = respuesta.data or []
        # Una actividad ajena y una inexistente son indistinguibles a
        # proposito: RLS ya oculto la ajena, y responder distinto revelaria
        # que ese id existe.
        return fila_a_dominio(filas[0]) if filas else None

    def save(
        self, access_token: str, actividad: ActividadUsuario
    ) -> ActividadUsuario:
        respuesta = (
            client_for_user(access_token)
            .table(TABLA)
            .upsert(dominio_a_fila(actividad))
            .execute()
        )
        filas = respuesta.data or []
        # PostgREST puede responder sin representacion segun como este
        # configurado; que no la devuelva no significa que no haya guardado.
        return fila_a_dominio(filas[0]) if filas else actividad

    def delete(self, access_token: str, activity_id: str) -> None:
        client_for_user(access_token).table(TABLA).delete().eq(
            "id", activity_id
        ).execute()
