"""Tests del repositorio de actividades sobre PostgREST.

El adaptador no filtra por usuario: adjunta el token del que pide y deja que
RLS decida. Estos tests verifican justamente eso —que el token viaje— ademas
del mapeo entre la fila y la entidad de dominio, que es donde se cuelan los
errores de nombre de columna.
"""

from unittest.mock import Mock, patch

import pytest

from domain.entities.user_activity import ActividadUsuario
from infrastructure.adapters.outbound.supabase.user_activity_repository import (
    SupabaseActividadUsuarioRepository,
    fila_a_dominio,
    dominio_a_fila,
)

TOKEN = "el-jwt-del-usuario"

FILA = {
    "id": "act-1",
    "user_id": "usuario-1",
    "title": "Calculo",
    "type": "fija",
    "identity": "clase",
    "priority": 1,
    "difficulty": "alta",
    "deadline": None,
    "days_enabled": ["martes", "jueves"],
    "days_config": {"martes": {"partitions": []}},
    "optional_day": False,
    "day_from": None,
    "day_to": None,
    "is_anchor": True,
}


def _repo_con(tabla: Mock) -> tuple[SupabaseActividadUsuarioRepository, Mock]:
    cliente = Mock()
    cliente.table.return_value = tabla
    parche = patch(
        "infrastructure.adapters.outbound.supabase.user_activity_repository."
        "client_for_user",
        return_value=cliente,
    )
    return SupabaseActividadUsuarioRepository(), parche


class TestMapeo:
    def test_la_fila_se_convierte_en_entidad(self):
        actividad = fila_a_dominio(FILA)

        assert actividad.id == "act-1"
        assert actividad.propietario_id == "usuario-1"
        assert actividad.nombre == "Calculo"
        assert actividad.dias_habilitados == ["martes", "jueves"]
        assert actividad.es_ancla is True

    def test_las_columnas_ausentes_toman_el_default(self):
        """Una fila vieja sin columnas nuevas no debe romper la lectura."""
        actividad = fila_a_dominio({"id": "x", "user_id": "u", "title": "t", "type": "fija"})

        assert actividad.identidad == "tarea"
        assert actividad.prioridad == 3
        assert actividad.dificultad == "media"
        assert actividad.dias_habilitados == []
        assert actividad.es_ancla is False

    def test_la_entidad_vuelve_a_los_nombres_de_la_tabla(self):
        fila = dominio_a_fila(fila_a_dominio(FILA))

        assert fila == FILA

    def test_el_viaje_de_ida_y_vuelta_no_pierde_nada(self):
        assert fila_a_dominio(dominio_a_fila(fila_a_dominio(FILA))) == fila_a_dominio(FILA)


class TestLectura:
    def test_listar_usa_el_token_de_quien_pide(self):
        tabla = Mock()
        tabla.select.return_value.execute.return_value = Mock(data=[FILA])
        repo, parche = _repo_con(tabla)

        with parche as client_for_user:
            actividades = repo.list_all(TOKEN)

        client_for_user.assert_called_once_with(TOKEN)
        assert [a.id for a in actividades] == ["act-1"]

    def test_listar_sin_filas_devuelve_lista_vacia(self):
        tabla = Mock()
        tabla.select.return_value.execute.return_value = Mock(data=None)
        repo, parche = _repo_con(tabla)

        with parche:
            assert repo.list_all(TOKEN) == []

    def test_obtener_devuelve_none_cuando_no_hay_fila(self):
        """RLS oculta lo ajeno: 'de otro' y 'no existe' son la misma respuesta."""
        tabla = Mock()
        tabla.select.return_value.eq.return_value.execute.return_value = Mock(data=[])
        repo, parche = _repo_con(tabla)

        with parche:
            assert repo.get(TOKEN, "act-1") is None

    def test_obtener_devuelve_la_actividad(self):
        tabla = Mock()
        tabla.select.return_value.eq.return_value.execute.return_value = Mock(data=[FILA])
        repo, parche = _repo_con(tabla)

        with parche:
            actividad = repo.get(TOKEN, "act-1")

        assert actividad is not None
        assert actividad.nombre == "Calculo"


class TestEscritura:
    def test_guardar_hace_upsert_y_devuelve_lo_guardado(self):
        tabla = Mock()
        tabla.upsert.return_value.execute.return_value = Mock(data=[FILA])
        repo, parche = _repo_con(tabla)

        with parche:
            guardada = repo.save(TOKEN, fila_a_dominio(FILA))

        tabla.upsert.assert_called_once_with(FILA)
        assert guardada.id == "act-1"

    def test_guardar_sin_respuesta_devuelve_lo_enviado(self):
        """PostgREST puede no devolver representacion; no es un error."""
        tabla = Mock()
        tabla.upsert.return_value.execute.return_value = Mock(data=[])
        repo, parche = _repo_con(tabla)
        actividad = fila_a_dominio(FILA)

        with parche:
            assert repo.save(TOKEN, actividad) == actividad

    def test_borrar_filtra_por_id(self):
        tabla = Mock()
        repo, parche = _repo_con(tabla)

        with parche:
            repo.delete(TOKEN, "act-1")

        tabla.delete.return_value.eq.assert_called_once_with("id", "act-1")
