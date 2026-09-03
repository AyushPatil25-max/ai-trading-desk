import asyncio
import hashlib
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

from backend.domain.schemas import MarketContext, DataQualityStatus, HistoricalWindow, SnapshotFreshness
from backend.infrastructure.data_providers import MarketDataProvider
from backend.infrastructure.cache import ContextCache

class ContextService:
    def __init__(self, provider: MarketDataProvider, cache: ContextCache):
        self.provider = provider
        self.cache = cache
        self._inflight = {}
        self._lock = asyncio.Lock()
        
    def _generate_cache_key(self, symbol: str, window: HistoricalWindow) -> str:
        """
        Deterministic cache key based on symbol, timeframe, and provider.
        """
        raw_key = f"{symbol}:{window.value}:{self.provider.name}"
        return hashlib.sha256(raw_key.encode('utf-8')).hexdigest()

    def _generate_deterministic_snapshot_id(self, context: MarketContext) -> str:
        """
        Calculates a deterministic SHA-256 snapshot identifier using canonical serialization.
        """
        core_data = {
            "symbol": context.symbol,
            "data_timestamp": context.data_timestamp.isoformat() if hasattr(context.data_timestamp, 'isoformat') else str(context.data_timestamp),
            "provider": context.provider,
            "current_price": context.current_price,
            "ohlcv_len": len(context.ohlcv_historical),
            "tech_len": len(context.technical_indicators),
            "fund_len": len(context.fundamental_data)
        }
        serialized = json.dumps(core_data, sort_keys=True)
        return f"snap-{hashlib.sha256(serialized.encode('utf-8')).hexdigest()[:16]}"
        
    def _determine_freshness(self, context: MarketContext) -> SnapshotFreshness:
        if context.quality_status == DataQualityStatus.CRITICAL_FAILURE:
            return SnapshotFreshness.INVALID
            
        now = datetime.now(timezone.utc)
        generated_at = context.generated_at
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)
            
        age = (now - generated_at).total_seconds()
        
        # 60s freshness rules
        if age > 60:
            return SnapshotFreshness.STALE
            
        return SnapshotFreshness.FRESH
        
    def _determine_completeness(self, context: MarketContext) -> str:
        if not context.ohlcv_historical or not context.current_price:
            return "PARTIAL"
        return "COMPLETE"
        
    async def get_market_context(self, symbol: str, window: HistoricalWindow = HistoricalWindow.RECENT) -> MarketContext:
        key = self._generate_cache_key(symbol, window)
        
        # 1. Check cache for exact match
        cached_context = await self.cache.get(key)
        if cached_context is not None:
            freshness = self._determine_freshness(cached_context)
            if freshness == SnapshotFreshness.FRESH:
                return cached_context.model_copy(update={
                    "is_cached": True, 
                    "cache_hit": True,
                    "freshness_status": freshness
                })

        # Check cache for larger windows
        windows_by_size = [
            HistoricalWindow.LONG,
            HistoricalWindow.MEDIUM,
            HistoricalWindow.SHORT,
            HistoricalWindow.RECENT
        ]
        target_days = HistoricalWindow.get_days(window)
        for w in windows_by_size:
            if HistoricalWindow.get_days(w) > target_days:
                larger_key = self._generate_cache_key(symbol, w)
                larger_context = await self.cache.get(larger_key)
                if larger_context is not None:
                    freshness = self._determine_freshness(larger_context)
                    if freshness == SnapshotFreshness.FRESH:
                        derived_ohlcv = larger_context.ohlcv_historical[-target_days:] if target_days > 0 else []
                        derived_context = larger_context.model_copy(update={
                            "is_cached": True,
                            "cache_hit": True,
                            "historical_window": window,
                            "ohlcv_historical": derived_ohlcv,
                            "freshness_status": freshness
                        })
                        await self.cache.set(key, derived_context)
                        return derived_context
            if w == window:
                break
            
        # 2. Concurrency single-flight protection
        is_leader = False
        async with self._lock:
            if key in self._inflight:
                future = self._inflight[key]
            else:
                future = asyncio.Future()
                self._inflight[key] = future
                is_leader = True
                
        if not is_leader:
            result = await future
            return result.model_copy(update={"is_cached": True, "cache_hit": True, "freshness_status": SnapshotFreshness.FRESH})

        # We are the leader, fetch data
        try:
            cached_context = await self.cache.get(key)
            if cached_context is not None and self._determine_freshness(cached_context) == SnapshotFreshness.FRESH:
                result = cached_context
            else:
                context = await asyncio.to_thread(self.provider.get_market_context, symbol, window)
                
                snapshot_id = self._generate_deterministic_snapshot_id(context)
                completeness = self._determine_completeness(context)
                
                context = context.model_copy(update={
                    "snapshot_id": snapshot_id,
                    "completeness_status": completeness,
                    "freshness_status": SnapshotFreshness.FRESH,
                    "cache_hit": False,
                    "generated_at": datetime.now(timezone.utc)
                })
                
                if context.quality_status != DataQualityStatus.CRITICAL_FAILURE:
                    await self.cache.set(key, context)
                result = context
                
            future.set_result(result)
            return result
        except Exception as e:
            if not future.done():
                future.set_exception(e)
            raise
        finally:
            async with self._lock:
                if key in self._inflight and self._inflight[key] is future:
                    del self._inflight[key]
