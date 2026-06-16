"""Tests for DI container wiring.

Verifies that the container can resolve LLMPort and LLMParserService
with the correct implementations.
"""

from unittest.mock import patch


class TestContainerWiring:
    @patch("openai.OpenAI")
    def test_container_resolves_llm_parser_service(self, MockOpenAI):
        """The container should resolve LLMParserService."""
        from infrastructure.config.container import ApplicationContainer
        from infrastructure.config.settings import Settings
        from domain.services.llm_parser_service import LLMParserService

        container = ApplicationContainer()
        container.settings.override(Settings(GROQ_API_KEY="test-groq-key"))

        parser = container.llm_parser_service()
        assert isinstance(parser, LLMParserService)

    @patch("openai.OpenAI")
    def test_container_resolves_llm_adapter(self, MockOpenAI):
        """The container should resolve LLMPort (GroqLLMAdapter)."""
        from infrastructure.config.container import ApplicationContainer
        from infrastructure.config.settings import Settings
        from domain.ports.outbound.llm_port import LLMPort

        container = ApplicationContainer()
        container.settings.override(Settings(GROQ_API_KEY="test-groq-key"))

        adapter = container.llm_adapter()
        assert isinstance(adapter, LLMPort)
        assert type(adapter).__name__ == "GroqLLMAdapter"
