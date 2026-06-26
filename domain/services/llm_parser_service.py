"""Core parser service for natural language activity descriptions.

Uses an LLMPort implementation to parse user text into structured
activity data conforming to the ParseNLResponse schema.
"""

import logging
from typing import Literal

from pydantic import BaseModel

from domain.ports.outbound.llm_port import LLMPort
from schemas.parse_nl import (
    ParsedSchedule,
    ParseNLResponse,
    QuestionResponse,
    ResultResponse,
    ChatResponse,
)
from infrastructure.adapters.inbound.api.middleware import LLMGatewayException

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
    {
        "text": "Practicar guitarra los martes, elige tú el horario",
        "output": {
            "name": "Practicar guitarra",
            "activity_type": "tarea",
            "is_fixed": False,
            "is_anchor": True,
            "difficulty": "media",
            "priority": "media",
            "schedule": [
                {"day": "Martes", "start_time": 0, "end_time": 0},
            ],
            "location": None,
            "confidence": 0.85,
            "missing_fields": ["start_time", "end_time", "location"],
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
        "  pero NO especifica una hora de inicio ni fin, usa el campo duracion_minutos.\n"
        "  No interpretes 'en X min' como una hora del día. Los start_time / end_time\n"
        "  deben quedar en 0 para indicar que el horario aún no está definido.\n\n"
        "Regla de rango preferido (hora_preferida_inicio / hora_preferida_fin):\n"
        '- Usa estos campos SOLO si el usuario dice "desde las X hasta las Y" o\n'
        '  "entre las X y las Y" Y ADEMÁS especifica una duración separada.\n'
        "  En ese caso NO es un horario fijo, es un RANGO donde la actividad\n"
        '  puede ubicarse. Ej: "en 15 min desde las 4am hasta las 5:40am" →\n'
        "  is_anchor=true, duracion_minutos=15, hora_preferida_inicio=240,\n"
        "  hora_preferida_fin=340, schedule con start_time=0, end_time=0.\n"
        '- Si el usuario solo dice "de X a Y" (sin mencionar duración por\n'
        "  separado), es un horario FIJO. Usa is_fixed=true con start_time y\n"
        "  end_time en schedule, y NO uses hora_preferida_*.\n\n"
        "Reglas de conversión de horas AM/PM a minutos desde la medianoche:\n"
        '- Todas las horas de inicio/fin en schedule u horas preferidas deben ser minutos enteros desde las 00:00 (medianoche).\n'
        "- Sé extremadamente preciso con am/pm:\n"
        "  * Las horas AM van desde las 12:00 am (0 minutos) hasta las 11:59 am (719 minutos).\n"
        "    Ej: 12 am (medianoche) = 0, 1 am (o '1 am', '1am') = 60, 7 am = 420, 11 am = 660.\n"
        "  * Las horas PM van desde las 12:00 pm (720 minutos) hasta las 11:59 pm (1439 minutos).\n"
        "    Para horas PM de 1 a 11, DEBES sumar 12 horas (720 minutos):\n"
        "    Ej: 12 pm (mediodía) = 720, 1 pm (o '1 pm', '1pm') = 780, 2 pm = 840, 6 pm = 1080, 8 pm = 1200.\n"
        "    ¡NUNCA confundas 1 pm (780 min) con 1 am (60 min) ni con otra hora!\n"
        "  * Si dice 'a la 1' y el contexto es de tarde/noche, asume 1 pm (780 min).\n\n"
        "Regla de delegación del horario:\n"
        '- Si el usuario te dice "elige tú", "tú decides", "cuando sea", "lo que sea",\n'
        '  "como sea", "lo que mejor convenga" o similar, está delegando en ti la\n'
        '  elección del horario. NO inventes un horario. Crea la actividad como ancla\n'
        '  (is_fixed: false, is_anchor: true) con los días que ya tiene y start_time=0,\n'
        "  end_time=0 en cada entrada del schedule.\n\n"
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

    # ── Conversational NL parsing ──────────────────────────────────

    def _build_conversational_prompt(self, text: str, history: list[dict], agenda_context: str | None = None) -> str:
        """Build a prompt for conversational NL parsing with accumulated context.

        Args:
            text: The current user message.
            history: List of prior exchanges as {role, content} dicts.
            agenda_context: Optional string containing current scheduled activities.

        Returns:
            A formatted prompt string for the LLM.
        """
        # Format conversation history
        history_lines = []
        for msg in history:
            role_val = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
            content_val = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
            role = "Usuario" if role_val == "user" else "Asistente"
            history_lines.append(f"{role}: {content_val}")

        history_text = "\n".join(history_lines) if history_lines else "(vacío)"

        few_shot_examples = """Ejemplo 1 (saludo inicial → pregunta):
Historial de la conversación: (vacío)
Usuario: hola
Respuesta: {
  "response_type": "question",
  "ai_message": "¡Hola! ¿Qué actividad quieres agregar hoy?",
  "missing_fields": ["name", "schedule", "duracion_minutos"]
}

Ejemplo 2 (vago → pregunta):
Historial de la conversación: (vacío)
Usuario: hacer ejercicio
Respuesta: {
  "response_type": "question",
  "ai_message": "¿Qué tipo de actividad quieres agregar? ¿Es una clase, un trabajo o una tarea?",
  "missing_fields": ["activity_type"]
}

Ejemplo 3 (parcial → pregunta):
Usuario: clase de yoga los lunes
Asistente: ¿Cuánto dura cada clase?
Usuario: 45 minutos
Respuesta: {
  "response_type": "question",
  "ai_message": "¿A qué hora empieza la clase de yoga los lunes?",
  "missing_fields": ["schedule"]
}

Ejemplo 4 (completo → resultado):
Usuario: Estudiar matemáticas los lunes y miércoles de 18 a 20, es una tarea de dificultad alta
Respuesta: {
  "response_type": "result",
  "name": "Estudiar matemáticas",
  "activity_type": "tarea",
  "is_fixed": true,
  "is_anchor": false,
  "difficulty": "alta",
  "priority": null,
  "schedule": [
    {"day": "lunes", "start_time": 1080, "end_time": 1200},
    {"day": "miércoles", "start_time": 1080, "end_time": 1200}
  ],
  "duracion_minutos": 120,
  "hora_preferida_inicio": null,
  "hora_preferida_fin": null,
  "location": null,
  "confidence": 0.95,
  "missing_fields": []
}

Ejemplo 5 (ancla con ventana preferida → resultado):
Usuario: Desayunar todos los días en 15 minutos desde las 4am hasta las 5:40am
Respuesta: {
  "response_type": "result",
  "name": "Desayunar",
  "activity_type": null,
  "is_fixed": false,
  "is_anchor": true,
  "difficulty": null,
  "priority": null,
  "schedule": [
    {"day": "lunes", "start_time": 0, "end_time": 0},
    {"day": "martes", "start_time": 0, "end_time": 0},
    {"day": "miércoles", "start_time": 0, "end_time": 0},
    {"day": "jueves", "start_time": 0, "end_time": 0},
    {"day": "viernes", "start_time": 0, "end_time": 0}
  ],
  "duracion_minutos": 15,
  "hora_preferida_inicio": 240,
  "hora_preferida_fin": 340,
  "location": null,
  "confidence": 0.9,
  "missing_fields": []
}

Ejemplo 6 (vago → pregunta con horario):
Usuario: voy al gimnasio
Respuesta: {
  "response_type": "question",
  "ai_message": "¿Qué días piensas ir al gimnasio y cuánto dura cada sesión?",
  "missing_fields": ["schedule", "duracion_minutos"]
}

Ejemplo 7 (corrección de horario tras superposición → resultado):
Historial de la conversación:
Usuario: Estudiar inglés los sábados de 7 a 10 am
Asistente: El horario del día Sabado (07:00 - 10:00) se superpone con la actividad ya establecida "Trabajar" (08:00 - 12:00).
Usuario: cambialo a las 11:00 am
Respuesta: {
  "response_type": "result",
  "name": "Estudiar inglés",
  "activity_type": "tarea",
  "is_fixed": true,
  "is_anchor": false,
  "difficulty": null,
  "priority": null,
  "schedule": [
    {"day": "sábado", "start_time": 660, "end_time": 840}
  ],
  "duracion_minutos": 180,
  "hora_preferida_inicio": null,
  "hora_preferida_fin": null,
  "location": null,
  "confidence": 0.95,
  "missing_fields": []
}

Ejemplo 8 (acumulación de contexto en turnos → resultado):
Historial de la conversación:
Usuario: quiero agregar mi clase de álgebra
Asistente: ¡Hola! ¿Qué días tienes la clase de álgebra y en qué horario?
Usuario: los martes de 10:00 a 12:00
Respuesta: {
  "response_type": "result",
  "name": "Clase de álgebra",
  "activity_type": "clase",
  "is_fixed": true,
  "is_anchor": false,
  "difficulty": null,
  "priority": null,
  "schedule": [
    {"day": "martes", "start_time": 600, "end_time": 720}
  ],
  "duracion_minutos": 120,
  "hora_preferida_inicio": null,
  "hora_preferida_fin": null,
  "location": null,
  "confidence": 0.95,
  "missing_fields": []
}

Ejemplo 9 (delegación de horario → resultado con ancla):
Historial de la conversación:
Usuario: quiero agregar una clase de yoga los lunes
Asistente: ¿A qué hora quieres hacer la clase de yoga los lunes?
Usuario: elige tú el horario
Respuesta: {
  "response_type": "result",
  "name": "Clase de yoga",
  "activity_type": "clase",
  "is_fixed": false,
  "is_anchor": true,
  "difficulty": null,
  "priority": null,
  "schedule": [
    {"day": "lunes", "start_time": 0, "end_time": 0}
  ],
  "duracion_minutos": null,
  "hora_preferida_inicio": null,
  "hora_preferida_fin": null,
  "location": null,
  "confidence": 0.85,
  "missing_fields": ["start_time", "end_time"]
}"""


        prompt = f"""Eres un asistente que ayuda a crear actividades académicas para un planificador horario.
Decide si la información del usuario es SUFICIENTE para producir una actividad estructurada, o si necesitas preguntar algo más, o si es charla libre / fuera de tema.
Si la consulta del usuario es charla libre, saludo casual, despedida o temas fuera del contexto de agregar actividades, responde con response_type 'chat' y una respuesta amigable.
Si falta información CRÍTICA (nombre, días, duración), responde con response_type 'question' y una pregunta corta y natural.
Si hay suficiente información, responde con response_type 'result' y el JSON completo.
Haz preguntas cortas, naturales, como si hablaras con un amigo, en español neutro (sin voseo argentino).
Una pregunta por vez. No abrumes al usuario.
Máximo 4 intercambios (ida+vuelta). Si llegas a 4, produce un result con lo que tengas.

Reglas especiales para el contexto y saludos:
1. Si el usuario te saluda de forma casual (ej. "hola", "buenas") o hace charla libre, responde usando response_type 'chat' con un mensaje amigable en 'ai_message'.
2. Debes recordar y acumular la información de toda la conversación en el historial. Si el usuario te dio el nombre de la actividad o los días en un mensaje anterior y ahora te da otro detalle (como las horas), el JSON resultante de tipo "result" debe incluir el nombre ("name") y demás campos que dio antes. No ignores ni olvides la información provista en los turnos anteriores.
3. Si se proporciona una sección de 'Actividades ya programadas en la agenda del usuario', utilízala como referencia de lo que el usuario ya tiene agendado. Si pide modificar o referenciar alguna de estas actividades existentes, debes mantener sus atributos previos (como categoría, tipo de horario y detalles temporales) a menos que el usuario indique explícitamente cambiarlos.
4. Prioridad absoluta del último mensaje: Lo último expresado por el usuario en el historial o en su mensaje actual manda de manera OBLIGATORIA. Si hay cualquier contradicción entre mensajes anteriores o el contexto de la agenda y el último mensaje, debes obedecer ciegamente la instrucción o corrección más reciente del usuario.

Reglas especiales para el tiempo y la duración:
1. Si el usuario especifica un rango de hora específico (ej. "de 7 am a 10 am" o "de 18 a 20"), la duración se infiere automáticamente a partir de la diferencia (ej. 3 horas o 2 horas). NO debes considerarla como faltante ni preguntar por ella; la actividad es fija (`is_fixed: true`) y se guardan las horas de inicio y fin exactas en el `schedule`.
2. Si el usuario especifica un rango y además indica una duración, y esa duración coincide exactamente con la diferencia de ese rango (ej. "3 horas de 7 am a 10 am" o "duración 2 horas de 18 a 20"), trátalo como un horario FIJO (`is_fixed: true`, `is_anchor: false`), guardando las horas exactas en el `schedule` y dejando las horas preferidas en null.
3. Si el usuario especifica una duración menor dentro de un rango de tiempo (ej. "10 minutos entre 7 am a 10 am"), la actividad es optimizable / flexible (`is_fixed: false`), la duración es la indicada (10 minutos), y el rango de tiempo se guarda en `hora_preferida_inicio` (420) y `hora_preferida_fin` (600). En este caso, el `schedule` debe tener `start_time: 0` and `end_time: 0` para los días indicados.
4. Si el usuario realiza una corrección (ej. cambia la hora o el día), debes actualizar los campos correspondientes en el JSON resultante. Nunca mantengas los valores antiguos si el usuario explícitamente pidió cambiarlos en su último mensaje.
5. Si el usuario corrige la hora de inicio pero no especifica la duración (ej. "cambialo a las 11 am"), y en el historial se puede deducir la duración previa (ej. de 7 a 10 am = 3 horas), mantén esa duración previa y calcula la nueva hora de fin basándote en ella (de 11 am a 2 pm). No vuelvas a preguntar por la duración si ya estaba establecida.
6. Si el usuario delega el horario con cualquier frase de delegación de horario (incluso si no está en una lista cerrada, ej. "tú decide", "elige tú", "tú decides", "cuando sea", "lo que sea", "como sea", "cuando puedas", "lo que mejor convenga", "cualquier hora", "cuando sea mejor", etc.), debes marcar la actividad con `is_anchor: true`, `is_fixed: false`, y establecer `start_time: 0` y `end_time: 0` en el schedule para los días correspondientes. No inventes un horario por defecto.
7. Reglas de conversión de horas AM/PM a minutos desde la medianoche:
   - Todas las horas de inicio/fin en schedule u horas preferidas deben ser minutos enteros desde las 00:00 (medianoche).
   - Sé extremadamente preciso con am/pm:
     * Las horas AM van desde las 12:00 am (0 minutos) hasta las 11:59 am (719 minutos). Ej: 12 am (medianoche) = 0, 1 am (o '1 am', '1am') = 60, 7 am = 420, 11 am = 660.
     * Las horas PM van desde las 12:00 pm (720 minutos) hasta las 11:59 pm (1439 minutos). Para horas PM de 1 a 11, DEBES sumar 12 horas (720 minutos): Ej: 12 pm (mediodía) = 720, 1 pm (o '1 pm', '1pm') = 780, 2 pm = 840, 6 pm = 1080, 8 pm = 1200. ¡NUNCA confundas 1 pm (780 min) con 1 am (60 min) ni con otra hora!
     * Si dice 'a la 1' y el contexto es de tarde/noche, asume 1 pm (780 min).

Regla de anti-alucinación:
1. Si un campo (como ubicación, prioridad, dificultad, tipo de actividad, etc.) no se menciona en la conversación y no se puede deducir, déjalo en null en el JSON de salida. No asumas ni inventes valores por defecto para campos no provistos.

Ejemplos de comportamiento:
{few_shot_examples}

IMPORTANTE: Responde SOLO con JSON válido. Sin markdown, sin texto adicional.

Si response_type es "chat":
{{
  "response_type": "chat",
  "ai_message": "[tu respuesta de charla casual / saludo / despedida / fuera de tema]"
}}

Si response_type es "question":
{{
  "response_type": "question",
  "ai_message": "[tu pregunta amigable en español neutro]",
  "missing_fields": ["campo1", "campo2"]
}}

Si response_type es "result":
{{
  "response_type": "result",
  "name": "...",
  "activity_type": "clase" | "trabajo" | "tarea" | null,
  "is_fixed": true | false,
  "is_anchor": true | false,
  "difficulty": "baja" | "media" | "alta" | null,
  "priority": "baja" | "media" | "alta" | null,
  "schedule": [ {{"day": "lunes" | "martes" | "miércoles" | "jueves" | "viernes" | "sábado" | "domingo", "start_time": minutos | 0, "end_time": minutos | 0}} ],
  "duracion_minutos": int | null,
  "hora_preferida_inicio": int | null,
  "hora_preferida_fin": int | null,
  "location": str | null,
  "confidence": float,
  "missing_fields": []
}}"""

        prompt_parts = [prompt]
        if agenda_context:
            prompt_parts.append(f"""---
Actividades ya programadas en la agenda del usuario (para referencia o modificación):
{agenda_context}""")

        prompt_parts.append(f"""---
Historial de la conversación actual:
{history_text}
Usuario: {text}""")

        return "\n\n".join(prompt_parts)

    def parse_conversational(self, text: str, history: list[dict], agenda_context: str | None = None) -> QuestionResponse | ChatResponse | ResultResponse:
        """Parse an activity description conversationally, accumulating context.

        Args:
            text: The current user message.
            history: List of prior exchanges as {role, content} dicts.
            agenda_context: Optional string containing current scheduled activities.

        Returns:
            A QuestionResponse if more info is needed, a ChatResponse for casual chat,
            or a ResultResponse if complete.
        """
        # 1. Truncate history to last 12 entries if needed
        if len(history) > 12:
            history = history[-12:]

        # 2. Count assistant messages to enforce max 4 exchanges (excluding chat responses)
        assistant_count = 0
        for m in history:
            role_val = m.get("role") if isinstance(m, dict) else getattr(m, "role", None)
            type_val = m.get("type") if isinstance(m, dict) else getattr(m, "type", None)
            if role_val == "assistant" and type_val != "chat":
                assistant_count += 1

        # 3. Build prompt
        prompt = self._build_conversational_prompt(text, history, agenda_context)

        # 4. Define the response model for the LLM
        class ConversationalLLMResponse(BaseModel):
            response_type: Literal["question", "result", "chat"] = "question"
            ai_message: str | None = None
            missing_fields: list[str] = []
            name: str | None = None
            activity_type: str | None = None
            is_fixed: bool = True
            is_anchor: bool = False
            difficulty: str | None = None
            priority: str | None = None
            schedule: list[dict] = []
            duracion_minutos: int | None = None
            hora_preferida_inicio: int | None = None
            hora_preferida_fin: int | None = None
            location: str | None = None
            confidence: float = 0.0

        # 5. Call LLM
        try:
            llm_response = self._llm_port.generate(prompt, ConversationalLLMResponse)
        except Exception as e:
            logger.warning("First LLM call failed: %s", e)
            llm_response = None

        # 6. Retry once if failed
        if llm_response is None or llm_response.response_type not in ("question", "result", "chat"):
            try:
                retry_prompt = (
                    prompt
                    + "\n\n IMPORTANTE: Responde SOLO con JSON válido."
                    " Tu respuesta anterior no fue válida. Usa response_type 'question', 'result' o 'chat'."
                )
                llm_response = self._llm_port.generate(retry_prompt, ConversationalLLMResponse)
            except Exception as e:
                logger.error("Second LLM call failed: %s", e)
                llm_response = None

        # 7. If still failed, raise custom exception for HTTP 502
        if llm_response is None or llm_response.response_type not in ("question", "result", "chat"):
            raise LLMGatewayException(
                "Failed to parse activity description conversationally after multiple attempts due to LLM service errors."
            )

        # 8. Enforce 4-exchange limit
        forced_result = False
        if assistant_count >= 4 and llm_response.response_type == "question":
            llm_response.response_type = "result"
            forced_result = True

        # 9. Map response
        if llm_response.response_type == "chat":
            ai_msg = llm_response.ai_message or "¡Hola! ¿En qué te puedo ayudar hoy?"
            return ChatResponse(ai_message=ai_msg)

        elif llm_response.response_type == "question":
            ai_msg = llm_response.ai_message or "Cuéntame un poco más para poder ayudarte."
            return QuestionResponse(
                ai_message=ai_msg,
                missing_fields=llm_response.missing_fields or [],
            )

        else:
            # Map to ResultResponse
            is_fixed = llm_response.is_fixed
            is_anchor = llm_response.is_anchor
            duracion = llm_response.duracion_minutos
            pref_inicio = llm_response.hora_preferida_inicio
            pref_fin = llm_response.hora_preferida_fin

            # Handle range/duration ambiguity: equal range and duration is fixed
            if pref_inicio is not None and pref_fin is not None and duracion is not None:
                if duracion == (pref_fin - pref_inicio):
                    is_fixed = True
                    is_anchor = False
                    pref_inicio_val = pref_inicio
                    pref_fin_val = pref_fin
                    pref_inicio = None
                    pref_fin = None
                    
                    schedule_models = []
                    for s in llm_response.schedule:
                        if isinstance(s, dict):
                            st = s.get("start_time")
                            et = s.get("end_time")
                            if st in (0, None) and et in (0, None):
                                st = pref_inicio_val
                                et = pref_fin_val
                            day_val = s.get("day", "")
                            schedule_models.append(
                                ParsedSchedule(
                                    day=day_val.lower() if day_val else "",
                                    start_time=st or 0,
                                    end_time=et or 0,
                                )
                            )
                else:
                    schedule_models = []
                    for s in llm_response.schedule:
                        if isinstance(s, dict):
                            day_val = s.get("day", "")
                            schedule_models.append(
                                ParsedSchedule(
                                    day=day_val.lower() if day_val else "",
                                    start_time=s.get("start_time") or 0,
                                    end_time=s.get("end_time") or 0,
                                )
                            )
            else:
                schedule_models = []
                for s in llm_response.schedule:
                    if isinstance(s, dict):
                        day_val = s.get("day", "")
                        schedule_models.append(
                            ParsedSchedule(
                                day=day_val.lower() if day_val else "",
                                start_time=s.get("start_time") or 0,
                                end_time=s.get("end_time") or 0,
                            )
                        )

            # Defensive post-parsing validation: is_fixed and is_anchor cannot both be true.
            # If both are true, is_fixed takes priority and is_anchor is set to false.
            if is_fixed and is_anchor:
                is_anchor = False

            return ResultResponse(
                name=llm_response.name,
                activity_type=llm_response.activity_type,
                is_fixed=is_fixed,
                is_anchor=is_anchor,
                difficulty=llm_response.difficulty,
                priority=llm_response.priority,
                schedule=schedule_models,
                duracion_minutos=duracion,
                hora_preferida_inicio=pref_inicio,
                hora_preferida_fin=pref_fin,
                location=llm_response.location,
                confidence=llm_response.confidence,
                missing_fields=llm_response.missing_fields or [] if (assistant_count >= 4 or forced_result) else [],
            )
