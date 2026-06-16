"""Core parser service for natural language activity descriptions.

Uses an LLMPort implementation to parse user text into structured
activity data conforming to the ParseNLResponse schema.
"""

import logging

from domain.ports.outbound.llm_port import LLMPort
from schemas.parse_nl import ParseNLResponse

logger = logging.getLogger(__name__)

# Few-shot examples to guide the LLM's structured output
_FEW_SHOT_EXAMPLES = [
    {
        "text": "Entreno de futbol los lunes y miercoles de 18 a 19 en el polideportivo",
        "output": {
            "name": "Entreno de futbol",
            "activity_type": "tarea",
            "is_fixed": True,
            "is_anchor": False,
            "difficulty": "media",
            "priority": "media",
            "schedule": [
                {"day": "Lunes", "start_time": 1080, "end_time": 1140},
                {"day": "Miercoles", "start_time": 1080, "end_time": 1140},
            ],
            "location": "Polideportivo",
            "confidence": 0.95,
            "missing_fields": [],
        },
    },
    {
        "text": "Clase de piano los jueves",
        "output": {
            "name": "Clase de piano",
            "activity_type": "clase",
            "is_fixed": True,
            "is_anchor": False,
            "difficulty": "media",
            "priority": "media",
            "schedule": [],
            "location": None,
            "confidence": 0.7,
            "missing_fields": ["schedule", "location"],
        },
    },
]


def _build_few_shot_prompt(text: str) -> str:
    """Build a structured prompt with few-shot examples."""
    examples_text = "\n\n".join(
        f"Texto de usuario: {ex['text']}\n"
        f"Salida JSON: {ex['output']}"
        for ex in _FEW_SHOT_EXAMPLES
    )

    prompt = (
        "Eres un asistente que extrae información estructurada sobre actividades "
        "a partir de texto en lenguaje natural escrito por estudiantes universitarios.\n\n"
        "Devolvé exclusivamente un objeto JSON que cumpla con el esquema indicado.\n"
        "No incluyas texto adicional, explicaciones ni formato markdown.\n\n"
        "Ejemplos:\n\n"
        f"{examples_text}\n\n"
        "---\n\n"
        f"Ahora analizá el siguiente texto y devolvé el JSON correspondiente:\n\n"
        f"Texto de usuario: {text}"
    )
    return prompt


def _has_minimal_data(response: ParseNLResponse) -> bool:
    """Check if the response contains enough data to be useful.

    A response with no name and no schedule is considered a failure.
    """
    return bool(response.name) or len(response.schedule) > 0


class LLMParserService:
    """Orchestrates natural language parsing through an LLM.

    Builds prompts with few-shot examples, calls the LLM via LLMPort,
    and maps the structured output to a ParseNLResponse.
    """

    def __init__(self, llm_port: LLMPort):
        self._llm_port = llm_port

    def build_prompt(self, text: str) -> str:
        """Build a prompt with few-shot examples for the given text."""
        return _build_few_shot_prompt(text)

    def parse(self, text: str) -> ParseNLResponse:
        """Parse a natural language activity description.

        Args:
            text: The user's natural language activity description.

        Returns:
            A ParseNLResponse with the extracted fields.

        Raises:
            RuntimeError: If parsing fails after retries.
        """
        prompt = self.build_prompt(text)

        for attempt in range(2):  # initial + one retry
            logger.info(
                "LLM parse attempt %d/2 for text (len=%d)",
                attempt + 1,
                len(text),
            )
            raw = self._llm_port.generate(prompt, ParseNLResponse)
            if _has_minimal_data(raw):
                return raw

            if attempt == 0:
                logger.info("First parse produced sparse data, retrying...")
                prompt = (
                    "El resultado anterior fue incompleto. Por favor, analizá "
                    "nuevamente el texto e intentá extraer todos los campos posibles, "
                    "aunque la información sea parcial.\n\n"
                    + prompt
                )

        logger.warning("Failed to parse activity text after retry: %s", text[:50])
        raise RuntimeError(
            "Failed to parse activity description after multiple attempts. "
            "Please provide more details."
        )
