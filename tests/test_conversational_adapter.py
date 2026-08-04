"""Tests del adaptador conversacional con tool calling.

El riesgo mayor de quedarse en Groq/Cerebras es que su tool calling multi-turno
es irregular: un modelo puede devolver argumentos que no son JSON, o inventar
nombres de tool. Nada de eso deberia tumbar el turno, asi que se prueba
explicitamente.
"""

import json
from unittest.mock import Mock, patch

import pytest

from domain.ports.outbound.conversational_llm_port import RespuestaConversacional
from infrastructure.adapters.inbound.api.middleware import LLMServiceException
from infrastructure.adapters.outbound.llm.openai_tools_adapter import (
    OpenAIToolsAdapter,
)

MENSAJES = [{"role": "user", "content": "clase de calculo"}]
TOOLS = [{"type": "function", "function": {"name": "actualizar_borrador"}}]


def _respuesta_openai(contenido=None, tool_calls=None):
    mensaje = Mock()
    mensaje.content = contenido
    mensaje.tool_calls = tool_calls
    eleccion = Mock()
    eleccion.message = mensaje
    respuesta = Mock()
    respuesta.choices = [eleccion]
    return respuesta


def _tool_call(id_="call-1", nombre="actualizar_borrador", argumentos='{"name": "Calculo"}'):
    llamada = Mock()
    llamada.id = id_
    llamada.function.name = nombre
    llamada.function.arguments = argumentos
    return llamada


@pytest.fixture
def adaptador():
    with patch(
        "infrastructure.adapters.outbound.llm.openai_tools_adapter.OpenAI"
    ) as cliente:
        adaptador = OpenAIToolsAdapter(
            api_key="clave", base_url="https://proveedor/v1", default_model="modelo-x"
        )
        adaptador._cliente_mock = cliente.return_value
        yield adaptador


class TestRespuestaDeTexto:
    def test_devuelve_el_texto_del_modelo(self, adaptador):
        adaptador._cliente_mock.chat.completions.create.return_value = (
            _respuesta_openai(contenido="Que dias la tenes?")
        )

        respuesta = adaptador.conversar(MENSAJES, TOOLS)

        assert respuesta.texto == "Que dias la tenes?"
        assert respuesta.pide_tools is False

    def test_manda_las_tools_y_los_mensajes(self, adaptador):
        adaptador._cliente_mock.chat.completions.create.return_value = (
            _respuesta_openai(contenido="ok")
        )

        adaptador.conversar(MENSAJES, TOOLS)

        kwargs = adaptador._cliente_mock.chat.completions.create.call_args.kwargs
        assert kwargs["messages"] == MENSAJES
        assert kwargs["tools"] == TOOLS
        assert kwargs["model"] == "modelo-x"


class TestInvocaciones:
    def test_devuelve_las_tools_que_pidio(self, adaptador):
        adaptador._cliente_mock.chat.completions.create.return_value = (
            _respuesta_openai(tool_calls=[_tool_call()])
        )

        respuesta = adaptador.conversar(MENSAJES, TOOLS)

        assert respuesta.pide_tools is True
        assert respuesta.invocaciones[0].nombre == "actualizar_borrador"
        assert respuesta.invocaciones[0].argumentos == {"name": "Calculo"}

    def test_conserva_el_id_de_cada_invocacion(self, adaptador):
        """Es como el modelo empareja lo que pidio con lo que se le responde."""
        adaptador._cliente_mock.chat.completions.create.return_value = (
            _respuesta_openai(tool_calls=[_tool_call(id_="call-abc")])
        )

        respuesta = adaptador.conversar(MENSAJES, TOOLS)

        assert respuesta.invocaciones[0].id == "call-abc"

    def test_soporta_varias_invocaciones_en_un_turno(self, adaptador):
        adaptador._cliente_mock.chat.completions.create.return_value = (
            _respuesta_openai(
                tool_calls=[
                    _tool_call(id_="a", nombre="actualizar_borrador"),
                    _tool_call(id_="b", nombre="proponer_actividad", argumentos="{}"),
                ]
            )
        )

        respuesta = adaptador.conversar(MENSAJES, TOOLS)

        assert [i.nombre for i in respuesta.invocaciones] == [
            "actualizar_borrador",
            "proponer_actividad",
        ]

    def test_texto_e_invocaciones_pueden_venir_juntos(self, adaptador):
        adaptador._cliente_mock.chat.completions.create.return_value = (
            _respuesta_openai(contenido="Ahi va", tool_calls=[_tool_call()])
        )

        respuesta = adaptador.conversar(MENSAJES, TOOLS)

        assert respuesta.texto == "Ahi va"
        assert respuesta.pide_tools is True


class TestRobustez:
    def test_unos_argumentos_ilegibles_no_tumban_el_turno(self, adaptador):
        """Estos modelos a veces emiten JSON roto. Se descarta esa invocacion
        y se sigue: perder una extraccion se recupera preguntando, tumbar el
        turno no."""
        adaptador._cliente_mock.chat.completions.create.return_value = (
            _respuesta_openai(tool_calls=[_tool_call(argumentos="{no es json")])
        )

        respuesta = adaptador.conversar(MENSAJES, TOOLS)

        assert respuesta.invocaciones == []

    def test_una_invocacion_rota_no_descarta_las_buenas(self, adaptador):
        adaptador._cliente_mock.chat.completions.create.return_value = (
            _respuesta_openai(
                tool_calls=[
                    _tool_call(id_="a", argumentos="{roto"),
                    _tool_call(id_="b", argumentos='{"name": "Algebra"}'),
                ]
            )
        )

        respuesta = adaptador.conversar(MENSAJES, TOOLS)

        assert len(respuesta.invocaciones) == 1
        assert respuesta.invocaciones[0].id == "b"

    def test_argumentos_vacios_se_leen_como_objeto_vacio(self, adaptador):
        """Las tools sin parametros suelen llegar con string vacio."""
        adaptador._cliente_mock.chat.completions.create.return_value = (
            _respuesta_openai(tool_calls=[_tool_call(argumentos="")])
        )

        respuesta = adaptador.conversar(MENSAJES, TOOLS)

        assert respuesta.invocaciones[0].argumentos == {}

    def test_un_fallo_del_proveedor_se_traduce_al_error_del_dominio(self, adaptador):
        """Asi el failover puede reaccionar sin conocer al proveedor."""
        adaptador._cliente_mock.chat.completions.create.side_effect = Exception("502")

        with pytest.raises(LLMServiceException):
            adaptador.conversar(MENSAJES, TOOLS)

    def test_una_respuesta_sin_opciones_es_un_fallo_del_servicio(self, adaptador):
        respuesta_vacia = Mock()
        respuesta_vacia.choices = []
        adaptador._cliente_mock.chat.completions.create.return_value = respuesta_vacia

        with pytest.raises(LLMServiceException):
            adaptador.conversar(MENSAJES, TOOLS)
