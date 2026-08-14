"""Horario guardado e historial de energia sobre PostgREST."""

from datetime import date, datetime, timedelta, timezone
from typing import Any

from domain.entities.energy_record import DIAS_DE_RETENCION, RegistroEnergia
from domain.entities.stored_schedule import HorarioGuardado
from domain.ports.outbound.schedule_repository_port import (
    EnergiaRepositoryPort,
    HorarioRepositoryPort,
)
from infrastructure.adapters.outbound.supabase.client import client_for_user

TABLA_HORARIOS = "schedules"
TABLA_ENERGIA = "energy_records"


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def horario_de_fila(fila: dict[str, Any]) -> HorarioGuardado:
    return HorarioGuardado(
        propietario_id=str(fila["user_id"]),
        estado=fila.get("estado"),
        mensaje=fila.get("mensaje"),
        recomendaciones=fila.get("recomendaciones") or [],
        tareas_omitidas=fila.get("tareas_omitidas") or [],
        actividades_programadas=fila.get("scheduled_activities") or [],
        creado_en=fila.get("created_at"),
    )


def energia_de_fila(fila: dict[str, Any], propietario_id: str) -> RegistroEnergia:
    return RegistroEnergia(
        propietario_id=propietario_id,
        momento=fila["timestamp"],
        nivel=fila["nivel"],
        dia_semana=fila["dia_semana"],
        contexto=fila.get("contexto"),
    )


class SupabaseHorarioRepository(HorarioRepositoryPort):
    def get(self, access_token: str) -> HorarioGuardado | None:
        respuesta = (
            client_for_user(access_token).table(TABLA_HORARIOS).select("*").execute()
        )
        filas = respuesta.data or []
        return horario_de_fila(filas[0]) if filas else None

    def save(self, access_token: str, horario: HorarioGuardado) -> HorarioGuardado:
        fila = {
            "user_id": horario.propietario_id,
            "estado": horario.estado,
            "mensaje": horario.mensaje,
            "recomendaciones": horario.recomendaciones,
            "tareas_omitidas": horario.tareas_omitidas,
            "scheduled_activities": horario.actividades_programadas,
            "updated_at": _ahora().isoformat(),
        }
        # No se manda `id`: Postgres es dueño del suyo, y el conflicto se
        # resuelve por user_id, que es unico —un horario vigente por persona.
        respuesta = (
            client_for_user(access_token)
            .table(TABLA_HORARIOS)
            .upsert(fila, on_conflict="user_id")
            .execute()
        )
        filas = respuesta.data or []
        return horario_de_fila(filas[0]) if filas else horario

    def delete(self, access_token: str) -> None:
        # neq sobre una columna que nunca es vacia: PostgREST exige un filtro
        # para borrar, y RLS ya limito el alcance a las filas del usuario.
        client_for_user(access_token).table(TABLA_HORARIOS).delete().neq(
            "user_id", ""
        ).execute()


class SupabaseEnergiaRepository(EnergiaRepositoryPort):
    def add(self, access_token: str, registro: RegistroEnergia) -> RegistroEnergia:
        cliente = client_for_user(access_token)
        cliente.table(TABLA_ENERGIA).insert(
            {
                "user_id": registro.propietario_id,
                "timestamp": registro.momento,
                "nivel": registro.nivel,
                "dia_semana": registro.dia_semana,
                "contexto": registro.contexto,
            }
        ).execute()

        # La poda va junto al alta y no en una tarea aparte: sin scheduler,
        # este es el unico momento garantizado en que alguien la ejecutaria.
        corte = (_ahora() - timedelta(days=DIAS_DE_RETENCION)).isoformat()
        cliente.table(TABLA_ENERGIA).delete().lt("timestamp", corte).execute()

        return registro

    def history(self, access_token: str, dias: int) -> list[RegistroEnergia]:
        corte = (_ahora() - timedelta(days=dias)).isoformat()
        respuesta = (
            client_for_user(access_token)
            .table(TABLA_ENERGIA)
            .select("*")
            .gt("timestamp", corte)
            .order("timestamp", desc=True)
            .execute()
        )
        filas = respuesta.data or []
        return [energia_de_fila(f, str(f.get("user_id", ""))) for f in filas]

    def dias_con_registro(
        self, access_token: str, desde: date, desfase_utc_minutos: int = 0
    ) -> set[date]:
        # Se traen los instantes y se convierten aca al dia del usuario. Hacer
        # el corte en SQL exigiria que Postgres conociera el huso, y el huso
        # viaja en cada peticion, no en la base.
        desplazamiento = timedelta(minutes=desfase_utc_minutos)
        # Se pide desde un dia antes: un reporte de las 23:00 del dia anterior
        # en un huso adelantado puede caer dentro del rango del usuario.
        limite = (desde - timedelta(days=1)).isoformat()
        respuesta = (
            client_for_user(access_token)
            .table(TABLA_ENERGIA)
            .select("timestamp")
            .gte("timestamp", limite)
            .execute()
        )

        dias: set[date] = set()
        for fila in respuesta.data or []:
            momento = fila.get("timestamp")
            if not momento:
                continue
            try:
                instante = datetime.fromisoformat(str(momento).replace("Z", "+00:00"))
            except ValueError:
                continue
            local = (instante + desplazamiento).date()
            if local >= desde:
                dias.add(local)
        return dias

    def reported_today(self, access_token: str, desfase_utc_minutos: int = 0) -> bool:
        # Desde la medianoche DEL USUARIO, no la UTC.
        #
        # Se calcula corriendo el reloj al huso del cliente, truncando ahi el
        # dia, y volviendo a UTC para comparar contra la columna. Hacerlo al
        # reves —truncar en UTC y despues correr— daria la medianoche de otro
        # dia cuando el desfase cruza la medianoche.
        desplazamiento = timedelta(minutes=desfase_utc_minutos)
        local = _ahora() + desplazamiento
        inicio = local.replace(hour=0, minute=0, second=0, microsecond=0) - desplazamiento
        respuesta = (
            client_for_user(access_token)
            .table(TABLA_ENERGIA)
            .select("timestamp")
            .gte("timestamp", inicio.isoformat())
            .limit(1)
            .execute()
        )
        return bool(respuesta.data)
