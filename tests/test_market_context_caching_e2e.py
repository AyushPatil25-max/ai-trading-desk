import asyncio
import unittest
import uuid
from datetime import datetime, timezone
from backend.domain.schemas import MarketContext, HistoricalWindow, DataQualityStatus, SnapshotFreshness
from backend.infrastructure.data_providers import MarketDataProvider
from backend.infrastructure.cache import InMemoryContextCache
from backend.application.context_service import ContextService
from backend.application.trading_os_orchestrator import TradingOSOrchestrator

class MockProvider(MarketDataProvider):
    @property
    def name(self) -> str:
        return "mock"
        
    def get_historical_data(self, symbol: str, period: str = "1y"):
        pass

    def get_market_context(self, symbol: str, window: HistoricalWindow = HistoricalWindow.RECENT) -> MarketContext:
        ohlcv = [{"close": 100.0} for _ in range(HistoricalWindow.get_days(window))]
        return MarketContext(
            context_id=str(uuid.uuid4()),
            symbol=symbol,
            provider="mock",
            historical_window=window,
            data_timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            current_price=100.0,
            ohlcv_historical=ohlcv
        )

class TestPhase20MarketContextCaching(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.provider = MockProvider()
        self.cache = InMemoryContextCache(ttl_seconds=2)
        self.service = ContextService(provider=self.provider, cache=self.cache)

    async def test_01_cache_hit_miss_and_freshness(self):
        ctx1 = await self.service.get_market_context("TCS.NS")
        self.assertFalse(ctx1.cache_hit)
        self.assertEqual(ctx1.freshness_status, SnapshotFreshness.FRESH)
        self.assertIsNotNone(ctx1.snapshot_id)

        ctx2 = await self.service.get_market_context("TCS.NS")
        self.assertTrue(ctx2.cache_hit)
        self.assertEqual(ctx2.freshness_status, SnapshotFreshness.FRESH)
        self.assertEqual(ctx1.snapshot_id, ctx2.snapshot_id)
        
        stats = self.cache.get_stats()
        self.assertEqual(stats["hits"], 1)

    async def test_02_deterministic_snapshot_id(self):
        ctx1 = self.provider.get_market_context("INFY.NS")
        ctx2 = self.provider.get_market_context("INFY.NS")
        
        id1 = self.service._generate_deterministic_snapshot_id(ctx1)
        id2 = self.service._generate_deterministic_snapshot_id(ctx2)
        self.assertEqual(id1, id2, "Equivalent contexts must produce identical IDs")
        
        ctx3 = self.provider.get_market_context("RELIANCE.NS")
        id3 = self.service._generate_deterministic_snapshot_id(ctx3)
        self.assertNotEqual(id1, id3, "Different contexts must produce different IDs")

    async def test_03_duplicate_fetch_coalescing(self):
        results = await asyncio.gather(
            self.service.get_market_context("HDFCBANK.NS"),
            self.service.get_market_context("HDFCBANK.NS"),
            self.service.get_market_context("HDFCBANK.NS")
        )
        hits = [r.cache_hit for r in results]
        self.assertEqual(hits.count(False), 1, "Only one fetch should happen")
        self.assertEqual(hits.count(True), 2, "Followers should get cache hit")
        self.assertEqual(results[0].snapshot_id, results[1].snapshot_id)

    async def test_04_ttl_expiry_and_stale_detection(self):
        ctx1 = await self.service.get_market_context("WIPRO.NS")
        self.assertFalse(ctx1.cache_hit)
        
        await asyncio.sleep(2.1)
        
        ctx2 = await self.service.get_market_context("WIPRO.NS")
        self.assertFalse(ctx2.cache_hit, "Cache should evict stale data and fetch fresh")
        self.assertEqual(ctx2.freshness_status, SnapshotFreshness.FRESH)

    async def test_05_orchestrator_snapshot_consistency(self):
        ctx = await self.service.get_market_context("TCS.NS")
        orchestrator = TradingOSOrchestrator()
        run = orchestrator.run_pipeline(market_context=ctx)
        
        self.assertIsNotNone(run.market_context)
        self.assertIn("snapshot_id", run.market_context)
        self.assertIn("freshness_status", run.market_context)

if __name__ == "__main__":
    unittest.main()
