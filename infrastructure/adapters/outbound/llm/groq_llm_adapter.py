"""Groq LLM adapter implementing LLMPort.

Uses the OpenAI-compatible API via the openai Python SDK pointed at
Groq's API endpoint for structured JSON outputs.
"""

import json
import logging

from openai import OpenAI
from pydantic import BaseModel

from domain.ports.outbound.llm_port import LLMPort
from infrastructure.adapters.inbound.api.middleware import (
    LLMServiceException,
)
from infrastructure.config.settings import Settings

logger = logging.getLogger(__name__)

# Default model — balance of speed and quality for structured output
DEFAULT_MODEL = "llama-3.3-70b-versatile"


class GroqLLMAdapter(LLMPort):
    """Adapter that calls Groq (Llama models) with structured JSON outputs.

    Uses the OpenAI-compatible endpoint with response_format to enforce
    valid JSON, then parses against the expected Pydantic model.
    """

    def __init__(self, settings: Settings):
        self._client = OpenAI(
            api_key=settings.GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
        )

    def generate(self, prompt: str, response_model: type[BaseModel]) -> BaseModel:
        """Send a prompt to Groq and parse the structured response.

        Args:
            prompt: The text prompt for the model.
            response_model: A Pydantic model class defining the expected
                response structure.

        Returns:
            An instance of response_model populated from the LLM output.

        Raises:
            LLMServiceException: If the LLM returns an error or malformed JSON.
        """
        try:
            schema = response_model.model_json_schema()
            response = self._client.chat.completions.create(
                model=DEFAULT_MODEL,
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
                raise LLMServiceException("Groq returned an empty response")

            data = json.loads(raw)
            return response_model.model_validate(data)

        except json.JSONDecodeError as exc:
            logger.error("Groq returned malformed JSON: %s", exc)
            raise LLMServiceException(
                f"Failed to parse Groq response: {exc}",
            ) from exc

        except LLMServiceException:
            raise

        except Exception as exc:
            exc_name = type(exc).__name__
            logger.error("Groq API call failed: %s: %s", exc_name, exc)
            raise LLMServiceException(
                f"Groq API error: {exc}",
            ) from exc
