from backend.config.app_config import get_app_config
"""
LLM Client abstraction — Phase 3.2

Provides:
  - LLMClient: abstract async interface
  - GroqLLMClient: concrete Groq implementation with structured JSON parsing
  - MockLLMClient: deterministic test double for offline testing
"""

import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Optional, Type

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class LLMClientError(Exception):
    """Raised when the LLM call fails unrecoverably."""


class LLMParseError(LLMClientError):
    """Raised when the LLM response cannot be parsed into the required schema."""


class LLMClient(ABC):
    """
    Abstract interface for LLM providers.

    Specialists depend on this abstraction, never on a concrete provider.
    This boundary allows switching Groq → Gemini → Claude without touching
    specialist logic.
    """

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Human-readable model identifier preserved in AgentOutput."""

    @abstractmethod
    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: Type[BaseModel],
    ) -> BaseModel:
        """
        Call the LLM and parse the response into a Pydantic model.

        Parameters
        ----------
        system_prompt : str
            Role / context instruction for the model.
        user_prompt : str
            The actual data / question.
        response_model : Type[BaseModel]
            Pydantic model the LLM response must conform to.

        Returns
        -------
        A validated instance of response_model.

        Raises
        ------
        LLMParseError    — if the response cannot be validated.
        LLMClientError   — on provider-level errors.
        """

    async def generate_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: Any = None,
    ) -> Any:
        """Legacy compatibility shim — delegates to generate_structured if a model is given."""
        if response_model is not None:
            return await self.generate_structured(system_prompt, user_prompt, response_model)
        raise NotImplementedError("Unstructured completions are not supported in this version.")


class GroqLLMClient(LLMClient):
    """
    Groq implementation of LLMClient.

    Loads the API key from the environment at construction time.
    Uses JSON response format for reliable structured output.
    """

    DEFAULT_MODEL = "llama-3.3-70b-versatile"
    DEFAULT_TEMPERATURE = 0.1

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        import groq
        resolved_key = api_key or get_app_config().groq_api_key
        if not resolved_key:
            raise LLMClientError(
                "GROQ_API_KEY is not set. Provide it via environment variable or constructor."
            )
        self._client = groq.AsyncGroq(api_key=resolved_key)
        self._model = model or self.DEFAULT_MODEL

    @property
    def model_name(self) -> str:
        return self._model

    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: Type[BaseModel],
    ) -> BaseModel:
        """
        Call Groq and validate the JSON response against `response_model`.

        Raises LLMParseError if the model returns invalid JSON or a schema mismatch.
        Raises LLMClientError on provider-level errors.
        """
        schema_json = json.dumps(response_model.model_json_schema(), indent=2)
        augmented_user = (
            f"{user_prompt}\n\n"
            f"You MUST return ONLY valid JSON matching this exact schema:\n{schema_json}"
        )

        try:
            completion = await self._client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": augmented_user},
                ],
                model=self._model,
                response_format={"type": "json_object"},
                temperature=self.DEFAULT_TEMPERATURE,
            )
            raw_text = completion.choices[0].message.content
            logger.debug("[GroqLLMClient] raw response length=%d", len(raw_text or ""))
        except Exception as exc:
            raise LLMClientError(f"Groq API call failed: {exc}") from exc

        try:
            return response_model.model_validate_json(raw_text)
        except Exception as exc:
            raise LLMParseError(
                f"LLM response could not be parsed into {response_model.__name__}: {exc}\n"
                f"Raw text: {raw_text!r}"
            ) from exc


class MockLLMClient(LLMClient):
    """
    Deterministic test double for offline testing.

    Instantiate with a pre-built Pydantic instance; every call returns it.
    Optionally configure to raise an exception for error-path testing.
    """

    def __init__(
        self,
        fixed_response: Optional[BaseModel] = None,
        raise_error: Optional[Exception] = None,
        responses_queue: Optional[List[BaseModel]] = None,
    ) -> None:
        self._response = fixed_response
        self._error = raise_error
        self._queue = list(responses_queue) if responses_queue else []
        self._call_count = 0

    @property
    def model_name(self) -> str:
        return "mock-llm"

    @property
    def call_count(self) -> int:
        return self._call_count

    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: Type[BaseModel],
    ) -> BaseModel:
        self._call_count += 1
        if self._error is not None:
            raise self._error
        if self._queue:
            return self._queue.pop(0)
        if self._response is not None:
            return self._response
        raise NotImplementedError("MockLLMClient has no fixed_response configured.")

