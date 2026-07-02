"""Tests for CircuitBreakerAdapter.

Verifies that the circuit breaker:
- Passes through successful calls (CLOSED state)
- Opens after max_failures consecutive failures
- Rejects calls while OPEN (before reset timeout)
- Transitions to HALF_OPEN after reset timeout
- Closes again after a successful call from HALF_OPEN
"""

import time
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from infrastructure.adapters.inbound.api.middleware import LLMServiceException


class SampleResponse(BaseModel):
    name: str = "test"


class TestCircuitBreakerAdapter:
    def test_healthy_call_passes_through(self):
        """When inner adapter succeeds, result should be returned directly."""
        from infrastructure.adapters.outbound.llm.circuit_breaker_adapter import (
            CircuitBreakerAdapter,
        )

        inner = MagicMock()
        inner.generate.return_value = SampleResponse(name="ok")

        cb = CircuitBreakerAdapter(inner, max_failures=3, reset_timeout=30)
        result = cb.generate("prompt", SampleResponse)

        assert isinstance(result, SampleResponse)
        assert result.name == "ok"
        inner.generate.assert_called_once_with("prompt", SampleResponse)

    def test_opens_after_max_failures(self):
        """After max_failures consecutive errors, state becomes OPEN."""
        from infrastructure.adapters.outbound.llm.circuit_breaker_adapter import (
            CircuitBreakerAdapter,
        )

        inner = MagicMock()
        inner.generate.side_effect = LLMServiceException("fail")

        cb = CircuitBreakerAdapter(inner, max_failures=2, reset_timeout=60)

        # First two calls raise normally
        with pytest.raises(LLMServiceException):
            cb.generate("p", SampleResponse)
        with pytest.raises(LLMServiceException):
            cb.generate("p", SampleResponse)

        # Third call should be blocked by circuit breaker
        with pytest.raises(LLMServiceException, match="circuit breaker OPEN"):
            cb.generate("p", SampleResponse)

        # Inner was called only twice (third was blocked)
        assert inner.generate.call_count == 2

    def test_single_failure_does_not_open(self):
        """A single failure should not open the circuit."""
        from infrastructure.adapters.outbound.llm.circuit_breaker_adapter import (
            CircuitBreakerAdapter,
        )

        inner = MagicMock()
        inner.generate.side_effect = [
            LLMServiceException("fail"),  # first fails
            SampleResponse(name="ok"),     # second succeeds
        ]

        cb = CircuitBreakerAdapter(inner, max_failures=3, reset_timeout=60)

        with pytest.raises(LLMServiceException):
            cb.generate("p", SampleResponse)

        # Should still work (circuit is CLOSED)
        result = cb.generate("p", SampleResponse)
        assert result.name == "ok"
        assert inner.generate.call_count == 2

    def test_reset_after_timeout(self):
        """After reset_timeout seconds, circuit transitions to HALF_OPEN."""
        from infrastructure.adapters.outbound.llm.circuit_breaker_adapter import (
            CircuitBreakerAdapter,
        )

        inner = MagicMock()
        inner.generate.side_effect = LLMServiceException("fail")

        cb = CircuitBreakerAdapter(inner, max_failures=1, reset_timeout=0.01)

        # First call fails, circuit opens
        with pytest.raises(LLMServiceException):
            cb.generate("p", SampleResponse)

        # Wait for timeout
        time.sleep(0.02)

        # Inner should be called again (HALF_OPEN)
        with pytest.raises(LLMServiceException):
            cb.generate("p", SampleResponse)

        # Inner was called twice (once before open, once during half-open)
        assert inner.generate.call_count == 2

    def test_closes_after_half_open_success(self):
        """A successful call in HALF_OPEN should reset the circuit to CLOSED."""
        from infrastructure.adapters.outbound.llm.circuit_breaker_adapter import (
            CircuitBreakerAdapter,
        )

        inner = MagicMock()

        def side_effect(*args, **kwargs):
            raise LLMServiceException("fail")

        inner.generate.side_effect = side_effect

        cb = CircuitBreakerAdapter(inner, max_failures=2, reset_timeout=0.01)

        # Open the circuit
        with pytest.raises(LLMServiceException):
            cb.generate("p", SampleResponse)
        with pytest.raises(LLMServiceException):
            cb.generate("p", SampleResponse)

        # Wait for reset
        time.sleep(0.02)

        # Now make it succeed
        inner.generate.side_effect = None
        inner.generate.return_value = SampleResponse(name="recovered")

        result = cb.generate("p", SampleResponse)
        assert result.name == "recovered"

        # Next call should go through normally (CLOSED)
        result2 = cb.generate("p", SampleResponse)
        assert result2.name == "recovered"
        assert inner.generate.call_count == 4  # 2 fails + 2 successes

    def test_remaining_failures_respected(self):
        """max_failures should reset after a success, not accumulate."""
        from infrastructure.adapters.outbound.llm.circuit_breaker_adapter import (
            CircuitBreakerAdapter,
        )

        inner = MagicMock()
        cb = CircuitBreakerAdapter(inner, max_failures=2, reset_timeout=60)

        # Fail once, succeed once, fail once — should NOT open yet
        inner.generate.side_effect = [
            LLMServiceException("fail"),  # 1 failure
            SampleResponse(name="ok"),     # success resets counter
            LLMServiceException("fail"),   # 1 failure (counter reset)
        ]
        with pytest.raises(LLMServiceException):
            cb.generate("p", SampleResponse)
        result = cb.generate("p", SampleResponse)
        assert result.name == "ok"
        with pytest.raises(LLMServiceException):
            cb.generate("p", SampleResponse)

        # Circuit should still be closed — only 1 failure since last success
        inner.generate.side_effect = None
        inner.generate.return_value = SampleResponse(name="still-ok")
        result = cb.generate("p", SampleResponse)
        assert result.name == "still-ok"
