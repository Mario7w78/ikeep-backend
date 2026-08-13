"""Excepciones del calendario sobre PostgREST."""

from datetime import date
from typing import Any

from domain.ports.outbound.exception_repository_port import ExcepcionesRepositoryPort
from domain.services.calendar.expansion import Excepcion
from infrastructure.adapters.outbound.supabase.client import client_for_user

TABLA = "activity_exceptions"


def _a_fecha(valor: Any) -> date:
    return valor if isinstance(valor, date) else date.fromisoformat(str(valor)[:10])


def _de_fila(fila: dict[str, Any]) -> Excepcion:
    return Excepcion(
        activity_id=fila["activity_id"],
        fecha=_a_fecha(fila["fecha"]),
        tipo=fila["tipo"],
        nueva_fecha=_a_fecha(fila["nueva_fecha"]) if fila.get("nueva_fecha") else None,
    )


class SupabaseExcepcionesRepository(ExcepcionesRepositoryPort):
    def del_rango(self, access_token: str, desde: date, hasta: date) -> list[Excepcion]:
        # Se consulta por la fecha original O por la nueva: una ocurrencia
        # movida hacia adentro del rango tiene que aparecer aunque su fecha
        # original cayera afuera.
        filtro = (
            f"and(fecha.gte.{desde.isoformat()},fecha.lte.{hasta.isoformat()}),"
            f"and(nueva_fecha.gte.{desde.isoformat()},nueva_fecha.lte.{hasta.isoformat()})"
        )
        respuesta = (
            client_for_user(access_token)
            .table(TABLA)
            .select("activity_id, fecha, tipo, nueva_fecha")
            .or_(filtro)
            .execute()
        )
        return [_de_fila(f) for f in (respuesta.data or [])]

    def guardar(self, access_token: str, user_id: str, excepcion: Excepcion) -> None:
        client_for_user(access_token).table(TABLA).upsert(
            {
                "user_id": user_id,
                "activity_id": excepcion.activity_id,
                "fecha": excepcion.fecha.isoformat(),
                "tipo": excepcion.tipo,
                "nueva_fecha": (
                    excepcion.nueva_fecha.isoformat() if excepcion.nueva_fecha else None
                ),
            },
            on_conflict="user_id,activity_id,fecha",
        ).execute()

    def borrar(self, access_token: str, activity_id: str, fecha: date) -> None:
        (
            client_for_user(access_token)
            .table(TABLA)
            .delete()
            .eq("activity_id", activity_id)
            .eq("fecha", fecha.isoformat())
            .execute()
        )
