"""Tests for LLMParserService.

Verifies prompt building, LLMPort integration, retry logic, and
response mapping.
"""

from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from schemas.parse_nl import ParseNLResponse, ParsedSchedule


class TestLLMParserService:
    def test_parse_returns_parse_nl_response(self):
        """parse() should return a ParseNLResponse on success."""
        from domain.services.llm_parser_service import LLMParserService

        mock_llm = MagicMock()
        mock_llm.generate.return_value = ParseNLResponse(
            name="Futbol",
            activity_type="tarea",
            confidence=0.92,
            schedule=[ParsedSchedule(day="Lunes", start_time=540, end_time=600)],
            missing_fields=[],
        )

        service = LLMParserService(mock_llm)
        result = service.parse("futbol los lunes de 9 a 10")

        assert isinstance(result, ParseNLResponse)
        assert result.name == "Futbol"
        assert result.confidence == 0.92

    def test_parse_passes_text_to_build_prompt(self):
        """The text should be incorporated into the prompt sent to the LLM."""
        from domain.services.llm_parser_service import LLMParserService

        mock_llm = MagicMock()
        mock_llm.generate.return_value = ParseNLResponse(
            name="Natacion",
            schedule=[ParsedSchedule(day="Martes", start_time=480, end_time=540)],
        )

        service = LLMParserService(mock_llm)
        service.parse("entreno de natacion los martes")

        # Verify the prompt contains the user's text and a structured output request
        call_args = mock_llm.generate.call_args
        prompt = call_args[0][0]  # first positional arg
        assert "entreno de natacion" in prompt
        assert "json" in prompt.lower() or "JSON" in prompt

    def test_parse_retries_once_on_parse_failure(self):
        """If LLMPort returns invalid data, the service should retry once."""
        from domain.services.llm_parser_service import LLMParserService

        mock_llm = MagicMock()
        # First call returns a minimal/empty response, second returns valid
        mock_llm.generate.side_effect = [
            ParseNLResponse(confidence=0.0, missing_fields=["name", "schedule"]),
            ParseNLResponse(name="Futbol", confidence=0.95),
        ]

        service = LLMParserService(mock_llm)
        result = service.parse("futbol")

        assert mock_llm.generate.call_count == 2
        assert result.name == "Futbol"
        assert result.confidence == 0.95

    def test_parse_raises_after_two_failures(self):
        """After exhausting retries, the service should raise."""
        from domain.services.llm_parser_service import LLMParserService

        mock_llm = MagicMock()
        mock_llm.generate.return_value = ParseNLResponse(
            confidence=0.0,
            missing_fields=["name", "schedule", "location"],
        )

        service = LLMParserService(mock_llm)
        with pytest.raises(RuntimeError, match="Failed to parse activity"):
            service.parse("some text")

        # Should have been called twice (initial + retry)
        assert mock_llm.generate.call_count == 2

    def test_build_prompt_includes_few_shot_examples(self):
        """The prompt builder should include few-shot examples."""
        from domain.services.llm_parser_service import LLMParserService

        mock_llm = MagicMock()
        mock_llm.generate.return_value = ParseNLResponse()

        service = LLMParserService(mock_llm)
        # Access build_prompt directly to test it in isolation
        prompt = service.build_prompt("correr los sabados")

        # Should contain few-shot examples
        assert "Ejemplo" in prompt or "ejemplo" in prompt
        assert "entreno" in prompt.lower() or "futbol" in prompt.lower() or "correr" in prompt

    def test_service_uses_correct_response_model(self):
        """The service should pass ParseNLResponse as the response_model."""
        from domain.services.llm_parser_service import LLMParserService

        mock_llm = MagicMock()
        mock_llm.generate.return_value = ParseNLResponse(
            name="Test",
            schedule=[ParsedSchedule(day="Lunes", start_time=0, end_time=60)],
        )

        service = LLMParserService(mock_llm)
        service.parse("test")

        call_args = mock_llm.generate.call_args
        # response_model is the second positional arg
        response_model = call_args[0][1]
        assert response_model is ParseNLResponse

    def test_parse_conversational_returns_chat_response(self):
        """parse_conversational should return ChatResponse when response_type is 'chat'."""
        from domain.services.llm_parser_service import LLMParserService
        from schemas.parse_nl import ChatResponse

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.response_type = "chat"
        mock_response.ai_message = "Hola, soy un asistente virtual"
        mock_llm.generate.return_value = mock_response

        service = LLMParserService(mock_llm)
        result = service.parse_conversational("hola", [])

        assert isinstance(result, ChatResponse)
        assert result.type == "chat"
        assert result.ai_message == "Hola, soy un asistente virtual"

    def test_parse_conversational_lowercase_days(self):
        """parse_conversational should normalize days to lowercase."""
        from domain.services.llm_parser_service import LLMParserService
        from schemas.parse_nl import ResultResponse

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.response_type = "result"
        mock_response.name = "Clase"
        mock_response.activity_type = None
        mock_response.schedule = [{"day": "LUNES", "start_time": 60, "end_time": 120}]
        mock_response.is_fixed = True
        mock_response.is_anchor = False
        mock_response.duracion_minutos = 60
        mock_response.hora_preferida_inicio = None
        mock_response.hora_preferida_fin = None
        mock_response.difficulty = None
        mock_response.priority = None
        mock_response.location = None
        mock_response.confidence = 0.9
        mock_response.missing_fields = []
        mock_llm.generate.return_value = mock_response

        service = LLMParserService(mock_llm)
        result = service.parse_conversational("clase lunes", [])

        assert isinstance(result, ResultResponse)
        assert result.schedule[0].day == "lunes"

    def test_parse_conversational_defensive_is_fixed_priority(self):
        """is_fixed has priority over is_anchor if both are True."""
        from domain.services.llm_parser_service import LLMParserService
        from schemas.parse_nl import ResultResponse

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.response_type = "result"
        mock_response.name = "Clase"
        mock_response.activity_type = None
        mock_response.schedule = [{"day": "lunes", "start_time": 60, "end_time": 120}]
        mock_response.is_fixed = True
        mock_response.is_anchor = True
        mock_response.duracion_minutos = 60
        mock_response.hora_preferida_inicio = None
        mock_response.hora_preferida_fin = None
        mock_response.difficulty = None
        mock_response.priority = None
        mock_response.location = None
        mock_response.confidence = 0.9
        mock_response.missing_fields = []
        mock_llm.generate.return_value = mock_response

        service = LLMParserService(mock_llm)
        result = service.parse_conversational("clase", [])

        assert isinstance(result, ResultResponse)
        assert result.is_fixed is True
        assert result.is_anchor is False

    def test_parse_conversational_range_duration_ambiguity(self):
        """If duration equals range difference, it is treated as fixed and preferred times are reset."""
        from domain.services.llm_parser_service import LLMParserService
        from schemas.parse_nl import ResultResponse

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.response_type = "result"
        mock_response.name = "Clase"
        mock_response.activity_type = None
        mock_response.schedule = [{"day": "lunes", "start_time": 0, "end_time": 0}]
        mock_response.is_fixed = False
        mock_response.is_anchor = True
        mock_response.duracion_minutos = 60
        mock_response.hora_preferida_inicio = 480
        mock_response.hora_preferida_fin = 540
        mock_response.difficulty = None
        mock_response.priority = None
        mock_response.location = None
        mock_response.confidence = 0.9
        mock_response.missing_fields = []
        mock_llm.generate.return_value = mock_response

        service = LLMParserService(mock_llm)
        result = service.parse_conversational("clase", [])

        assert isinstance(result, ResultResponse)
        assert result.is_fixed is True
        assert result.is_anchor is False
        assert result.hora_preferida_inicio is None
        assert result.hora_preferida_fin is None
        assert result.schedule[0].start_time == 480
        assert result.schedule[0].end_time == 540

    def test_parse_conversational_exclude_chat_from_exchange_count(self):
        """assistant responses of type 'chat' should be excluded from exchange count."""
        from domain.services.llm_parser_service import LLMParserService
        from schemas.parse_nl import ResultResponse

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.response_type = "result"
        mock_response.name = "Clase"
        mock_response.activity_type = None
        mock_response.schedule = []
        mock_response.is_fixed = True
        mock_response.is_anchor = False
        mock_response.duracion_minutos = None
        mock_response.hora_preferida_inicio = None
        mock_response.hora_preferida_fin = None
        mock_response.difficulty = None
        mock_response.priority = None
        mock_response.location = None
        mock_response.confidence = 0.9
        mock_response.missing_fields = []
        mock_llm.generate.return_value = mock_response

        # History contains 4 assistant messages, but 2 are chat
        history = [
            {"role": "user", "content": "hola"},
            {"role": "assistant", "content": "hola", "type": "chat"},
            {"role": "user", "content": "quiero agendar clase"},
            {"role": "assistant", "content": "¿de qué?", "type": "question"},
            {"role": "user", "content": "matematicas"},
            {"role": "assistant", "content": "chiste", "type": "chat"},
            {"role": "user", "content": "ok"},
            {"role": "assistant", "content": "¿dónde?", "type": "question"},
        ]

        service = LLMParserService(mock_llm)
        # Call parse_conversational. If assistant_count counted chat, it would be 4, forcing result.
        # But excluding chat, it should be 2. Let's make sure it propagates correctly.
        result = service.parse_conversational("salon 101", history)
        assert isinstance(result, ResultResponse)
        assert result.missing_fields == []  # Not forced, so it should be empty list as returned by mock_response

    def test_parse_conversational_propagate_missing_fields_on_limit(self):
        """If assistant_count >= 4, propagate real missing_fields in ResultResponse."""
        from domain.services.llm_parser_service import LLMParserService
        from schemas.parse_nl import ResultResponse

        mock_llm = MagicMock()
        mock_response = MagicMock()
        # Mock LLM returns question with missing fields, but we force it to result
        mock_response.response_type = "question"
        mock_response.missing_fields = ["schedule", "duracion_minutos"]
        mock_response.name = "Clase"
        mock_response.activity_type = None
        mock_response.schedule = []
        mock_response.is_fixed = False
        mock_response.is_anchor = False
        mock_response.duracion_minutos = None
        mock_response.hora_preferida_inicio = None
        mock_response.hora_preferida_fin = None
        mock_response.difficulty = None
        mock_response.priority = None
        mock_response.location = None
        mock_response.confidence = 0.5
        mock_llm.generate.return_value = mock_response

        # 4 assistant messages of type 'question'
        history = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b", "type": "question"},
            {"role": "user", "content": "c"},
            {"role": "assistant", "content": "d", "type": "question"},
            {"role": "user", "content": "e"},
            {"role": "assistant", "content": "f", "type": "question"},
            {"role": "user", "content": "g"},
            {"role": "assistant", "content": "h", "type": "question"},
        ]

        service = LLMParserService(mock_llm)
        result = service.parse_conversational("i", history)

        assert isinstance(result, ResultResponse)
        assert result.missing_fields == ["schedule", "duracion_minutos"]
