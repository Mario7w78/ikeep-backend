"""Failover entre proveedores conversacionales.

Hermano del FailoverAdapter de un disparo, con la misma politica: se prueban
en orden y se pasa al siguiente ante un fallo del servicio o un timeout.

Aca importa mas que en el otro caso. El tool calling multi-turno es donde
estos proveedores se comportan de forma mas despareja, asi que la probabilidad
de tener que cambiar a mitad de conversacion es real.
"""

import logging
from typing import Any

from domain.ports.outbound.conversational_llm_port import (
    ConversationalLLMPort,
    RespuestaConversacional,
)
from infrastructure.adapters.inbound.api.middleware import (
    LLMGatewayException,
    LLMServiceException,
    LLMTimeoutException,
)

logger = logging.getLogger(__name__)


class ConversationalFailoverAdapter(ConversationalLLMPort):
    def __init__(self, providers: list[ConversationalLLMPort]):
        if not providers:
            raise ValueError("Se requiere al menos un proveedor")
        self._providers = providers

    def conversar(
        self,
        mensajes: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> RespuestaConversacional:
        errores = []

        for proveedor in self._providers:
            try:
                return proveedor.conversar(mensajes, tools)
            except (LLMServiceException, LLMTimeoutException) as exc:
                # Solo estos dos: cualquier otra excepcion es un error nuestro
                # y probar con otro proveedor solo lo repetiria mas lento.
                logger.warning("Proveedor %r fallo: %s", proveedor, exc)
                errores.append(f"{proveedor}: {exc}")

        raise LLMGatewayException(
            "Ningun proveedor pudo responder. " + " | ".join(errores)
        )
