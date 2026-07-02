"""Tests for FailoverAdapter.

Verifies that the failover adapter:
- Returns result from the first provider that succeeds
- Falls through to subsequent providers on failure
- Raises LLMGatewayException if ALL providers fail
- Stops at the first success (does not call remaining providers)
"""

from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from infrastructure.adapters.inbound.api.middleware import (
    LLMGatewayException,
    LLMServiceException,
    LLMTimeoutException,
)


class SampleResponse(BaseModel):
    name: str = "test"


class TestFailoverAdapter:
    def test_first_provider_succeeds(self):
        """When the first provider succeeds, its result is returned."""
        from infrastructure.adapters.outbound.llm.failover_adapter import (
            FailoverAdapter,
        )

        p1 = MagicMock()
        p1.generate.return_value = SampleResponse(name="p1")
        p2 = MagicMock()

        adapter = FailoverAdapter([p1, p2])
        result = adapter.generate("prompt", SampleResponse)

        assert result.name == "p1"
        p1.generate.assert_called_once()
        p2.generate.assert_not_called()

    def test_fallback_to_second_provider(self):
        """When the first fails, the second should be tried."""
        from infrastructure.adapters.outbound.llm.failover_adapter import (
            FailoverAdapter,
        )

        p1 = MagicMock()
        p1.generate.side_effect = LLMServiceException("p1 fail")
        p2 = MagicMock()
        p2.generate.return_value = SampleResponse(name="p2")

        adapter = FailoverAdapter([p1, p2])
        result = adapter.generate("prompt", SampleResponse)

        assert result.name == "p2"
        p1.generate.assert_called_once()
        p2.generate.assert_called_once()

    def test_fallback_on_timeout(self):
        """LLMTimeoutException should also trigger failover."""
        from infrastructure.adapters.outbound.llm.failover_adapter import (
            FailoverAdapter,
        )

        p1 = MagicMock()
        p1.generate.side_effect = LLMTimeoutException("timeout")
        p2 = MagicMock()
        p2.generate.return_value = SampleResponse(name="p2")

        adapter = FailoverAdapter([p1, p2])
        result = adapter.generate("prompt", SampleResponse)

        assert result.name == "p2"

    def test_all_providers_fail_raises_gateway_error(self):
        """When all providers fail, should raise LLMGatewayException."""
        from infrastructure.adapters.outbound.llm.failover_adapter import (
            FailoverAdapter,
        )

        p1 = MagicMock()
        p1.generate.side_effect = LLMServiceException("p1 fail")
        p2 = MagicMock()
        p2.generate.side_effect = LLMServiceException("p2 fail")
        p3 = MagicMock()
        p3.generate.side_effect = LLMTimeoutException("p3 timeout")

        adapter = FailoverAdapter([p1, p2, p3])
        with pytest.raises(LLMGatewayException) as exc_info:
            adapter.generate("prompt", SampleResponse)

        assert "All 3 providers failed" in str(exc_info.value)
        assert p1.generate.call_count == 1
        assert p2.generate.call_count == 1
        assert p3.generate.call_count == 1

    def test_stops_at_first_success(self):
        """Should not call remaining providers after one succeeds."""
        from infrastructure.adapters.outbound.llm.failover_adapter import (
            FailoverAdapter,
        )

        p1 = MagicMock()
        p1.generate.side_effect = LLMServiceException("fail")
        p2 = MagicMock()
        p2.generate.return_value = SampleResponse(name="p2")
        p3 = MagicMock()

        adapter = FailoverAdapter([p1, p2, p3])
        adapter.generate("prompt", SampleResponse)

        assert p1.generate.call_count == 1
        assert p2.generate.call_count == 1
        assert p3.generate.call_count == 0

    def test_empty_providers_list_raises(self):
        """An empty provider list should raise ValueError at init."""
        from infrastructure.adapters.outbound.llm.failover_adapter import (
            FailoverAdapter,
        )

        with pytest.raises(ValueError, match="At least one provider"):
            FailoverAdapter([])

    def test_single_provider_works(self):
        """A single provider should work without failover overhead."""
        from infrastructure.adapters.outbound.llm.failover_adapter import (
            FailoverAdapter,
        )

        p1 = MagicMock()
        p1.generate.return_value = SampleResponse(name="solo")

        adapter = FailoverAdapter([p1])
        result = adapter.generate("prompt", SampleResponse)

        assert result.name == "solo"
