"""Perfil y ajustes sobre PostgREST.

Como en el resto de los adaptadores, el scope por usuario lo resuelve RLS con
el token que se adjunta; aca no se filtra a mano.
"""

from datetime import datetime, timezone
from typing import Any

from domain.entities.profile import Perfil
from domain.entities.user_settings import AjustesUsuario
from domain.ports.outbound.profile_repository_port import (
    AjustesRepositoryPort,
    PerfilRepositoryPort,
)
from infrastructure.adapters.outbound.supabase.client import client_for_user

TABLA_PERFILES = "profiles"
TABLA_AJUSTES = "user_settings"

# Nombre en el dominio -> columna. Se declara una sola vez para que el patch
# parcial y la lectura no puedan divergir.
COLUMNAS_AJUSTES = {
    "inicio_dia": "start_hour",
    "fin_dia": "end_hour",
    "dia_inicio": "dia_inicio",
    "dias_totales": "dias_totales",
    "inicio_por_dia": "per_day_start_hours",
    "fin_por_dia": "per_day_end_hours",
    "patron_energia_manual": "custom_energy_pattern",
}


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def perfil_de_fila(fila: dict[str, Any]) -> Perfil:
    return Perfil(
        id=str(fila["id"]),
        nombre_usuario=fila.get("username"),
        nivel_energia=fila.get("energy_level"),
        hora_despertar=fila.get("wake_up_time"),
        hora_dormir=fila.get("sleep_time"),
    )


class SupabasePerfilRepository(PerfilRepositoryPort):
    def get(self, access_token: str) -> Perfil | None:
        # Sin .eq(): RLS ya limita la tabla a la fila del usuario, y volver a
        # filtrar exigiria pasar un id que el token ya contiene.
        respuesta = (
            client_for_user(access_token).table(TABLA_PERFILES).select("*").execute()
        )
        filas = respuesta.data or []
        return perfil_de_fila(filas[0]) if filas else None

    def save(self, access_token: str, perfil: Perfil) -> Perfil:
        fila = {
            "id": perfil.id,
            "username": perfil.nombre_usuario,
            "energy_level": perfil.nivel_energia,
            "wake_up_time": perfil.hora_despertar,
            "sleep_time": perfil.hora_dormir,
            "updated_at": _ahora(),
        }
        respuesta = (
            client_for_user(access_token).table(TABLA_PERFILES).upsert(fila).execute()
        )
        filas = respuesta.data or []
        return perfil_de_fila(filas[0]) if filas else perfil

    def clear(self, access_token: str) -> None:
        client_for_user(access_token).table(TABLA_PERFILES).update(
            {
                "username": None,
                "energy_level": None,
                "wake_up_time": None,
                "sleep_time": None,
                "updated_at": _ahora(),
            }
        ).neq("id", "").execute()


class SupabaseAjustesRepository(AjustesRepositoryPort):
    def get(self, access_token: str, user_id: str) -> AjustesUsuario:
        respuesta = (
            client_for_user(access_token).table(TABLA_AJUSTES).select("*").execute()
        )
        filas = respuesta.data or []
        if not filas:
            # Un usuario sin fila no es un caso excepcional: es alguien que
            # nunca cambio nada. Los defaults de la entidad son la respuesta.
            return AjustesUsuario(propietario_id=user_id)

        fila = filas[0]
        base = AjustesUsuario(propietario_id=user_id)
        return AjustesUsuario(
            propietario_id=user_id,
            **{
                campo: (
                    fila[columna]
                    if fila.get(columna) is not None
                    else getattr(base, campo)
                )
                for campo, columna in COLUMNAS_AJUSTES.items()
            },
        )

    def patch(
        self, access_token: str, user_id: str, cambios: dict
    ) -> AjustesUsuario:
        fila = {
            COLUMNAS_AJUSTES[campo]: valor
            for campo, valor in cambios.items()
            if campo in COLUMNAS_AJUSTES
        }
        fila["user_id"] = user_id
        fila["updated_at"] = _ahora()

        client_for_user(access_token).table(TABLA_AJUSTES).upsert(fila).execute()
        # Se relee en vez de reconstruir: el upsert parcial deja el resto de
        # las columnas como estaban y solo la base sabe cuales son.
        return self.get(access_token, user_id)
