"""Generic adapter for any OpenAI-compatible LLM API.

Works with any provider that exposes an OpenAI-compatible /v1/chat/completions
endpoint: Groq, Cerebras, Mistral, and many others.

Uses the `openai` Python SDK with a configurable base_url and model name.
"""

import json
import logging

from openai import OpenAI
from pydantic import BaseModel

from domain.ports.outbound.llm_port import LLMPort
from infrastructure.adapters.inbound.api.middleware import LLMServiceException

logger = logging.getLogger(__name__)


class OpenAICompatibleAdapter(LLMPort):
    """Adapter for any OpenAI-compatible LLM inference API.

    Attributes:
        api_key: API key for the provider.
        base_url: Full URL to the provider's OpenAI-compatible endpoint.
        default_model: Model identifier to use for all calls.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        default_model: str,
    ):
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._default_model = default_model

    def generate(self, prompt: str, response_model: type[BaseModel]) -> BaseModel:
        """Send a prompt and return a structured response.

        Args:
            prompt: The text prompt for the model.
            response_model: A Pydantic model class defining the expected
                response structure.

        Returns:
            An instance of response_model populated from the LLM output.

        Raises:
            LLMServiceException: If the LLM returns an error or malformed JSON.
        """
        schema = response_model.model_json_schema()

        try:
            response = self._client.chat.completions.create(
                model=self._default_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Eres un asistente que responde exclusivamente con JSON válido. "
                            "No incluyas texto adicional, explicaciones ni formato markdown. "
                            f"El JSON debe cumplir con este esquema: {json.dumps(schema)}"
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )

            raw = response.choices[0].message.content
            if not raw:
                raise LLMServiceException(
                    f"{self._default_model} returned an empty response",
                )

            data = json.loads(raw)
            return response_model.model_validate(data)

        except json.JSONDecodeError as exc:
            logger.error(
                "%s returned malformed JSON: %s", self._default_model, exc,
            )
            raise LLMServiceException(
                f"Failed to parse {self._default_model} response: {exc}",
            ) from exc

        except LLMServiceException:
            raise

        except Exception as exc:
            exc_name = type(exc).__name__
            logger.error(
                "%s API call failed: %s: %s", self._default_model, exc_name, exc,
            )
            raise LLMServiceException(
                f"{self._default_model} API error: {exc}",
            ) from exc

    def __repr__(self) -> str:
        return f"OpenAICompatibleAdapter(model={self._default_model})"
