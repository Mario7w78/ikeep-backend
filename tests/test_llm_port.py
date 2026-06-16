"""Tests for LLMPort abstract base class.

Verifies the port contract: generate() must be implemented by subclasses.
"""

from abc import ABC, abstractmethod
from typing import Any

import pytest
from pydantic import BaseModel


class TestLLMPortContract:
    """LLMPort is an ABC — tests focus on the contract, not instantiation."""

    def test_port_is_abstract(self):
        """LLMPort should be an ABC and cannot be instantiated directly."""
        import domain.ports.outbound.llm_port as lp

        assert issubclass(lp.LLMPort, ABC)
        assert "generate" in lp.LLMPort.__abstractmethods__

    def test_generate_signature_has_required_parameters(self):
        """generate() should accept prompt (str) and response_model (type[BaseModel])."""
        import domain.ports.outbound.llm_port as lp
        import inspect

        sig = inspect.signature(lp.LLMPort.generate)
        params = list(sig.parameters.keys())
        assert "prompt" in params
        assert "response_model" in params

    def test_concrete_subclass_must_implement_generate(self):
        """A subclass that doesn't implement generate() should still be abstract."""
        import domain.ports.outbound.llm_port as lp

        class IncompletePort(lp.LLMPort):
            pass

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompletePort()  # type: ignore[abstract]

    def test_concrete_subclass_can_be_instantiated(self):
        """A subclass that implements generate() should be instantiable."""
        import domain.ports.outbound.llm_port as lp

        class FakeModel(BaseModel):
            name: str = "test"

        class ConcretePort(lp.LLMPort):
            def generate(self, prompt: str, response_model: type[BaseModel]) -> BaseModel:
                return response_model()

        instance = ConcretePort()
        result = instance.generate("test", FakeModel)
        assert isinstance(result, FakeModel)
        assert result.name == "test"
