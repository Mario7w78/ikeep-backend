"""Tests for OpenAICompatibleAdapter.

Verifies the generic adapter works with any OpenAI-compatible endpoint
(Groq, Cerebras, Mistral) by mocking the OpenAI client.
"""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from infrastructure.adapters.inbound.api.middleware import LLMServiceException


class SampleResponse(BaseModel):
    name: str
    score: float = 0.0


_PATCH_PATH = (
    "infrastructure.adapters.outbound.llm"
    ".openai_compatible_adapter.OpenAI"
)


class TestOpenAICompatibleAdapter:
    @patch(_PATCH_PATH)
    def test_instantiation_creates_client(self, MockOpenAI):
        """Adapter should create an OpenAI client with given config."""
        from infrastructure.adapters.outbound.llm.openai_compatible_adapter import (
            OpenAICompatibleAdapter,
        )

        adapter = OpenAICompatibleAdapter(
            api_key="test-key",
            base_url="https://api.test.com/v1",
            default_model="test-model",
        )

        MockOpenAI.assert_called_once_with(
            api_key="test-key",
            base_url="https://api.test.com/v1",
        )

    @patch(_PATCH_PATH)
    def test_generate_returns_model_instance(self, MockOpenAI):
        """generate() should return a populated BaseModel instance."""
        from infrastructure.adapters.outbound.llm.openai_compatible_adapter import (
            OpenAICompatibleAdapter,
        )

        mock_client = MockOpenAI.return_value
        mock_message = MagicMock()
        mock_message.content = '{"name": "Test", "score": 0.9}'
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        adapter = OpenAICompatibleAdapter(
            api_key="key", base_url="https://url/v1", default_model="m"
        )
        result = adapter.generate("test prompt", SampleResponse)

        assert isinstance(result, SampleResponse)
        assert result.name == "Test"
        assert result.score == 0.9

    @patch(_PATCH_PATH)
    def test_generate_uses_correct_model_and_url(self, MockOpenAI):
        """The adapter should call the API with the configured model and URL."""
        from infrastructure.adapters.outbound.llm.openai_compatible_adapter import (
            OpenAICompatibleAdapter,
        )

        mock_client = MockOpenAI.return_value
        mock_message = MagicMock()
        mock_message.content = '{"name": "X", "score": 1.0}'
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        adapter = OpenAICompatibleAdapter(
            api_key="gk-prod",
            base_url="https://api.cerebras.ai/v1",
            default_model="gpt-oss-120b",
        )
        adapter.generate("hello", SampleResponse)

        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "gpt-oss-120b"
        assert call_kwargs["response_format"] == {"type": "json_object"}
        assert call_kwargs["temperature"] == 0.1

    @patch(_PATCH_PATH)
    def test_generate_sends_system_prompt_with_schema(self, MockOpenAI):
        """System prompt should instruct JSON output with the schema."""
        from infrastructure.adapters.outbound.llm.openai_compatible_adapter import (
            OpenAICompatibleAdapter,
        )

        mock_client = MockOpenAI.return_value
        mock_message = MagicMock()
        mock_message.content = '{"name": "X", "score": 1.0}'
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        adapter = OpenAICompatibleAdapter(
            api_key="k", base_url="https://url/v1", default_model="m"
        )
        adapter.generate("my prompt", SampleResponse)

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert "JSON" in messages[0]["content"]
        assert "type" in messages[0]["content"]  # schema reference
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "my prompt"

    @patch(_PATCH_PATH)
    def test_generate_raises_on_malformed_json(self, MockOpenAI):
        """Malformed JSON should raise LLMServiceException."""
        from infrastructure.adapters.outbound.llm.openai_compatible_adapter import (
            OpenAICompatibleAdapter,
        )

        mock_client = MockOpenAI.return_value
        mock_message = MagicMock()
        mock_message.content = "not json"
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        adapter = OpenAICompatibleAdapter(
            api_key="k", base_url="https://url/v1", default_model="m"
        )
        with pytest.raises(LLMServiceException):
            adapter.generate("test", SampleResponse)

    @patch(_PATCH_PATH)
    def test_generate_raises_on_empty_response(self, MockOpenAI):
        """Empty response content should raise LLMServiceException."""
        from infrastructure.adapters.outbound.llm.openai_compatible_adapter import (
            OpenAICompatibleAdapter,
        )

        mock_client = MockOpenAI.return_value
        mock_message = MagicMock()
        mock_message.content = None
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        adapter = OpenAICompatibleAdapter(
            api_key="k", base_url="https://url/v1", default_model="m"
        )
        with pytest.raises(LLMServiceException, match="empty response"):
            adapter.generate("test", SampleResponse)

    @patch(_PATCH_PATH)
    def test_generate_raises_on_api_error(self, MockOpenAI):
        """API errors should raise LLMServiceException."""
        from infrastructure.adapters.outbound.llm.openai_compatible_adapter import (
            OpenAICompatibleAdapter,
        )

        mock_client = MockOpenAI.return_value
        mock_client.chat.completions.create.side_effect = Exception(
            "Connection refused"
        )

        adapter = OpenAICompatibleAdapter(
            api_key="k", base_url="https://url/v1", default_model="m"
        )
        with pytest.raises(LLMServiceException, match="Connection refused"):
            adapter.generate("test", SampleResponse)
