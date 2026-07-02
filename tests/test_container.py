"""Tests for DI container wiring.

Verifies that the container can resolve LLMPort and LLMParserService
with the correct implementations.
"""

from unittest.mock import patch

from infrastructure.adapters.outbound.llm.failover_adapter import (
    FailoverAdapter,
)
from infrastructure.adapters.outbound.llm.circuit_breaker_adapter import (
    CircuitBreakerAdapter,
)
from infrastructure.adapters.outbound.llm.openai_compatible_adapter import (
    OpenAICompatibleAdapter,
)


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
    def test_container_resolves_failover_adapter(self, MockOpenAI):
        """The container should resolve a FailoverAdapter with 3 providers."""
        from infrastructure.config.container import ApplicationContainer
        from infrastructure.config.settings import Settings
        from domain.ports.outbound.llm_port import LLMPort

        container = ApplicationContainer()
        container.settings.override(Settings(
            GROQ_API_KEY="test-groq-key",
        ))

        adapter = container.llm_adapter()
        assert isinstance(adapter, LLMPort)
        assert isinstance(adapter, FailoverAdapter)

        # Should have 3 providers: Groq, Cerebras, Mistral
        assert len(adapter._providers) == 3
        for provider in adapter._providers:
            assert isinstance(provider, CircuitBreakerAdapter)
            assert isinstance(provider.inner, OpenAICompatibleAdapter)
