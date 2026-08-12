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
