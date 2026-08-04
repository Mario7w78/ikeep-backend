"""Adaptador conversacional con tool calling, para APIs compatibles con OpenAI.

Sirve para Groq, Cerebras y Mistral igual que su hermano de un solo disparo.

Es deliberadamente tolerante con lo que devuelve el modelo. El tool calling
multi-turno de estos proveedores es irregular: emiten JSON roto, nombres
inventados, argumentos vacios. Nada de eso deberia costarle el turno al
usuario, asi que se descarta lo ilegible y se sigue con el resto. Perder una
extraccion se recupera preguntando de nuevo; tumbar la conversacion, no.
"""

import json
import logging
from typing import Any

from openai import OpenAI

from domain.ports.outbound.conversational_llm_port import (
    ConversationalLLMPort,
    InvocacionTool,
    RespuestaConversacional,
)
from infrastructure.adapters.inbound.api.middleware import LLMServiceException

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 25.0
MAX_OUTPUT_TOKENS = 1500


class OpenAIToolsAdapter(ConversationalLLMPort):
    def __init__(self, api_key: str, base_url: str, default_model: str):
        # Mismo criterio que el adaptador de un disparo: timeout corto para
        # que un proveedor colgado deje avanzar la cadena de failover, y sin
        # reintentos propios porque los hace el failover.
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        )
        self._default_model = default_model

    def conversar(
        self,
        mensajes: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> RespuestaConversacional:
        try:
            respuesta = self._client.chat.completions.create(
                model=self._default_model,
                messages=mensajes,
                tools=tools,
                max_tokens=MAX_OUTPUT_TOKENS,
            )
        except Exception as exc:
            # Se traduce al error del dominio para que el failover pueda
            # reaccionar sin saber contra que proveedor esta hablando.
            logger.warning("Fallo del proveedor %s: %s", self._default_model, exc)
            raise LLMServiceException(
                f"El proveedor no respondio: {exc}"
            ) from exc

        if not respuesta.choices:
            raise LLMServiceException("El proveedor respondio sin opciones.")

        mensaje = respuesta.choices[0].message

        return RespuestaConversacional(
            texto=mensaje.content or None,
            invocaciones=self._leer_invocaciones(mensaje.tool_calls),
        )

    def _leer_invocaciones(self, tool_calls: Any) -> list[InvocacionTool]:
        if not tool_calls:
            return []

        invocaciones = []
        for llamada in tool_calls:
            argumentos = self._leer_argumentos(llamada)
            if argumentos is None:
                continue
            invocaciones.append(
                InvocacionTool(
                    id=llamada.id,
                    nombre=llamada.function.name,
                    argumentos=argumentos,
                )
            )
        return invocaciones

    def _leer_argumentos(self, llamada: Any) -> dict[str, Any] | None:
        """None si no se pueden interpretar, para descartar esa invocacion."""
        crudo = llamada.function.arguments
        # Las tools sin parametros suelen llegar con string vacio.
        if not crudo:
            return {}

        try:
            argumentos = json.loads(crudo)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "Argumentos ilegibles en %s, se descarta la invocacion: %r",
                llamada.function.name,
                crudo,
            )
            return None

        if not isinstance(argumentos, dict):
            logger.warning(
                "Argumentos que no son un objeto en %s: %r",
                llamada.function.name,
                argumentos,
            )
            return None

        return argumentos

    def __repr__(self) -> str:
        return f"OpenAIToolsAdapter(model={self._default_model!r})"
