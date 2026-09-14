"""Tests del failover conversacional.

Hay un caso que importa especialmente: si todos los proveedores se quedaron
sin presupuesto, eso no es "la pasarela falla" sino "el asistente se quedo sin
pilas", y la app lo debe poder distinguir para hablarle distinto al usuario.
"""

from unittest.mock import MagicMock

import pytest

from infrastructure.adapters.inbound.api.middleware import (
    LLMGatewayException,
    LLMQuotaExceededException,
    LLMServiceException,
)
from infrastructure.adapters.outbound.llm.conversational_failover_adapter import (
    ConversationalFailoverAdapter,
)


def _respuesta():
    return MagicMock(texto="hola", invocaciones=[])


class TestFailoverConversacional:
    def test_el_primer_proveedor_que_responda_gana(self):
        p1 = MagicMock()
        p1.conversar.side_effect = LLMServiceException("fallo p1")
        p2 = MagicMock()
        p2.conversar.return_value = _respuesta()

        resultado = ConversationalFailoverAdapter([p1, p2]).conversar([], [])

        assert resultado.texto == "hola"
        p2.conversar.assert_called_once()

    def test_se_prueba_el_siguiente_al_quedarse_sin_quota(self):
        """Un proveedor sin saldo no corta el intento: otro puede tener."""
        p1 = MagicMock()
        p1.conversar.side_effect = LLMQuotaExceededException("p1 sin saldo")
        p2 = MagicMock()
        p2.conversar.return_value = _respuesta()

        resultado = ConversationalFailoverAdapter([p1, p2]).conversar([], [])

        assert resultado.texto == "hola"

    def test_todos_sin_quota_es_quota_y_no_pasarela(self):
        """Es el caso del boton: se agoto todo el presupuesto de proveedores.
        El cliente tiene que saber que Sapo se canso, no que el servidor
        exploto."""
        p1 = MagicMock()
        p1.conversar.side_effect = LLMQuotaExceededException("p1 sin saldo")
        p2 = MagicMock()
        p2.conversar.side_effect = LLMQuotaExceededException("p2 sin saldo")

        with pytest.raises(LLMQuotaExceededException) as capturado:
            ConversationalFailoverAdapter([p1, p2]).conversar([], [])

        assert "sin saldo" in str(capturado.value)

    def test_mezcla_de_fallas_sigue_siendo_pasarela(self):
        """Uno sin saldo y otro roto: el usuario esta ante un fallo general,
        no ante el boton."""
        p1 = MagicMock()
        p1.conversar.side_effect = LLMQuotaExceededException("p1 sin saldo")
        p2 = MagicMock()
        p2.conversar.side_effect = LLMServiceException("p2 roto")

        with pytest.raises(LLMGatewayException):
            ConversationalFailoverAdapter([p1, p2]).conversar([], [])