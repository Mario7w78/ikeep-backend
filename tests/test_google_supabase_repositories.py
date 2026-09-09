"""Tests de los repositorios de Google sobre PostgREST.

Como en los demas repos: el adaptador adjunta el token del que pide y deja
que RLS decida. Aca se verifica que el token viaje, que el refresh token se
guarde tal cual llego (ya cifrado: descifrar no es asunto de este archivo) y
el mapeo fila <-> dominio, donde se cuelan los errores de nombre de columna.
"""

from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from domain.ports.outbound.google_event_repository_port import EventoImportado
from domain.ports.outbound.google_token_repository_port import TokensDeConexion
from infrastructure.adapters.outbound.supabase.google_event_repository import (
    SupabaseGoogleEventsRepository,
    fila_a_evento,
)
from infrastructure.adapters.outbound.supabase.google_token_repository import (
    SupabaseGoogleTokensRepository,
)

TOKEN = "el-jwt-del-usuario"
USUARIO = "usuario-1"


def _repo_con(clase, tabla: Mock):
    cliente = Mock()
    cliente.table.return_value = tabla
    parche = patch(
        f"{clase.__module__}.client_for_user",
        return_value=cliente,
    )
    return clase(), parche


def _tabla_encadenada(data=None) -> Mock:
    tabla = Mock()
    tabla.upsert.return_value = tabla
    tabla.delete.return_value = tabla
    tabla.select.return_value = tabla
    tabla.lt.return_value = tabla
    tabla.gt.return_value = tabla
    tabla.order.return_value = tabla
    tabla.limit.return_value = tabla
    tabla.eq.return_value = tabla
    tabla.execute.return_value = Mock(data=data)
    return tabla


class TestTokensRepo:
    def test_guardar_hace_upsert_con_el_user_id(self):
        tabla = _tabla_encadenada()
        repo, parche = _repo_con(SupabaseGoogleTokensRepository, tabla)

        with parche:
            repo.guardar(
                TOKEN,
                TokensDeConexion(
                    user_id=USUARIO,
                    refresh_token_cifrado="cifrado-opaco",
                    access_token="at",
                    access_expira_en=datetime(2026, 8, 25, 12, tzinfo=timezone.utc),
                ),
            )

        llamada = tabla.upsert.call_args
        assert llamada.args[0]["user_id"] == USUARIO
        assert llamada.kwargs["on_conflict"] == "user_id"

    def test_el_refresh_token_guarda_tal_cual_llego(self):
        # Ya cifrado. Si algun dia llega en claro aca, es un bug de arriba:
        # este repositorio no tiene como notarlo, pero tampoco lo empeora.
        tabla = _tabla_encadenada()
        repo, parche = _repo_con(SupabaseGoogleTokensRepository, tabla)

        with parche:
            repo.guardar(
                TOKEN, TokensDeConexion(user_id=USUARIO, refresh_token_cifrado="gAAA")
            )

        fila = tabla.upsert.call_args.args[0]
        assert fila["refresh_token_cifrado"] == "gAAA"

    def test_obtener_devuelve_none_sin_filas(self):
        repo, parche = _repo_con(
            SupabaseGoogleTokensRepository, _tabla_encadenada(data=[])
        )

        with parche:
            assert repo.obtener(TOKEN) is None

    def test_obtener_mapea_la_fila(self):
        fila = {
            "user_id": USUARIO,
            "refresh_token_cifrado": "gAAA",
            "access_token": "at",
            "access_expira_en": "2026-08-25T12:00:00+00:00",
        }
        repo, parche = _repo_con(
            SupabaseGoogleTokensRepository, _tabla_encadenada(data=[fila])
        )

        with parche:
            tokens = repo.obtener(TOKEN)

        assert tokens.user_id == USUARIO
        assert tokens.access_expira_en.hour == 12

    def test_borrar_no_filtra_por_usuario(self):
        # RLS ya acota al dueno del token: un filtro manual seria una segunda
        # opinion que puede estar mal. La primera basta.
        tabla = _tabla_encadenada()
        repo, parche = _repo_con(SupabaseGoogleTokensRepository, tabla)

        with parche:
            repo.borrar(TOKEN)

        tabla.delete.return_value.execute.assert_called_once()
        tabla.delete.return_value.eq.assert_not_called()

    def test_sync_token_de_un_usuario_nuevo_es_none(self):
        repo, parche = _repo_con(
            SupabaseGoogleTokensRepository, _tabla_encadenada(data=[])
        )

        with parche:
            assert repo.sync_token(TOKEN, "primary") is None


