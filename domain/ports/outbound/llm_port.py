from abc import ABC, abstractmethod

from pydantic import BaseModel


class LLMPort(ABC):
    """Abstract port for LLM interaction.

    Implementations connect to specific LLM providers (Gemini, OpenAI, etc.)
    and return structured responses that conform to the provided Pydantic model.
    """

    @abstractmethod
    def generate(self, prompt: str, response_model: type[BaseModel]) -> BaseModel:
        """Send a prompt to the LLM and receive a structured response.

        Args:
            prompt: The text prompt to send to the LLM.
            response_model: A Pydantic BaseModel subclass defining the expected
                response structure. The LLM MUST return output that validates
                against this model.

        Returns:
            An instance of response_model populated with the LLM's output.

        Raises:
            LLMServiceException: If the LLM service returns an error.
            LLMTimeoutException: If the request times out.
        """
        pass
