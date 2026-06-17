"""Core parser service for natural language activity descriptions.

Uses an LLMPort implementation to parse user text into structured
activity data conforming to the ParseNLResponse schema.
"""

import logging

from domain.ports.outbound.llm_port import LLMPort
from schemas.parse_nl import ParseNLResponse

logger = logging.getLogger(__name__)

# Few-shot examples to guide the LLM's structured output.
#
# Classification rules for is_fixed / is_anchor:
#   - is_fixed=True, is_anchor=False → day AND time known (scheduler blocks the slot)
#   - is_fixed=False, is_anchor=True  → day known, time NOT known (scheduler pins the day, picks time)
#   - is_fixed=False, is_anchor=False → neither day nor time known (scheduler picks both)
#
# Duration rule:
#   - When the user specifies a duration (ej: "en 15 min", "10 minutos", "media hora")
#     but does NOT specify a start or end time, set duracion_minutos and keep
#     start_time=0, end_time=0 in the schedule entries. Do NOT interpret "en X min"
#     as a specific time of day.
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
            "is_fixed": False,
            "is_anchor": True,
            "difficulty": "media",
            "priority": "media",
            "schedule": [
                {"day": "Jueves", "start_time": 0, "end_time": 0},
            ],
            "location": None,
            "confidence": 0.7,
            "missing_fields": ["start_time", "end_time", "location"],
        },
    },
    {
        "text": "Hacer ejercicios de calculo para el parcial",
        "output": {
            "name": "Ejercicios de calculo",
            "activity_type": "tarea",
            "is_fixed": False,
            "is_anchor": False,
            "difficulty": "alta",
            "priority": "alta",
            "schedule": [],
            "location": None,
            "confidence": 0.6,
            "missing_fields": ["schedule", "location"],
        },
    },
    {
        "text": "Desayunar todos los dias en 15 minutos desde las 4am hasta las 5:40am",
        "output": {
            "name": "Desayunar",
            "activity_type": "tarea",
            "is_fixed": False,
            "is_anchor": True,
            "difficulty": "baja",
            "priority": "baja",
            "schedule": [
                {"day": "Lunes", "start_time": 0, "end_time": 0},
                {"day": "Martes", "start_time": 0, "end_time": 0},
                {"day": "Miercoles", "start_time": 0, "end_time": 0},
                {"day": "Jueves", "start_time": 0, "end_time": 0},
                {"day": "Viernes", "start_time": 0, "end_time": 0},
                {"day": "Sabado", "start_time": 0, "end_time": 0},
                {"day": "Domingo", "start_time": 0, "end_time": 0},
            ],
            "duracion_minutos": 15,
            "hora_preferida_inicio": 240,
            "hora_preferida_fin": 340,
            "location": None,
            "confidence": 0.95,
            "missing_fields": ["start_time", "end_time"],
        },
    },
    {
        "text": "Desayunar todos los dias en 15 minutos",
        "output": {
            "name": "Desayunar",
            "activity_type": "tarea",
            "is_fixed": False,
            "is_anchor": True,
            "difficulty": "baja",
            "priority": "baja",
            "schedule": [
                {"day": "Lunes", "start_time": 0, "end_time": 0},
                {"day": "Martes", "start_time": 0, "end_time": 0},
                {"day": "Miercoles", "start_time": 0, "end_time": 0},
                {"day": "Jueves", "start_time": 0, "end_time": 0},
                {"day": "Viernes", "start_time": 0, "end_time": 0},
                {"day": "Sabado", "start_time": 0, "end_time": 0},
                {"day": "Domingo", "start_time": 0, "end_time": 0},
            ],
            "duracion_minutos": 15,
            "location": None,
            "confidence": 0.9,
            "missing_fields": ["start_time", "end_time"],
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
        "Clasifica la actividad según esta regla:\n"
        '- "is_fixed": true, "is_anchor": false → el usuario dijo día Y horario específico\n'
        '- "is_fixed": false, "is_anchor": true → el usuario dijo el día PERO NO la hora\n'
        '- "is_fixed": false, "is_anchor": false → el usuario NO dijo ni día ni horario\n\n'
        "Regla de duración:\n"
        '- Si el usuario menciona una duración (ej: "en 15 min", "10 minutos", "media hora")\n'
        "  pero NO especifica una hora de inicio ni fin, usá el campo duracion_minutos.\n"
        "  No interpretes 'en X min' como una hora del día. Los start_time / end_time\n"
        "  deben quedar en 0 para indicar que el horario aún no está definido.\n\n"
        "Regla de rango preferido (hora_preferida_inicio / hora_preferida_fin):\n"
        '- Usá estos campos SOLO si el usuario dice "desde las X hasta las Y" o\n'
        '  "entre las X y las Y" Y ADEMÁS especifica una duración separada.\n'
        "  En ese caso NO es un horario fijo, es un RANGO donde la actividad\n"
        '  puede ubicarse. Ej: "en 15 min desde las 4am hasta las 5:40am" →\n'
        "  is_anchor=true, duracion_minutos=15, hora_preferida_inicio=240,\n"
        "  hora_preferida_fin=340, schedule con start_time=0, end_time=0.\n"
        '- Si el usuario solo dice "de X a Y" (sin mencionar duración por\n'
        "  separado), es un horario FIJO. Usá is_fixed=true con start_time y\n"
        "  end_time en schedule, y NO uses hora_preferida_*.\n\n"
        "Devuelve exclusivamente un objeto JSON que cumpla con el esquema indicado.\n"
        "No incluyas texto adicional, explicaciones ni formato markdown.\n\n"
        "Ejemplos:\n\n"
        f"{examples_text}\n\n"
        "---\n\n"
        f"Ahora analiza el siguiente texto y devuelve el JSON correspondiente:\n\n"
        f"Texto de usuario: {text}"
    )
    return prompt


def _has_minimal_data(response: ParseNLResponse) -> bool:
    """Check if the response contains enough data to be useful.

    A response with no name at all is considered a failure.
    """
    return bool(response.name)


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
