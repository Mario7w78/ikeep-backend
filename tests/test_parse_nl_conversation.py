"""Tests for parse_nl_conversation — conversational NL parsing.

Verifies:
- Vague input returns QuestionResponse with type="question"
- Complete input returns ResultResponse with type="result"
- History truncation (>12 entries → keep last 12)
- 4-exchange force-result behavior
- Invalid JSON retry with fallback
"""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from schemas.parse_nl import ParsedSchedule, QuestionResponse, ResultResponse


class TestParseNLConversation:
    """Tests for LLMParserService.parse_conversational()."""

    # ── Helper: build mock LLM response models ──────────────────────

    @staticmethod
    def _mock_question_response(
        ai_message="¿Qué tipo de actividad querés agregar?",
        missing_fields=None,
    ):
        """Build a mock object that looks like a ConversationalLLMResponse with type question."""
        mock = MagicMock()
        mock.response_type = "question"
        mock.ai_message = ai_message
        mock.missing_fields = missing_fields or ["activity_type"]
        mock.name = None
        mock.activity_type = None
        mock.is_fixed = True
        mock.is_anchor = False
        mock.difficulty = None
        mock.priority = None
        mock.schedule = []
        mock.duracion_minutos = None
        mock.hora_preferida_inicio = None
        mock.hora_preferida_fin = None
        mock.location = None
        mock.confidence = 0.0
        return mock

    @staticmethod
    def _mock_result_response(
        name="Estudiar matemáticas",
        activity_type="tarea",
        schedule_data=None,
        confidence=0.95,
    ):
        """Build a mock object that looks like a ConversationalLLMResponse with type result."""
        mock = MagicMock()
        mock.response_type = "result"
        mock.ai_message = None
        mock.missing_fields = []
        mock.name = name
        mock.activity_type = activity_type
        mock.is_fixed = True
        mock.is_anchor = False
        mock.difficulty = "alta"
        mock.priority = None
        mock.schedule = schedule_data or [
            {"day": "lunes", "start_time": 1080, "end_time": 1200},
            {"day": "miércoles", "start_time": 1080, "end_time": 1200},
        ]
        mock.duracion_minutos = 120
        mock.hora_preferida_inicio = None
        mock.hora_preferida_fin = None
        mock.location = None
        mock.confidence = confidence
        return mock

    # ── Tests ───────────────────────────────────────────────────────

    def test_vague_input_returns_question(self):
        """Vague input with empty history should return a QuestionResponse."""
        from domain.services.llm_parser_service import LLMParserService

        mock_llm = MagicMock()
        mock_llm.generate.return_value = self._mock_question_response()

        service = LLMParserService(mock_llm)
        result = service.parse_conversational("hacer ejercicio", [])

        assert isinstance(result, QuestionResponse)
        assert result.type == "question"
        assert result.ai_message
        assert isinstance(result.missing_fields, list)

    def test_complete_input_returns_result(self):
        """Complete input should return a ResultResponse."""
        from domain.services.llm_parser_service import LLMParserService

        mock_llm = MagicMock()
        mock_llm.generate.return_value = self._mock_result_response()

        service = LLMParserService(mock_llm)
        result = service.parse_conversational(
            "Estudiar matemáticas los lunes y miércoles de 18 a 20",
            [],
        )

        assert isinstance(result, ResultResponse)
        assert result.type == "result"
        assert result.name == "Estudiar matemáticas"
        assert result.confidence > 0.0
        assert len(result.schedule) == 2

    def test_result_response_inherits_parse_nl_response_fields(self):
        """ResultResponse should have all ParseNLResponse fields."""
        from domain.services.llm_parser_service import LLMParserService

        mock_llm = MagicMock()
        mock_llm.generate.return_value = self._mock_result_response()

        service = LLMParserService(mock_llm)
        result = service.parse_conversational(
            "Estudiar matemáticas los lunes y miércoles de 18 a 20",
            [],
        )

        # Should have standard ParseNLResponse fields
        assert result.name is not None
        assert result.activity_type is not None
        assert result.is_fixed is True
        assert result.is_anchor is False
        assert result.difficulty is not None
        assert isinstance(result.schedule, list)
        assert result.confidence > 0.0

    def test_history_truncation(self):
        """History with >12 entries should be truncated to last 12."""
        from domain.services.llm_parser_service import LLMParserService

        mock_llm = MagicMock()
        mock_llm.generate.return_value = self._mock_question_response()

        service = LLMParserService(mock_llm)

        # Build 15 entries (more than 12)
        long_history = []
        for i in range(15):
            long_history.append({
                "role": "user" if i % 2 == 0 else "assistant",
                "content": f"Mensaje {i}",
            })

        service.parse_conversational("nuevo mensaje", long_history)

        # The prompt should contain only the last 12 entries
        call_args = mock_llm.generate.call_args
        prompt = call_args[0][0]

        # "Mensaje 0" (the oldest) should NOT be in the truncated prompt
        assert "Mensaje 0" not in prompt
        # "Mensaje 14" (the newest) SHOULD be in the prompt
        assert "Mensaje 14" in prompt
        # "Mensaje 3" (within last 12: entries 3-14) should be included
        assert "Mensaje 3" in prompt

    def test_four_exchange_force_result(self):
        """After 4 assistant exchanges, force result even if LLM returns question."""
        from domain.services.llm_parser_service import LLMParserService

        mock_llm = MagicMock()
        # LLM returns question, but we've had 4 exchanges
        mock_llm.generate.return_value = self._mock_question_response(
            ai_message="¿Qué más necesito saber?",
            missing_fields=["duracion_minutos"],
        )

        service = LLMParserService(mock_llm)

        # History with 4 assistant messages (4 exchanges)
        history = [
            {"role": "user", "content": "hacer ejercicio"},
            {"role": "assistant", "content": "¿Qué días?"},
            {"role": "user", "content": "lunes y miércoles"},
            {"role": "assistant", "content": "¿Cuánto dura?"},
            {"role": "user", "content": "30 minutos"},
            {"role": "assistant", "content": "¿A qué hora?"},
            {"role": "user", "content": "a las 18"},
            {"role": "assistant", "content": "¿Dónde?"},
            {"role": "user", "content": "en casa"},
        ]

        result = service.parse_conversational("hacer ejercicio en casa", history)

        # Should be forced to result despite LLM returning question
        assert isinstance(result, ResultResponse)
        assert result.type == "result"

    def test_three_exchange_still_question(self):
        """With less than 4 exchanges, LLM question response stays as question."""
        from domain.services.llm_parser_service import LLMParserService

        mock_llm = MagicMock()
        mock_llm.generate.return_value = self._mock_question_response(
            ai_message="¿Qué días pensás hacer ejercicio?",
            missing_fields=["schedule"],
        )

        service = LLMParserService(mock_llm)

        # History with only 1 assistant message (1 exchange)
        history = [
            {"role": "user", "content": "hacer ejercicio"},
            {"role": "assistant", "content": "¿Qué tipo de actividad?"},
            {"role": "user", "content": "gimnasio"},
        ]

        result = service.parse_conversational("voy al gimnasio", history)

        # Should remain question (only 1 exchange so far)
        assert isinstance(result, QuestionResponse)
        assert result.type == "question"
        assert "días" in result.ai_message or "¿Qué" in result.ai_message

    def test_invalid_json_retry_and_fallback(self):
        """If LLM returns invalid JSON twice, service raises LLMGatewayException."""
        from domain.services.llm_parser_service import LLMParserService
        from infrastructure.adapters.inbound.api.middleware import LLMGatewayException

        mock_llm = MagicMock()
        # Both calls fail (return None doesn't happen since generate returns BaseModel)
        # We use side_effect to raise exception both times
        mock_llm.generate.side_effect = [
            Exception("Invalid JSON"),
            Exception("Invalid JSON again"),
        ]

        service = LLMParserService(mock_llm)
        with pytest.raises(LLMGatewayException):
            service.parse_conversational("hacer ejercicio", [])

        assert mock_llm.generate.call_count == 2

    def test_retry_happens_on_first_failure(self):
        """If first LLM call fails, verify retry is attempted."""
        from domain.services.llm_parser_service import LLMParserService

        mock_llm = MagicMock()
        # First call fails, second succeeds with question
        mock_llm.generate.side_effect = [
            Exception("First call failed"),
            self._mock_question_response(
                ai_message="¿Qué días?",
                missing_fields=["schedule"],
            ),
        ]

        service = LLMParserService(mock_llm)
        result = service.parse_conversational("hacer ejercicio", [])

        assert isinstance(result, QuestionResponse)
        assert result.type == "question"
        assert mock_llm.generate.call_count == 2

    def test_prompt_includes_system_instructions(self):
        """The conversational prompt should include system instructions."""
        from domain.services.llm_parser_service import LLMParserService

        mock_llm = MagicMock()
        mock_llm.generate.return_value = self._mock_question_response()

        service = LLMParserService(mock_llm)
        service.parse_conversational("correr los sábados", [])

        call_args = mock_llm.generate.call_args
        prompt = call_args[0][0]

        # Should contain key system instructions
        assert "planificador horario" in prompt
        assert "response_type" in prompt
        assert "español neutro" in prompt or "neutro" in prompt
        assert "JSON" in prompt.upper() or "json" in prompt

    def test_prompt_includes_few_shot_examples(self):
        """The conversational prompt should include few-shot examples."""
        from domain.services.llm_parser_service import LLMParserService

        mock_llm = MagicMock()
        mock_llm.generate.return_value = self._mock_question_response()

        service = LLMParserService(mock_llm)
        service.parse_conversational("hacer ejercicio", [])

        call_args = mock_llm.generate.call_args
        prompt = call_args[0][0]

        # Should contain few-shot examples
        assert "Ejemplo 1" in prompt
        assert "hacer ejercicio" in prompt
        assert "Desayunar" in prompt

    def test_conversational_prompt_includes_history(self):
        """The conversational prompt should include conversation history."""
        from domain.services.llm_parser_service import LLMParserService

        mock_llm = MagicMock()
        mock_llm.generate.return_value = self._mock_question_response()

        service = LLMParserService(mock_llm)

        history = [
            {"role": "user", "content": "quiero agregó una actividad"},
            {"role": "assistant", "content": "¿Qué tipo de actividad?"},
            {"role": "user", "content": "clase de yoga"},
        ]

        service.parse_conversational("los lunes", history)

        call_args = mock_llm.generate.call_args
        prompt = call_args[0][0]

        assert "quiero agregó una actividad" in prompt
        assert "clase de yoga" in prompt
        assert "Usuario:" in prompt
        assert "Asistente:" in prompt

    def test_result_response_maps_schedule_null_to_zero(self):
        """ResultResponse should handle null start_time/end_time in schedule by mapping to 0."""
        from domain.services.llm_parser_service import LLMParserService

        mock_llm = MagicMock()
        mock_llm.generate.return_value = self._mock_result_response(
            schedule_data=[
                {"day": "lunes", "start_time": None, "end_time": None},
                {"day": "martes", "start_time": None, "end_time": None},
            ],
        )

        service = LLMParserService(mock_llm)
        result = service.parse_conversational("actividad sin horario fijo", [])

        assert isinstance(result, ResultResponse)
        assert len(result.schedule) == 2
        assert result.schedule[0].start_time == 0
        assert result.schedule[0].end_time == 0
        assert result.schedule[1].start_time == 0
        assert result.schedule[1].end_time == 0

    def test_parse_conversational_with_pydantic_history(self):
        """Verify that parse_conversational handles history with Pydantic ConversationMessage objects."""
        from domain.services.llm_parser_service import LLMParserService
        from schemas.parse_nl import ConversationMessage

        mock_llm = MagicMock()
        mock_llm.generate.return_value = self._mock_question_response()

        service = LLMParserService(mock_llm)

        history = [
            ConversationMessage(role="user", content="quiero agregar una actividad"),
            ConversationMessage(role="assistant", content="¿Qué tipo de actividad?"),
        ]

        result = service.parse_conversational("clase de yoga", history)
        assert isinstance(result, QuestionResponse)

