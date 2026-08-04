"""Tests de la fuente de datos del asistente.

Traduce lo que guardan los repositorios a lo que el asistente entiende. El
horario guardado usa el vocabulario del cliente —dias por nombre, horas como
"HH:mm"— y el contexto del modelo usa minutos e ids. Aca se cruza esa frontera,
que es donde se cuelan los errores silenciosos.
"""

from unittest.mock import Mock

import pytest

from domain.entities.stored_schedule import HorarioGuardado
from domain.entities.user_activity import ActividadUsuario
from infrastructure.adapters.outbound.assistant.data_source import (
    RepositorioFuenteDeDatos,
    a_minutos,
    indice_de_dia,
)


class TestConversiones:
    @pytest.mark.parametrize(
        "texto,esperado", [("00:00", 0), ("10:00", 600), ("23:59", 1439), ("9:05", 545)]
    )
    def test_convierte_horas_a_minutos(self, texto, esperado):
        assert a_minutos(texto) == esperado

    @pytest.mark.parametrize("invalido", ["", "manana", "25:00", None, "10"])
    def test_una_hora_ilegible_devuelve_none(self, invalido):
        """Preferible perder un bloque que romper la agenda entera."""
        assert a_minutos(invalido) is None

    @pytest.mark.parametrize(
        "dia,indice",
        [("Lunes", 0), ("lunes", 0), ("Miercoles", 2), ("Miércoles", 2), ("Domingo", 6)],
    )
    def test_convierte_dias_a_indice(self, dia, indice):
        assert indice_de_dia(dia) == indice

    def test_un_dia_desconocido_devuelve_none(self):
        assert indice_de_dia("Caturday") is None


class TestAgenda:
    def _fuente(self, horario=None, actividades=None):
        horarios = Mock()
        horarios.get.return_value = horario
        actividades_repo = Mock()
        actividades_repo.list_all.return_value = actividades or []
        return RepositorioFuenteDeDatos(
            access_token="tok",
            horarios=horarios,
            actividades=actividades_repo,
        )

    def test_sin_horario_la_agenda_esta_vacia(self):
        assert self._fuente().agenda() == []

    def test_traduce_un_bloque_programado(self):
        horario = HorarioGuardado(
            propietario_id="u1",
            actividades_programadas=[
                {
                    "activity": {"id": "act-1", "title": "Calculo"},
                    "day": "Martes",
                    "assignedStartTime": "10:00",
                    "assignedEndTime": "12:00",
                }
            ],
        )

        agenda = self._fuente(horario=horario).agenda()

        assert len(agenda) == 1
        assert agenda[0].id_actividad == "act-1"
        assert agenda[0].nombre == "Calculo"
        assert agenda[0].dia == 1
        assert agenda[0].inicio == 600
        assert agenda[0].fin == 720

    def test_descarta_los_bloques_ilegibles_sin_perder_los_demas(self):
        """Un item roto no deberia dejar al asistente sin agenda."""
        horario = HorarioGuardado(
            propietario_id="u1",
            actividades_programadas=[
                {"activity": {"id": "a", "title": "Rota"}, "day": "Ayer",
                 "assignedStartTime": "10:00", "assignedEndTime": "12:00"},
                {"activity": {"id": "b", "title": "Buena"}, "day": "Lunes",
                 "assignedStartTime": "08:00", "assignedEndTime": "09:00"},
            ],
        )

        agenda = self._fuente(horario=horario).agenda()

        assert [b.id_actividad for b in agenda] == ["b"]

    def test_un_bloque_sin_actividad_se_descarta(self):
        """Los huecos de viaje vienen sin activity."""
        horario = HorarioGuardado(
            propietario_id="u1",
            actividades_programadas=[
                {"activity": None, "day": "Lunes",
                 "assignedStartTime": "08:00", "assignedEndTime": "09:00"}
            ],
        )

        assert self._fuente(horario=horario).agenda() == []


class TestBusqueda:
    def _fuente_con(self, *nombres):
        actividades_repo = Mock()
        actividades_repo.list_all.return_value = [
            ActividadUsuario(
                id=f"act-{i}", propietario_id="u1", nombre=n, tipo="fija"
            )
            for i, n in enumerate(nombres)
        ]
        horarios = Mock()
        horarios.get.return_value = None
        return RepositorioFuenteDeDatos(
            access_token="tok", horarios=horarios, actividades=actividades_repo
        )

    def test_encuentra_ignorando_acentos(self):
        resultados = self._fuente_con("Matemática Discreta").buscar_actividad(
            "matematica"
        )

        assert len(resultados) == 1
        assert resultados[0]["id"] == "act-0"

    def test_devuelve_todas_las_coincidencias(self):
        """Con varias, el modelo tiene que preguntar cual, no elegir."""
        resultados = self._fuente_con(
            "Clase de Calculo", "Tarea de Calculo"
        ).buscar_actividad("calculo")

        assert len(resultados) == 2

    def test_sin_coincidencias_devuelve_lista_vacia(self):
        assert self._fuente_con("Calculo").buscar_actividad("quimica") == []
