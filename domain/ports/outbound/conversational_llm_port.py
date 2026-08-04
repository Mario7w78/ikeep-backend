"""Puerto para conversacion con tool calling.

Hermano de LLMPort, no reemplazo. Aquel resuelve un disparo estructurado
—prompt entra, modelo Pydantic sale— y lo usan suggest y reschedule, que
funcionan bien asi. Este necesita otra forma: una lista de turnos que crece,
un catalogo de tools, y una respuesta que puede ser texto o invocaciones.

Se separan porque forzar los dos casos en una firma habria obligado a los
consumidores existentes a cargar con parametros que no usan.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class InvocacionTool:
    """Una tool que el modelo decidio llamar."""

    # Lo asigna el proveedor y hay que devolverlo junto al resultado: es como
    # el modelo empareja lo que pidio con lo que se le responde.
    id: str
    nombre: str
    argumentos: dict[str, Any]


@dataclass(frozen=True)
class RespuestaConversacional:
    """Lo que devuelve el modelo en un turno.

    Puede traer texto, invocaciones, o ambos: un modelo puede explicar lo que
    va a hacer mientras lo hace.
    """

    texto: str | None = None
    invocaciones: list[InvocacionTool] = field(default_factory=list)

    @property
    def pide_tools(self) -> bool:
        return bool(self.invocaciones)


class ConversationalLLMPort(ABC):
    @abstractmethod
    def conversar(
        self,
        mensajes: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> RespuestaConversacional:
        """Continua la conversacion.

        Args:
            mensajes: Los turnos en el formato nativo del proveedor. Las
                invocaciones y sus resultados viajan verbatim, no
                parafraseados: que el modelo reciba de vuelta su propio JSON
                estructurado es justamente lo que evita que tenga que
                re-deducirlo.
            tools: El catalogo disponible en este turno.

        Raises:
            LLMServiceException: Si el proveedor falla.
            LLMTimeoutException: Si se agota el tiempo.
        """
