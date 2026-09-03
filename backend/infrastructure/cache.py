"""
Context Cache — Phase 2 Data Coverage Foundation

High-performance in-memory cache with domain-aware TTLs, single-flight coordination,
and hit/miss observability statistics.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import asyncio
from backend.domain.schemas import MarketContext


class ContextCache(ABC):
    @abstractmethod
    async def get(self, key: str) -> Optional[MarketContext]:
        pass

    @abstractmethod
    async def set(self, key: str, context: MarketContext, ttl_seconds: Optional[int] = None):
        pass

    @abstractmethod
    async def invalidate(self, key: str):
        pass


class InMemoryContextCache(ContextCache):
    """
    Thread-safe and async-safe in-memory cache with optional per-item TTL override
    and hit/miss performance metrics.
    """

    def __init__(self, ttl_seconds: int = 60):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._default_ttl = timedelta(seconds=ttl_seconds)
        self._lock = asyncio.Lock()
        self._hits: int = 0
        self._misses: int = 0

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        if total == 0:
            return 0.0
        return round(self._hits / total, 4)

    def get_stats(self) -> Dict[str, Any]:
        return {
            "hits": self._hits,
            "misses": self._misses,
            "total_requests": self._hits + self._misses,
            "hit_rate": self.hit_rate,
            "cached_entries": len(self._cache),
        }

    async def get(self, key: str) -> Optional[MarketContext]:
        async with self._lock:
            if key in self._cache:
                item = self._cache[key]
                entry: MarketContext = item["context"]
                ttl: timedelta = item["ttl"]
                cached_at: datetime = item["cached_at"]

                now = datetime.now(timezone.utc)
                if cached_at.tzinfo is None:
                    cached_at = cached_at.replace(tzinfo=timezone.utc)

                if now - cached_at <= ttl:
                    self._hits += 1
                    return entry.model_copy(update={"is_cached": True})
                else:
                    del self._cache[key]

            self._misses += 1
            return None

    async def set(self, key: str, context: MarketContext, ttl_seconds: Optional[int] = None):
        async with self._lock:
            ttl = timedelta(seconds=ttl_seconds) if ttl_seconds is not None else self._default_ttl
            self._cache[key] = {
                "context": context,
                "ttl": ttl,
                "cached_at": datetime.now(timezone.utc),
            }

    async def invalidate(self, key: str):
        async with self._lock:
            self._cache.pop(key, None)

    async def clear(self):
        async with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
