"""Eventos importados de Google Calendar sobre PostgREST.

Es un cache con dueño: la fuente es Google y esta copia existe para poder
responder el mes sin esperar a Mountain View cada vez.
"""

from datetime import datetime
from typing import Any

from domain.ports.outbound.google_event_repository_port import (
    EventoImportado,
    GoogleEventsRepositoryPort,
)
from infrastructure.adapters.outbound.supabase.client import client_for_user

TABLA = "google_events"


class SupabaseGoogleEventsRepository(GoogleEventsRepositoryPort):
    def upsert(
        self, access_token: str, user_id: str, eventos: list[EventoImportado]
    ) -> None:
        if not eventos:
            return
        (
            client_for_user(access_token)
            .table(TABLA)
            .upsert(
                [_evento_a_fila(user_id, e) for e in eventos],
                on_conflict="user_id,calendar_id,event_id",
            )
            .execute()
        )

    def del_rango(
        self, access_token: str, desde: datetime, hasta: datetime
    ) -> list[EventoImportado]:
        # Se solapa con [desde, hasta]: arranca antes de que termine el rango
        # y termina despues de que empiece. Un `gte/gte` simple perderia el
        # evento de tres dias que empezo el mes pasado y sigue abierto.
        respuesta = (
            client_for_user(access_token)
            .table(TABLA)
            .select("*")
            .lt("inicio", hasta.isoformat())
            .gt("fin", desde.isoformat())
            .order("inicio")
            .execute()
        )
        return [fila_a_evento(fila) for fila in (respuesta.data or [])]

    def borrar_todo(self, access_token: str) -> None:
        # RLS acota al dueno del token; el `neq` con un uuid que ningun usuario
        # tiene cumple el requisito de PostgREST de borrar con filtro.
        client_for_user(access_token).table(TABLA).delete().neq(
            "user_id", "00000000-0000-0000-0000-000000000000"
        ).execute()


def _evento_a_fila(user_id: str, evento: EventoImportado) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "event_id": evento.id,
        "calendar_id": evento.calendar_id,
        "titulo": evento.titulo,
        "inicio": evento.inicio.isoformat(),
        "fin": evento.fin.isoformat(),
        "todo_el_dia": evento.todo_el_dia,
    }


def fila_a_evento(fila: dict[str, Any]) -> EventoImportado:
    return EventoImportado(
        id=fila["event_id"],
        titulo=fila["titulo"],
        inicio=_a_momento(fila["inicio"]),
        fin=_a_momento(fila["fin"]),
        calendar_id=fila.get("calendar_id") or "primary",
        todo_el_dia=bool(fila.get("todo_el_dia", False)),
    )


def _a_momento(valor) -> datetime:
    return valor if isinstance(valor, datetime) else datetime.fromisoformat(valor)
