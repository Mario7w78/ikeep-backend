"""Completados de actividades sobre PostgREST."""

from datetime import date
from typing import Any

from domain.ports.outbound.completion_repository_port import CompletadosRepositoryPort
from infrastructure.adapters.outbound.supabase.client import client_for_user

TABLA = "activity_completions"


class SupabaseCompletadosRepository(CompletadosRepositoryPort):
    def marcar(
        self, access_token: str, user_id: str, activity_id: str, fecha: date
    ) -> None:
        # upsert y no insert: el cliente puede reintentar tras un fallo de red
        # y el usuario puede tocar dos veces. Las dos cosas dicen lo mismo.
        client_for_user(access_token).table(TABLA).upsert(
            {
                "user_id": user_id,
                "activity_id": activity_id,
                "fecha": fecha.isoformat(),
            },
            on_conflict="user_id,activity_id,fecha",
        ).execute()

    def desmarcar(self, access_token: str, activity_id: str, fecha: date) -> None:
        (
            client_for_user(access_token)
            .table(TABLA)
            .delete()
            .eq("activity_id", activity_id)
            .eq("fecha", fecha.isoformat())
            .execute()
        )

    def del_dia(self, access_token: str, fecha: date) -> list[str]:
        respuesta = (
            client_for_user(access_token)
            .table(TABLA)
            .select("activity_id")
            .eq("fecha", fecha.isoformat())
            .execute()
        )
        return [fila["activity_id"] for fila in (respuesta.data or [])]

    def dias_con_actividad(self, access_token: str, desde: date) -> set[date]:
        respuesta = (
            client_for_user(access_token)
            .table(TABLA)
            .select("fecha")
            .gte("fecha", desde.isoformat())
            .execute()
        )
        return {_a_fecha(fila["fecha"]) for fila in (respuesta.data or [])}


def _a_fecha(valor: Any) -> date:
    return valor if isinstance(valor, date) else date.fromisoformat(str(valor)[:10])
