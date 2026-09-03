import unittest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta, timezone
import uuid

from backend.domain.schemas import MarketContext, DataQualityStatus, HistoricalWindow
from backend.infrastructure.data_providers import MarketDataProvider
from backend.infrastructure.cache import InMemoryContextCache
from backend.application.context_service import ContextService
from pydantic import ValidationError

class MockProvider(MarketDataProvider):
    @property
    def name(self) -> str:
        return "mock"
        
    def get_historical_data(self, symbol: str, period: str = "1y"):
        pass

    def get_market_context(self, symbol: str, window: HistoricalWindow = HistoricalWindow.RECENT) -> MarketContext:
        # mock generating OHLCV length
        ohlcv = [{"close": 100.0} for _ in range(HistoricalWindow.get_days(window))]
        return MarketContext(
            context_id=str(uuid.uuid4()),
            symbol=symbol,
            provider="mock",
            historical_window=window,
            generated_at=datetime.now(timezone.utc),
            data_timestamp=datetime.now(timezone.utc),
            current_price=100.0,
            ohlcv_historical=ohlcv,
            quality_status=DataQualityStatus.OK
        )

class TestContextService(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.provider = MockProvider()
        self.provider.get_market_context = MagicMock(side_effect=self.provider.get_market_context)
        self.cache = InMemoryContextCache(ttl_seconds=1) # 1 sec TTL for testing
        self.service = ContextService(self.provider, self.cache)

    async def test_1_cache_miss_and_2_hit(self):
        # 1. Miss
        ctx1 = await self.service.get_market_context("TEST")
        self.provider.get_market_context.assert_called_once_with("TEST", HistoricalWindow.RECENT)
        self.assertFalse(ctx1.is_cached)
        
        # 2. Hit
        self.provider.get_market_context.reset_mock()
        ctx2 = await self.service.get_market_context("TEST")
        self.provider.get_market_context.assert_not_called()
        self.assertTrue(ctx2.is_cached)
        self.assertEqual(ctx1.context_id, ctx2.context_id)

    async def test_3_cache_invalidation(self):
        await self.service.get_market_context("TEST")
        self.provider.get_market_context.reset_mock()
        
        key = self.service._generate_cache_key("TEST", HistoricalWindow.RECENT)
        await self.cache.invalidate(key)
        
        ctx2 = await self.service.get_market_context("TEST")
        self.provider.get_market_context.assert_called_once_with("TEST", HistoricalWindow.RECENT)
        self.assertFalse(ctx2.is_cached)

    async def test_4_ttl_freshness_and_9_stale_rejection(self):
        ctx1 = await self.service.get_market_context("TEST")
        self.provider.get_market_context.reset_mock()
        
        # wait for ttl to expire
        await asyncio.sleep(1.1)
        
        # 9. Stale context rejection: should fetch new data
        ctx2 = await self.service.get_market_context("TEST")
        self.provider.get_market_context.assert_called_once()
        self.assertNotEqual(ctx1.context_id, ctx2.context_id)
        self.assertFalse(ctx2.is_cached)

    async def test_5_deterministic_cache_key(self):
        key1 = self.service._generate_cache_key("TEST", HistoricalWindow.MEDIUM)
        key2 = self.service._generate_cache_key("TEST", HistoricalWindow.MEDIUM)
        self.assertEqual(key1, key2)
        key3 = self.service._generate_cache_key("TEST", HistoricalWindow.RECENT)
        self.assertNotEqual(key1, key3)

    async def test_6_context_id_generation(self):
        ctx1 = await self.service.get_market_context("TEST1")
        ctx2 = await self.service.get_market_context("TEST2")
        self.assertTrue(ctx1.context_id)
        self.assertTrue(ctx2.context_id)
        self.assertNotEqual(ctx1.context_id, ctx2.context_id)

    async def test_7_same_context_returned_to_multiple_consumers(self):
        ctx1 = await self.service.get_market_context("TEST")
        ctx2 = await self.service.get_market_context("TEST")
        self.assertEqual(ctx1.model_dump(exclude={'is_cached', 'snapshot_id', 'freshness_status', 'completeness_status', 'cache_hit'}), ctx2.model_dump(exclude={'is_cached', 'snapshot_id', 'freshness_status', 'completeness_status', 'cache_hit'}))

    async def test_8_context_immutability(self):
        ctx = await self.service.get_market_context("TEST")
        with self.assertRaises(ValidationError):
            ctx.current_price = 200.0

    async def test_10_provider_failure(self):
        self.provider.get_market_context.side_effect = Exception("API Down")
        with self.assertRaises(Exception):
            await self.service.get_market_context("FAIL")

    async def test_12_concurrent_identical_requests(self):
        async def slow_provider(func, symbol: str, window) -> MarketContext:
            await asyncio.sleep(0.2)
            return MarketContext(
                context_id=str(uuid.uuid4()),
                symbol=symbol,
                provider="mock",
                historical_window=window,
                generated_at=datetime.now(timezone.utc),
                data_timestamp=datetime.now(timezone.utc),
                current_price=100.0,
                quality_status=DataQualityStatus.OK
            )
        
        with patch('asyncio.to_thread', new_callable=AsyncMock) as mock_thread:
            mock_thread.side_effect = slow_provider
            
            # Fire 5 concurrent requests
            results = await asyncio.gather(
                self.service.get_market_context("TEST"),
                self.service.get_market_context("TEST"),
                self.service.get_market_context("TEST"),
                self.service.get_market_context("TEST"),
                self.service.get_market_context("TEST")
            )
            
            # Provider should only be called ONCE
            mock_thread.assert_called_once()
            
            # All results should have the SAME context_id
            first_id = results[0].context_id
            for res in results:
                self.assertEqual(res.context_id, first_id)

    async def test_13_derive_smaller_window_from_larger_cache(self):
        # Fetch LONG first
        ctx_long = await self.service.get_market_context("TEST", HistoricalWindow.LONG)
        self.assertEqual(len(ctx_long.ohlcv_historical), 252)
        self.provider.get_market_context.reset_mock()
        
        # Now fetch SHORT (20D). It should NOT call provider, but return a sliced version
        ctx_short = await self.service.get_market_context("TEST", HistoricalWindow.SHORT)
        self.provider.get_market_context.assert_not_called()
        self.assertTrue(ctx_short.is_cached)
        self.assertEqual(ctx_short.historical_window, HistoricalWindow.SHORT)
        self.assertEqual(len(ctx_short.ohlcv_historical), 20)
        self.assertEqual(ctx_short.context_id, ctx_long.context_id) # Same snapshot ID
