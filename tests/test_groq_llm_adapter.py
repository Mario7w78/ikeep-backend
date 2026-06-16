"""Tests for GroqLLMAdapter.

Verifies the adapter integrates with the OpenAI-compatible API correctly,
handles errors, and respects the LLMPort contract.

NOTE: We patch the adapter module's reference (`groq_llm_adapter.OpenAI`)
rather than `openai.OpenAI` because the adapter uses `from openai import OpenAI`,
creating a local reference that `@patch("openai.OpenAI")` would not affect.
"""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel


class SampleResponse(BaseModel):
    name: str
    score: float = 0.0


# Path to the OpenAI reference used by the adapter module
_PATCH_PATH = "infrastructure.adapters.outbound.llm.groq_llm_adapter.OpenAI"


class TestGroqLLMAdapter:
    @patch(_PATCH_PATH)
    def test_instantiation_requires_api_key(
        self, MockOpenAI
    ):
        """Adapter should create an OpenAI client with Groq's base URL."""
        from infrastructure.adapters.outbound.llm.groq_llm_adapter import (
            GroqLLMAdapter,
        )

        settings = MagicMock()
        settings.GROQ_API_KEY = "test-groq-key"

        adapter = GroqLLMAdapter(settings)
        MockOpenAI.assert_called_once_with(
            api_key="test-groq-key",
            base_url="https://api.groq.com/openai/v1",
        )

    @patch(_PATCH_PATH)
    def test_generate_returns_model_instance(
        self, MockOpenAI
    ):
        """generate() should return a populated BaseModel instance."""
        from infrastructure.adapters.outbound.llm.groq_llm_adapter import (
            GroqLLMAdapter,
        )

        mock_client = MockOpenAI.return_value
        mock_message = MagicMock()
        mock_message.content = '{"name": "Futbol", "score": 0.95}'
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        settings = MagicMock()
        settings.GROQ_API_KEY = "test-groq-key"

        adapter = GroqLLMAdapter(settings)
        result = adapter.generate("test prompt", SampleResponse)

        assert isinstance(result, SampleResponse)
        assert result.name == "Futbol"
        assert result.score == 0.95

    @patch(_PATCH_PATH)
    def test_generate_raises_on_malformed_json(
        self, MockOpenAI
    ):
        """Malformed JSON from the LLM should raise LLMServiceException."""
        from infrastructure.adapters.outbound.llm.groq_llm_adapter import (
            GroqLLMAdapter,
        )
        from infrastructure.adapters.inbound.api.middleware import (
            LLMServiceException,
        )

        mock_client = MockOpenAI.return_value
        mock_message = MagicMock()
        mock_message.content = "not valid json"
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        settings = MagicMock()
        settings.GROQ_API_KEY = "test-groq-key"

        adapter = GroqLLMAdapter(settings)
        with pytest.raises(LLMServiceException):
            adapter.generate("test", SampleResponse)

    @patch(_PATCH_PATH)
    def test_generate_configures_json_response_format(
        self, MockOpenAI
    ):
        """chat.completions.create should be called with response_format and system prompt."""
        from infrastructure.adapters.outbound.llm.groq_llm_adapter import (
            GroqLLMAdapter,
        )

        mock_client = MockOpenAI.return_value
        mock_message = MagicMock()
        mock_message.content = '{"name": "Test", "score": 1.0}'
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        settings = MagicMock()
        settings.GROQ_API_KEY = "test-groq-key"

        adapter = GroqLLMAdapter(settings)
        adapter.generate("test prompt", SampleResponse)

        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs

        assert call_kwargs["response_format"] == {"type": "json_object"}
        messages = call_kwargs["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert "json" in messages[0]["content"].lower()
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "test prompt"
        assert call_kwargs["model"] == "llama-3.3-70b-versatile"

    @patch(_PATCH_PATH)
    def test_generate_raises_on_api_error(
        self, MockOpenAI
    ):
        """API errors should raise LLMServiceException."""
        from infrastructure.adapters.outbound.llm.groq_llm_adapter import (
            GroqLLMAdapter,
        )
        from infrastructure.adapters.inbound.api.middleware import (
            LLMServiceException,
        )

        mock_client = MockOpenAI.return_value
        mock_client.chat.completions.create.side_effect = Exception(
            "Rate limit exceeded"
        )

        settings = MagicMock()
        settings.GROQ_API_KEY = "test-groq-key"

        adapter = GroqLLMAdapter(settings)
        with pytest.raises(LLMServiceException, match="Rate limit exceeded"):
            adapter.generate("test", SampleResponse)

    @patch(_PATCH_PATH)
    def test_generate_raises_on_empty_response(
        self, MockOpenAI
    ):
        """Empty response content should raise LLMServiceException."""
        from infrastructure.adapters.outbound.llm.groq_llm_adapter import (
            GroqLLMAdapter,
        )
        from infrastructure.adapters.inbound.api.middleware import (
            LLMServiceException,
        )

        mock_client = MockOpenAI.return_value
        mock_message = MagicMock()
        mock_message.content = None
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        settings = MagicMock()
        settings.GROQ_API_KEY = "test-groq-key"

        adapter = GroqLLMAdapter(settings)
        with pytest.raises(LLMServiceException, match="empty response"):
            adapter.generate("test", SampleResponse)
