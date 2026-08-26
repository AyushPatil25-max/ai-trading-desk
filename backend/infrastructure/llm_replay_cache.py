"""
LLM Record and Replay Cache — Phase 5.6

Provides deterministic caching, recording, and bitwise replay of structured LLM responses
for historical backtesting and auditing.
"""

from datetime import datetime
import hashlib
import json
import os
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class CachedLLMResponse(BaseModel):
    request_hash: str
    model: str
    temperature: float
    system_prompt_hash: str
    user_prompt_hash: str
    response_schema: str
    context_id: str
    response_payload: Dict[str, Any]
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    recorded_at: datetime = Field(default_factory=datetime.utcnow)


class LLMReplayCache:
    """
    In-memory and file-backed deterministic replay cache for LLM structured queries.
    """

    _DEFAULT_INSTANCE: Optional["LLMReplayCache"] = None

    def __init__(self, cache_file_path: Optional[str] = None) -> None:
        self.cache_file_path = cache_file_path
        self._cache: Dict[str, CachedLLMResponse] = {}
        if cache_file_path and os.path.exists(cache_file_path):
            self.load_from_file(cache_file_path)

    @classmethod
    def get_default(cls) -> "LLMReplayCache":
        if cls._DEFAULT_INSTANCE is None:
            cls._DEFAULT_INSTANCE = cls()
        return cls._DEFAULT_INSTANCE

    @staticmethod
    def compute_key(
        system_prompt: str,
        user_prompt: str,
        schema_name: str,
        model: str,
        temperature: float,
        context_id: str,
    ) -> str:
        sys_hash = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()[:16]
        user_hash = hashlib.sha256(user_prompt.encode("utf-8")).hexdigest()[:16]
        payload = f"{model}_{temperature}_{schema_name}_{context_id}_{sys_hash}_{user_hash}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Optional[CachedLLMResponse]:
        return self._cache.get(key)

    def set(
        self,
        key: str,
        model: str,
        temperature: float,
        system_prompt: str,
        user_prompt: str,
        schema_name: str,
        context_id: str,
        response_payload: Dict[str, Any],
        input_tokens: int = 0,
        output_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
    ) -> CachedLLMResponse:
        sys_hash = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()[:16]
        user_hash = hashlib.sha256(user_prompt.encode("utf-8")).hexdigest()[:16]

        entry = CachedLLMResponse(
            request_hash=key,
            model=model,
            temperature=temperature,
            system_prompt_hash=sys_hash,
            user_prompt_hash=user_hash,
            response_schema=schema_name,
            context_id=context_id,
            response_payload=response_payload,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=estimated_cost_usd,
        )
        self._cache[key] = entry
        return entry

    def save_to_file(self, path: Optional[str] = None) -> None:
        target = path or self.cache_file_path
        if not target:
            return
        os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
        serializable = {k: v.model_dump(mode="json") for k, v in self._cache.items()}
        with open(target, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2)

    def load_from_file(self, path: str) -> None:
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            for k, v in data.items():
                self._cache[k] = CachedLLMResponse(**v)
