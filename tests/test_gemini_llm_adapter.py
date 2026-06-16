"""Tests for GeminiLLMAdapter.

Verifies the adapter integrates with google-genai correctly,
handles errors, and respects the LLMPort contract.
"""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel


class SampleResponse(BaseModel):
    name: str
    score: float = 0.0


class TestGeminiLLMAdapter:
    @patch("google.genai.Client")
    def test_instantiation_requires_api_key(
        self, MockClient
    ):
        """Adapter should create a genai.Client with the API key."""
        from infrastructure.adapters.outbound.llm.gemini_llm_adapter import (
            GeminiLLMAdapter,
        )

        settings = MagicMock()
        settings.GEMINI_API_KEY = "test-key"

        adapter = GeminiLLMAdapter(settings)
        MockClient.assert_called_once_with(api_key="test-key")

    @patch("google.genai.Client")
    def test_generate_returns_model_instance(
        self, MockClient
    ):
        """generate() should return a populated BaseModel instance."""
        from infrastructure.adapters.outbound.llm.gemini_llm_adapter import (
            GeminiLLMAdapter,
        )

        # Mock the client and its response
        mock_client = MockClient.return_value
        mock_response = MagicMock()
        mock_response.text = '{"name": "Futbol", "score": 0.95}'
        mock_client.models.generate_content.return_value = mock_response

        settings = MagicMock()
        settings.GEMINI_API_KEY = "test-key"

        adapter = GeminiLLMAdapter(settings)
        result = adapter.generate("test prompt", SampleResponse)

        assert isinstance(result, SampleResponse)
        assert result.name == "Futbol"
        assert result.score == 0.95

    @patch("google.genai.Client")
    def test_generate_raises_on_malformed_json(
        self, MockClient
    ):
        """Malformed JSON from the LLM should raise LLMServiceException."""
        from infrastructure.adapters.outbound.llm.gemini_llm_adapter import (
            GeminiLLMAdapter,
        )
        from infrastructure.adapters.inbound.api.middleware import (
            LLMServiceException,
        )

        mock_client = MockClient.return_value
        mock_response = MagicMock()
        mock_response.text = "not valid json"
        mock_client.models.generate_content.return_value = mock_response

        settings = MagicMock()
        settings.GEMINI_API_KEY = "test-key"

        adapter = GeminiLLMAdapter(settings)
        with pytest.raises(LLMServiceException):
            adapter.generate("test", SampleResponse)

    @patch("google.genai.Client")
    def test_generate_configures_response_schema(
        self, MockClient
    ):
        """generate_content should be called with response_schema in config."""
        from google.genai import types
        from infrastructure.adapters.outbound.llm.gemini_llm_adapter import (
            GeminiLLMAdapter,
        )

        # Mock the response so generate() succeeds
        mock_client = MockClient.return_value
        mock_response = MagicMock()
        mock_response.text = '{"name": "Test", "score": 1.0}'
        mock_client.models.generate_content.return_value = mock_response

        settings = MagicMock()
        settings.GEMINI_API_KEY = "test-key"

        adapter = GeminiLLMAdapter(settings)
        adapter.generate("test", SampleResponse)

        mock_client.models.generate_content.assert_called_once()
        call_kwargs = mock_client.models.generate_content.call_args.kwargs

        assert "config" in call_kwargs
        config = call_kwargs["config"]
        assert isinstance(config, types.GenerateContentConfig)
        assert config.response_mime_type == "application/json"
        assert config.response_schema is SampleResponse

    @patch("google.genai.Client")
    def test_generate_raises_timeout_on_exception(
        self, MockClient
    ):
        """Network errors should raise LLMServiceException."""
        from infrastructure.adapters.outbound.llm.gemini_llm_adapter import (
            GeminiLLMAdapter,
        )
        from infrastructure.adapters.inbound.api.middleware import (
            LLMServiceException,
        )

        mock_client = MockClient.return_value
        mock_client.models.generate_content.side_effect = Exception(
            "Connection failed"
        )

        settings = MagicMock()
        settings.GEMINI_API_KEY = "test-key"

        adapter = GeminiLLMAdapter(settings)
        with pytest.raises(LLMServiceException, match="Connection failed"):
            adapter.generate("test", SampleResponse)
