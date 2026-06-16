"""Gemini LLM adapter implementing LLMPort.

Uses the google-genai SDK (google.genai) with response_schema for structured
outputs that validate against a Pydantic model.
"""

import json
import logging

from google import genai
from google.genai import types
from pydantic import BaseModel

from domain.ports.outbound.llm_port import LLMPort
from infrastructure.adapters.inbound.api.middleware import (
    LLMServiceException,
    LLMTimeoutException,
)
from infrastructure.config.settings import Settings

logger = logging.getLogger(__name__)

# Default model — balance of speed and quality for structured output
DEFAULT_MODEL = "gemini-2.0-flash"


class GeminiLLMAdapter(LLMPort):
    """Adapter that calls Google Gemini with Pydantic structured outputs.

    Uses Gemini's response_schema feature to guarantee valid JSON that
    matches the expected Pydantic model, eliminating the need for
    post-hoc validation retries.
    """

    def __init__(self, settings: Settings):
        self._client = genai.Client(api_key=settings.GEMINI_API_KEY)

    def generate(self, prompt: str, response_model: type[BaseModel]) -> BaseModel:
        """Send a prompt to Gemini and parse the structured response.

        Args:
            prompt: The text prompt for the model.
            response_model: A Pydantic model class defining the expected
                response structure. Gemini's response_schema enforces
                this schema server-side.

        Returns:
            An instance of response_model populated from the LLM output.

        Raises:
            LLMServiceException: If the LLM returns an error or malformed JSON.
            LLMTimeoutException: If the request times out.
        """
        try:
            response = self._client.models.generate_content(
                model=DEFAULT_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=response_model,
                ),
            )

            raw = response.text.strip()
            if not raw:
                raise LLMServiceException(
                    "Gemini returned an empty response",
                )

            data = json.loads(raw)
            return response_model.model_validate(data)

        except json.JSONDecodeError as exc:
            logger.error("Gemini returned malformed JSON: %s", exc)
            raise LLMServiceException(
                f"Failed to parse Gemini response: {exc}",
            ) from exc

        except LLMServiceException:
            raise

        except Exception as exc:
            exc_name = type(exc).__name__
            logger.error("Gemini API call failed: %s: %s", exc_name, exc)
            raise LLMServiceException(
                f"Gemini API error: {exc}",
            ) from exc
