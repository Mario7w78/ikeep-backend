"""Failover adapter that tries multiple LLM providers in order.

Iterates through a list of LLMPort implementations until one succeeds,
providing resilience against individual provider outages.
"""

import logging

from pydantic import BaseModel

from domain.ports.outbound.llm_port import LLMPort
from infrastructure.adapters.inbound.api.middleware import (
    LLMGatewayException,
    LLMServiceException,
    LLMTimeoutException,
)

logger = logging.getLogger(__name__)


class FailoverAdapter(LLMPort):
    """Tries multiple LLM providers sequentially until one succeeds.

    Each provider is attempted in order. If a provider raises
    LLMServiceException or LLMTimeoutException, the next provider
    is tried. The first successful response is returned immediately.

    If every provider fails, an LLMGatewayException is raised with
    details of all failures.
    """

    def __init__(self, providers: list[LLMPort]):
        if not providers:
            raise ValueError("At least one provider is required")

        self._providers = providers

    def generate(self, prompt: str, response_model: type[BaseModel]) -> BaseModel:
        """Attempt generation across all providers in order.

        Args:
            prompt: The text prompt for the LLM.
            response_model: Pydantic model defining the expected response.

        Returns:
            A populated response_model instance from the first successful provider.

        Raises:
            LLMGatewayException: If all providers fail.
        """
        errors: list[dict[str, str]] = []

        for provider in self._providers:
            try:
                result = provider.generate(prompt, response_model)
                logger.info(
                    "LLM ok: %s", type(provider).__name__,
                )
                return result

            except (LLMServiceException, LLMTimeoutException) as exc:
                provider_name = type(provider).__name__
                logger.warning(
                    "LLM failover: %s - %s", provider_name, exc,
                )
                errors.append({"provider": provider_name, "error": str(exc)})
                continue

        raise LLMGatewayException(
            f"All {len(self._providers)} providers failed",
            detail={"errors": errors},
        )

    def __repr__(self) -> str:
        providers = [type(p).__name__ for p in self._providers]
        return f"FailoverAdapter(providers={providers})"
