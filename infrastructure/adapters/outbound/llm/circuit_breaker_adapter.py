"""Circuit breaker wrapper for LLM adapters.

Prevents hammering a failing provider by stopping calls after a threshold
of consecutive failures, then periodically testing if it has recovered.
"""

import logging
import threading
import time

from pydantic import BaseModel

from domain.ports.outbound.llm_port import LLMPort
from infrastructure.adapters.inbound.api.middleware import (
    LLMServiceException,
    LLMTimeoutException,
)

logger = logging.getLogger(__name__)


class CircuitBreakerAdapter(LLMPort):
    """Wraps an LLMPort with circuit breaker logic.

    States:
        CLOSED: Normal operation — calls pass through.
        OPEN: Failing — calls are rejected without contacting the provider.
        HALF_OPEN: Testing — one call is allowed to check if the provider
                   has recovered.

    Thread-safe: uses a lock around state transitions.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        inner: LLMPort,
        max_failures: int = 3,
        reset_timeout: float = 30.0,
    ):
        self._inner = inner
        self._max_failures = max_failures
        self._reset_timeout = reset_timeout

        self._lock = threading.Lock()
        self._failure_count = 0
        self._state = self.CLOSED
        self._last_failure_time = 0.0

    @property
    def state(self) -> str:
        """Current circuit breaker state (for testing/observability)."""
        return self._state

    @property
    def inner(self) -> LLMPort:
        """The wrapped adapter (for testing/observability)."""
        return self._inner

    def generate(self, prompt: str, response_model: type[BaseModel]) -> BaseModel:
        """Attempt to generate a response, respecting circuit breaker state.

        Args:
            prompt: The text prompt for the LLM.
            response_model: Pydantic model defining the expected response.

        Returns:
            A populated response_model instance.

        Raises:
            LLMServiceException: If the circuit is OPEN or the call fails.
        """
        with self._lock:
            if self._state == self.OPEN:
                if time.time() - self._last_failure_time >= self._reset_timeout:
                    self._state = self.HALF_OPEN
                    logger.info(
                        "Circuit breaker %s -> HALF_OPEN after timeout",
                        type(self._inner).__name__,
                    )
                else:
                    raise LLMServiceException(
                        f"circuit breaker OPEN for {type(self._inner).__name__}"
                        f" ({self._failure_count} failures, "
                        f"retry in {self._reset_timeout - (time.time() - self._last_failure_time):.0f}s)",
                    )

        try:
            result = self._inner.generate(prompt, response_model)

            with self._lock:
                self._failure_count = 0
                if self._state == self.HALF_OPEN:
                    logger.info(
                        "Circuit breaker %s -> CLOSED (recovered)",
                        type(self._inner).__name__,
                    )
                self._state = self.CLOSED

            return result

        except LLMTimeoutException:
            self._record_failure()
            raise

        except LLMServiceException:
            self._record_failure()
            raise

    def _record_failure(self) -> None:
        """Record a failure and transition to OPEN if threshold is reached."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._failure_count >= self._max_failures:
                self._state = self.OPEN
                logger.warning(
                    "Circuit breaker %s -> OPEN (%d failures)",
                    type(self._inner).__name__,
                    self._failure_count,
                )

    def __repr__(self) -> str:
        return (
            f"CircuitBreakerAdapter(inner={type(self._inner).__name__}, "
            f"state={self._state}, failures={self._failure_count})"
        )
