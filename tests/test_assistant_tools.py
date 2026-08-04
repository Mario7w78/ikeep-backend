"""Tests del catalogo de tools.

Las definiciones son datos, no logica, asi que lo que se verifica es que sean
consistentes con los schemas que el resto del sistema espera. Un nombre de
parametro que no coincide no rompe nada aca: rompe en produccion, cuando el
modelo emite algo que despues no valida.
"""

import pytest

from domain.services.assistant.tools import (
    TOOLS,
    TOOLS_DE_LECTURA,
    TOOLS_DE_PROPUESTA,
    definiciones_openai,
    es_tool_conocida,
)
from schemas.assistant import BorradorPatch


class TestCatalogo:
    def test_estan_las_ocho_tools(self):
        assert set(TOOLS) == {
            "actualizar_borrador",
            "consultar_agenda",
            "buscar_actividad",
            "sugerir_tarea",
            "proponer_actividad",
            "proponer_modificacion",
            "proponer_eliminacion",
            "proponer_regeneracion",
        }

    def test_lectura_y_propuesta_no_se_solapan(self):
        """Se comportan distinto: una de lectura devuelve su resultado al
        modelo en el mismo turno, una de propuesta termina el turno."""
        assert not (TOOLS_DE_LECTURA & TOOLS_DE_PROPUESTA)

    def test_actualizar_borrador_no_es_ninguna_de_las_dos(self):
        """No devuelve nada al modelo ni termina el turno: solo acumula."""
        assert "actualizar_borrador" not in TOOLS_DE_LECTURA
        assert "actualizar_borrador" not in TOOLS_DE_PROPUESTA

    def test_reconoce_las_tools_del_catalogo(self):
        assert es_tool_conocida("consultar_agenda")

    def test_una_tool_inventada_no_se_reconoce(self):
        """El modelo puede alucinar nombres; hay que poder rechazarlos sin
        que revienten el turno."""
        assert not es_tool_conocida("borrar_todo")


class TestDefinicionesOpenAI:
    def test_tienen_la_forma_que_espera_la_api(self):
        for definicion in definiciones_openai():
            assert definicion["type"] == "function"
            assert "name" in definicion["function"]
            assert "description" in definicion["function"]
            assert definicion["function"]["parameters"]["type"] == "object"

    def test_hay_una_definicion_por_tool(self):
        nombres = {d["function"]["name"] for d in definiciones_openai()}

        assert nombres == set(TOOLS)

    def test_toda_tool_describe_para_que_sirve(self):
        """Una descripcion vacia deja al modelo eligiendo a ciegas."""
        for definicion in definiciones_openai():
            assert len(definicion["function"]["description"]) > 20

    def test_actualizar_borrador_expone_los_campos_del_patch(self):
        """Si el catalogo y el schema divergen, el modelo emite campos que
        despues no validan."""
        definicion = next(
            d
            for d in definiciones_openai()
            if d["function"]["name"] == "actualizar_borrador"
        )
        propiedades = set(definicion["function"]["parameters"]["properties"])

        assert propiedades == set(BorradorPatch.model_fields)

    @pytest.mark.parametrize(
        "tool,parametro",
        [
            ("buscar_actividad", "texto"),
            ("consultar_agenda", "dia"),
            ("proponer_eliminacion", "activity_id"),
            ("proponer_modificacion", "activity_id"),
        ],
    )
    def test_las_tools_declaran_los_parametros_que_necesitan(self, tool, parametro):
        definicion = next(
            d for d in definiciones_openai() if d["function"]["name"] == tool
        )

        assert parametro in definicion["function"]["parameters"]["properties"]
