"""
Provider-Neutral LLM Adapter & Model Registry — Phase 5.6F

Provides real API driver implementations for Groq, Google Gemini, OpenAI,
Mock, and Replay LLM backends while preserving specialist client boundaries.
"""

from datetime import datetime
from enum import Enum
import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel, Field

from backend.infrastructure.llm import LLMClient, LLMClientError, LLMParseError, MockLLMClient
from backend.infrastructure.llm_replay_cache import LLMReplayCache

logger = logging.getLogger(__name__)


class LLMProviderType(str, Enum):
    GROQ = "GROQ"
    GEMINI = "GEMINI"
    OPENAI = "OPENAI"
    MOCK = "MOCK"
    REPLAY = "REPLAY"


class ModelCandidateDescriptor(BaseModel):
    slot_name: str
    provider: LLMProviderType
    model_id: str
    role: str
    context_window: int = 128000
    input_cost_per_m_usd: float = 0.59
    output_cost_per_m_usd: float = 0.79
    default_temperature: float = 0.1
    env_key: str = "GROQ_API_KEY"
    is_configured: bool = False


class LLMExecutionStats(BaseModel):
    model_name: str
    provider: LLMProviderType
    request_hash: str
    response_hash: str
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ProviderNeutralLLMClient(LLMClient):
    """
    Unified LLM Client that delegates to configured providers or replay cache
    while preserving deterministic schema validation and usage accounting.
    """

    MODEL_PRICING_RATES: Dict[str, tuple] = {
        "llama-3.3-70b-versatile": (0.59, 0.79),
        "llama-3.1-8b-instant": (0.05, 0.08),
        "gemini-2.5-flash": (0.15, 0.60),
        "gemini-3.7-flash": (0.15, 0.60),
        "gemini-2.5-pro": (1.25, 5.00),
        "gpt-4o-mini": (0.15, 0.60),
        "gpt-4o": (2.50, 10.00),
    }

    def __init__(
        self,
        provider: LLMProviderType = LLMProviderType.GROQ,
        model_name: str = "llama-3.3-70b-versatile",
        api_key: Optional[str] = None,
        temperature: float = 0.1,
        timeout_seconds: float = 30.0,
        replay_cache: Optional[LLMReplayCache] = None,
        fixed_mock_response: Optional[BaseModel] = None,
    ) -> None:
        self._provider = provider
        self._model = model_name
        self._api_key = api_key
        self._temperature = temperature
        self._timeout = timeout_seconds
        self._replay_cache = replay_cache
        self._fixed_mock = fixed_mock_response
        self._last_stats: Optional[LLMExecutionStats] = None
        self._call_count = 0

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider(self) -> LLMProviderType:
        return self._provider

    @property
    def last_stats(self) -> Optional[LLMExecutionStats]:
        return self._last_stats

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
        t0 = time.perf_counter()

        schema_json = json.dumps(response_model.model_json_schema(), indent=2)
        req_key = LLMReplayCache.compute_key(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_name=response_model.__name__,
            model=self._model,
            temperature=self._temperature,
            context_id="canonical",
        )

        # 1. REPLAY / CACHE CHECK
        if self._provider == LLMProviderType.REPLAY and self._replay_cache:
            cached = self._replay_cache.get(req_key)
            if cached:
                latency = (time.perf_counter() - t0) * 1000.0
                resp_hash = hashlib.sha256(json.dumps(cached.response_payload).encode("utf-8")).hexdigest()
                self._last_stats = LLMExecutionStats(
                    model_name=self._model,
                    provider=self._provider,
                    request_hash=req_key,
                    response_hash=resp_hash,
                    input_tokens=cached.input_tokens,
                    output_tokens=cached.output_tokens,
                    estimated_cost_usd=cached.estimated_cost_usd,
                    latency_ms=latency,
                )
                return response_model.model_validate(cached.response_payload)

        # 2. MOCK MODE
        if self._provider == LLMProviderType.MOCK or self._fixed_mock is not None:
            latency = (time.perf_counter() - t0) * 1000.0
            if self._fixed_mock:
                resp_dict = self._fixed_mock.model_dump()
            else:
                try:
                    resp_dict = response_model().model_dump()
                except Exception:
                    raise NotImplementedError(f"MockLLMClient requires fixed_response for {response_model.__name__}")

            resp_hash = hashlib.sha256(json.dumps(resp_dict).encode("utf-8")).hexdigest()
            self._last_stats = LLMExecutionStats(
                model_name=self._model,
                provider=self._provider,
                request_hash=req_key,
                response_hash=resp_hash,
                input_tokens=len(user_prompt) // 4,
                output_tokens=len(str(resp_dict)) // 4,
                estimated_cost_usd=0.0,
                latency_ms=latency,
            )
            return response_model.model_validate(resp_dict)

        # 3. LIVE PROVIDERS (GROQ / OPENAI / GEMINI)
        augmented_user = f"{user_prompt}\n\nYou MUST return ONLY valid JSON matching this exact schema:\n{schema_json}"

        if self._provider == LLMProviderType.GROQ:
            resolved_key = self._api_key or os.getenv("GROQ_API_KEY")
            if not resolved_key:
                raise LLMClientError(f"Provider GROQ is NOT_CONFIGURED: missing GROQ_API_KEY for model {self._model}")

            import groq
            client = groq.AsyncGroq(api_key=resolved_key, timeout=self._timeout)

            try:
                completion = await client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": augmented_user},
                    ],
                    model=self._model,
                    response_format={"type": "json_object"},
                    temperature=self._temperature,
                )
                raw_text = completion.choices[0].message.content or "{}"
                in_tok = getattr(completion.usage, "prompt_tokens", len(augmented_user) // 4)
                out_tok = getattr(completion.usage, "completion_tokens", len(raw_text) // 4)
            except Exception as exc:
                raise LLMClientError(f"Groq API call failed for model {self._model}: {exc}") from exc

        elif self._provider == LLMProviderType.OPENAI:
            resolved_key = self._api_key or os.getenv("OPENAI_API_KEY")
            if not resolved_key:
                raise LLMClientError(f"Provider OPENAI is NOT_CONFIGURED: missing OPENAI_API_KEY for model {self._model}")

            import openai
            client = openai.AsyncOpenAI(api_key=resolved_key, timeout=self._timeout)

            try:
                completion = await client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": augmented_user},
                    ],
                    model=self._model,
                    response_format={"type": "json_object"},
                    temperature=self._temperature,
                )
                raw_text = completion.choices[0].message.content or "{}"
                in_tok = getattr(completion.usage, "prompt_tokens", len(augmented_user) // 4)
                out_tok = getattr(completion.usage, "completion_tokens", len(raw_text) // 4)
            except Exception as exc:
                raise LLMClientError(f"OpenAI API call failed for model {self._model}: {exc}") from exc

        elif self._provider == LLMProviderType.GEMINI:
            resolved_key = self._api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if not resolved_key:
                raise LLMClientError(f"Provider GEMINI is NOT_CONFIGURED: missing GEMINI_API_KEY for model {self._model}")

            try:
                import httpx
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{self._model}:generateContent?key={resolved_key}"
                payload = {
                    "contents": [{"parts": [{"text": augmented_user}]}],
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                    "generationConfig": {"responseMimeType": "application/json", "temperature": self._temperature}
                }
                async with httpx.AsyncClient(timeout=self._timeout) as http_client:
                    resp = await http_client.post(url, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                    in_tok = data.get("usageMetadata", {}).get("promptTokenCount", len(augmented_user) // 4)
                    out_tok = data.get("usageMetadata", {}).get("candidatesTokenCount", len(raw_text) // 4)
            except Exception as exc:
                raise LLMClientError(f"Gemini API call failed for model {self._model}: {exc}") from exc

        else:
            raise LLMClientError(f"Unsupported or unconfigured provider type: {self._provider}")

        latency = (time.perf_counter() - t0) * 1000.0
        resp_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        
        in_rate, out_rate = self.MODEL_PRICING_RATES.get(self._model, (0.50, 1.00))
        cost_usd = (in_tok / 1_000_000.0) * in_rate + (out_tok / 1_000_000.0) * out_rate

        try:
            validated = response_model.model_validate_json(raw_text)
        except Exception as exc:
            raise LLMParseError(f"Failed to parse LLM response into {response_model.__name__}: {exc}\nRaw text: {raw_text!r}") from exc

        # Cache live response
        if self._replay_cache:
            self._replay_cache.set(
                key=req_key,
                model=self._model,
                temperature=self._temperature,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema_name=response_model.__name__,
                context_id="canonical",
                response_payload=validated.model_dump(),
                input_tokens=in_tok,
                output_tokens=out_tok,
                estimated_cost_usd=cost_usd,
            )

        self._last_stats = LLMExecutionStats(
            model_name=self._model,
            provider=self._provider,
            request_hash=req_key,
            response_hash=resp_hash,
            input_tokens=in_tok,
            output_tokens=out_tok,
            estimated_cost_usd=cost_usd,
            latency_ms=latency,
        )
        return validated


class LLMAdapterFactory:
    """
    Factory that resolves candidate slots from registry and constructs ProviderNeutralLLMClient.
    """

    CANDIDATES: Dict[str, ModelCandidateDescriptor] = {
        "groq_primary": ModelCandidateDescriptor(
            slot_name="groq_primary",
            provider=LLMProviderType.GROQ,
            model_id="llama-3.3-70b-versatile",
            role="Current Production Baseline",
            context_window=128000,
            input_cost_per_m_usd=0.59,
            output_cost_per_m_usd=0.79,
            env_key="GROQ_API_KEY",
            is_configured=bool(os.getenv("GROQ_API_KEY")),
        ),
        "gemini_flash": ModelCandidateDescriptor(
            slot_name="gemini_flash",
            provider=LLMProviderType.GEMINI,
            model_id="gemini-3.7-flash",
            role="High-Throughput Fast Reasoning",
            context_window=1000000,
            input_cost_per_m_usd=0.15,
            output_cost_per_m_usd=0.60,
            env_key="GEMINI_API_KEY",
            is_configured=bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
        ),
        "openai_lightweight": ModelCandidateDescriptor(
            slot_name="openai_lightweight",
            provider=LLMProviderType.OPENAI,
            model_id="gpt-4o-mini",
            role="Lightweight Proprietary Reasoning",
            context_window=128000,
            input_cost_per_m_usd=0.15,
            output_cost_per_m_usd=0.60,
            env_key="OPENAI_API_KEY",
            is_configured=bool(os.getenv("OPENAI_API_KEY")),
        ),
        "openai_reasoning": ModelCandidateDescriptor(
            slot_name="openai_reasoning",
            provider=LLMProviderType.OPENAI,
            model_id="gpt-4o",
            role="Strong Multi-Modal Reasoning",
            context_window=128000,
            input_cost_per_m_usd=2.50,
            output_cost_per_m_usd=10.00,
            env_key="OPENAI_API_KEY",
            is_configured=bool(os.getenv("OPENAI_API_KEY")),
        ),
    }

    @classmethod
    def get_candidate(cls, slot_name: str) -> ModelCandidateDescriptor:
        if slot_name not in cls.CANDIDATES:
            raise KeyError(f"Candidate slot '{slot_name}' not registered in LLM candidate registry.")
        desc = cls.CANDIDATES[slot_name]
        desc.is_configured = bool(os.getenv(desc.env_key))
        return desc

    @classmethod
    def list_candidate_slots(cls) -> List[ModelCandidateDescriptor]:
        return [cls.get_candidate(k) for k in cls.CANDIDATES]

    @classmethod
    def create_client(
        cls,
        slot_or_model: str,
        temperature: float = 0.1,
        replay_cache: Optional[LLMReplayCache] = None,
        force_mock: Optional[BaseModel] = None,
    ) -> ProviderNeutralLLMClient:
        # Check if slot name
        if slot_or_model in cls.CANDIDATES:
            cand = cls.get_candidate(slot_or_model)
            provider = cand.provider
            model_id = cand.model_id
        elif slot_or_model.startswith("mock"):
            provider = LLMProviderType.MOCK
            model_id = "mock-llm"
        elif slot_or_model.startswith("replay"):
            provider = LLMProviderType.REPLAY
            model_id = "replay-llm"
        elif "gemini" in slot_or_model.lower():
            provider = LLMProviderType.GEMINI
            model_id = slot_or_model
        elif "gpt" in slot_or_model.lower():
            provider = LLMProviderType.OPENAI
            model_id = slot_or_model
        else:
            provider = LLMProviderType.GROQ
            model_id = slot_or_model

        return ProviderNeutralLLMClient(
            provider=provider,
            model_name=model_id,
            temperature=temperature,
            replay_cache=replay_cache,
            fixed_mock_response=force_mock,
        )