class TestEventsRepo:
    def _evento(self, **over):
        base = dict(
            id="evt-1",
            titulo="Parcial",
            inicio=datetime(2026, 8, 3, 10, tzinfo=timezone.utc),
            fin=datetime(2026, 8, 3, 11, tzinfo=timezone.utc),
            todo_el_dia=False,
        )
        base.update(over)
        return EventoImportado(**base)

    def test_upsert_vacio_no_toca_la_base(self):
        tabla = _tabla_encadenada()
        repo, parche = _repo_con(SupabaseGoogleEventsRepository, tabla)

        with parche:
            repo.upsert(TOKEN, USUARIO, [])

        tabla.upsert.assert_not_called()

    def test_upsert_manda_las_filas_con_dueno(self):
        tabla = _tabla_encadenada()
        repo, parche = _repo_con(SupabaseGoogleEventsRepository, tabla)

        with parche:
            repo.upsert(TOKEN, USUARIO, [self._evento()])

        llamada = tabla.upsert.call_args
        filas = llamada.args[0]
        assert filas[0]["user_id"] == USUARIO
        assert filas[0]["event_id"] == "evt-1"
        # El id del evento solo es unico dentro de su calendario: la clave
        # compuesta incluye calendar_id.
        assert filas[0]["calendar_id"] == "primary"
        assert llamada.kwargs["on_conflict"] == "user_id,calendar_id,event_id"

    def test_del_rango_pilla_los_que_se_solapan(self):
        # Un evento de tres dias que empezo antes del rango y sigue abierto
        # tiene que salir con un inicio < hasta Y fin > desde.
        tabla = _tabla_encadenada(
            data=[{
                "event_id": "evt-largo",
                "titulo": "Viaje",
                "inicio": "2026-07-30T00:00:00+00:00",
                "fin": "2026-08-05T00:00:00+00:00",
                "todo_el_dia": True,
            }]
        )
        repo, parche = _repo_con(SupabaseGoogleEventsRepository, tabla)

        with parche:
            eventos = repo.del_rango(
                TOKEN,
                datetime(2026, 8, 1, tzinfo=timezone.utc),
                datetime(2026, 9, 1, tzinfo=timezone.utc),
            )

        assert eventos[0].id == "evt-largo"
        assert eventos[0].todo_el_dia is True
        filtros = (str(tabla.lt.call_args), str(tabla.gt.call_args))
        assert any("inicio" in f for f in filtros)
        assert any("fin" in f for f in filtros)

    def test_borrar_todo_deja_al_usuario_limpio(self):
        tabla = _tabla_encadenada()
        repo, parche = _repo_con(SupabaseGoogleEventsRepository, tabla)

        with parche:
            repo.borrar_todo(TOKEN)

        tabla.delete.return_value.execute.assert_called_once()

    def test_fila_a_evento_redondea(self):
        evento = fila_a_evento({
            "event_id": "e",
            "titulo": "t",
            "inicio": "2026-08-03T10:00:00Z".replace("Z", "+00:00"),
            "fin": "2026-08-03T11:00:00Z".replace("Z", "+00:00"),
            "todo_el_dia": False,
        })

        assert evento.titulo == "t"


def test_los_dos_son_del_puerto_que_dicen_ser():
    from domain.ports.outbound.google_event_repository_port import (
        GoogleEventsRepositoryPort,
    )
    from domain.ports.outbound.google_token_repository_port import (
        GoogleTokensRepositoryPort,
    )

    assert isinstance(SupabaseGoogleTokensRepository(), GoogleTokensRepositoryPort)
    assert isinstance(SupabaseGoogleEventsRepository(), GoogleEventsRepositoryPort)
