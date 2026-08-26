from abc import ABC, abstractmethod
from typing import Optional
from datetime import datetime, timedelta
import asyncio
from backend.domain.schemas import MarketContext

class ContextCache(ABC):
    @abstractmethod
    async def get(self, key: str) -> Optional[MarketContext]:
        pass
        
    @abstractmethod
    async def set(self, key: str, context: MarketContext):
        pass
        
    @abstractmethod
    async def invalidate(self, key: str):
        pass

class InMemoryContextCache(ContextCache):
    def __init__(self, ttl_seconds: int = 60):
        self._cache = {}
        self._ttl = timedelta(seconds=ttl_seconds)
        self._lock = asyncio.Lock()
        
    async def get(self, key: str) -> Optional[MarketContext]:
        async with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                if datetime.utcnow() - entry.generated_at <= self._ttl:
                    # Mark as cached
                    return entry.model_copy(update={'is_cached': True})
                else:
                    del self._cache[key]
        return None
        
    async def set(self, key: str, context: MarketContext):
        async with self._lock:
            self._cache[key] = context
            
    async def invalidate(self, key: str):
        async with self._lock:
            self._cache.pop(key, None)
