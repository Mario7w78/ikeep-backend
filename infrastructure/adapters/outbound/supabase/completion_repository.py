"""Completados de actividades sobre PostgREST."""

from datetime import date
from typing import Any

from domain.ports.outbound.completion_repository_port import (
    CompletadosRepositoryPort,
    ConteosPorArea,
)
from domain.services.rewards.completion import EstadoCompletado, OrigenCompletado
from infrastructure.adapters.outbound.supabase.client import client_for_user

TABLA = "activity_completions"


class SupabaseCompletadosRepository(CompletadosRepositoryPort):
    def marcar(
        self,
        access_token: str,
        user_id: str,
        activity_id: str,
        fecha: date,
        estado: EstadoCompletado = EstadoCompletado.HECHA,
        origen: OrigenCompletado = OrigenCompletado.MANUAL,
    ) -> None:
        # upsert y no insert: el cliente puede reintentar tras un fallo de red
        # y el usuario puede tocar dos veces. Las dos cosas dicen lo mismo.
        #
        # Y cambiar de opinion tambien: marcar hecha algo que se habia dicho
        # no hecha pisa la fila, no crea una segunda.
        client_for_user(access_token).table(TABLA).upsert(
            {
                "user_id": user_id,
                "activity_id": activity_id,
                "fecha": fecha.isoformat(),
                "estado": estado.value,
                "origen": origen.value,
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
        # Filtrado en la base y no en memoria: una ocurrencia marcada como no
        # hecha es una respuesta del usuario, no progreso, y contarla haria
        # que decir la verdad subiera el anillo del dia.
        respuesta = (
            client_for_user(access_token)
            .table(TABLA)
            .select("activity_id")
            .eq("fecha", fecha.isoformat())
            .eq("estado", EstadoCompletado.HECHA.value)
            .execute()
        )
        return [fila["activity_id"] for fila in (respuesta.data or [])]

    def estados_del_dia(self, access_token: str, fecha: date) -> dict[str, str]:
        respuesta = (
            client_for_user(access_token)
            .table(TABLA)
            .select("activity_id, estado")
            .eq("fecha", fecha.isoformat())
            .execute()
        )
        return {
            fila["activity_id"]: fila.get("estado", EstadoCompletado.HECHA.value)
            for fila in (respuesta.data or [])
        }

    def dias_con_actividad(self, access_token: str, desde: date) -> set[date]:
        respuesta = (
            client_for_user(access_token)
            .table(TABLA)
            .select("fecha")
            .gte("fecha", desde.isoformat())
            .eq("estado", EstadoCompletado.HECHA.value)
            .execute()
        )
        return {_a_fecha(fila["fecha"]) for fila in (respuesta.data or [])}

    def conteos_por_area(self, access_token: str, desde: date) -> ConteosPorArea:
        # Una sola consulta y dos agrupaciones. Pedir el historico y la
        # ventana por separado serian dos viajes contra un servidor que tarda
        # en despertar, para datos que salen de las mismas filas.
        #
        # El area vive en `activities`: una fila de completado apunta a una
        # definicion, y el area es de la definicion. Se pide embebida en vez
        # de traer las actividades aparte y cruzarlas en memoria.
        respuesta = (
            client_for_user(access_token)
            .table(TABLA)
            .select("fecha, activities(area)")
            .eq("estado", EstadoCompletado.HECHA.value)
            .execute()
        )

        historico: dict[str, int] = {}
        recientes: dict[str, int] = {}
        for fila in respuesta.data or []:
            area = _area_de(fila)
            historico[area] = historico.get(area, 0) + 1
            if _a_fecha(fila["fecha"]) >= desde:
                recientes[area] = recientes.get(area, 0) + 1

        return ConteosPorArea(historico=historico, recientes=recientes)


def _a_fecha(valor: Any) -> date:
    return valor if isinstance(valor, date) else date.fromisoformat(str(valor)[:10])



def _area_de(fila: dict[str, Any]) -> str:
    """El area de la actividad a la que apunta el completado.

    Segun la version de PostgREST la relacion embebida llega como objeto o
    como lista de uno; las dos formas dicen lo mismo. Una fila sin area cuenta
    igual: perderla haria que el total de los petalos no cuadre con el
    historial, y esa discrepancia no se detecta mirando.
    """
    actividad = fila.get("activities") or {}
    if isinstance(actividad, list):
        actividad = actividad[0] if actividad else {}
    return actividad.get("area") or "estudio"
