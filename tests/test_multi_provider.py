import unittest
import time
from datetime import datetime, timezone

from backend.domain.schemas import HistoricalWindow, DataQualityStatus, DataQualityTier
from backend.infrastructure.data_providers import MarketDataProvider
from backend.infrastructure.multi_provider import (
    MultiProviderMarketDataProvider, ProviderHealthScore,
    AlphaVantageProvider, FMPProvider, PolygonProvider, TwelveDataProvider
)

class MockFailingProvider(MarketDataProvider):
    def __init__(self, name, priority=1, delay=0):
        self._name = name
        self._priority = priority
        self._tier = DataQualityTier.TIER_4_STANDARD_AGGREGATOR
        self.delay = delay
        
    @property
    def name(self) -> str:
        return self._name
        
    def get_market_context(self, symbol: str, window=HistoricalWindow.RECENT):
        if self.delay > 0:
            time.sleep(self.delay)
        raise ValueError("Simulated failure")
        
    def get_historical_data(self, symbol, period="1y"):
        raise ValueError("Simulated failure")

class MockSuccessProvider(MarketDataProvider):
    def __init__(self, name, priority=1, delay=0):
        self._name = name
        self._priority = priority
        self._tier = DataQualityTier.TIER_5_UNVERIFIED_SECONDARY
        self.delay = delay
        
    @property
    def name(self) -> str:
        return self._name
        
    def get_market_context(self, symbol: str, window=HistoricalWindow.RECENT):
        from backend.domain.schemas import MarketContext
        if self.delay > 0:
            time.sleep(self.delay)
        return MarketContext(
            context_id="test",
            symbol=symbol,
            data_timestamp=datetime.now(timezone.utc),
            provider=self.name,
            current_price=150.0
        )
        
    def get_historical_data(self, symbol, period="1y"):
        import pandas as pd
        return pd.DataFrame([{"close": 150.0}])

class TestMultiProvider(unittest.TestCase):
    def test_provider_health_score(self):
        hs = ProviderHealthScore("test")
        self.assertEqual(hs.success_rate, 1.0)
        hs.record_failure()
        self.assertEqual(hs.success_rate, 0.0)
        hs.record_success(100.0)
        self.assertEqual(hs.success_rate, 0.5)
        self.assertEqual(hs.consecutive_failures, 0)
        self.assertEqual(hs.average_latency_ms, 100.0)
        
    def test_fallback_hierarchy(self):
        mp = MultiProviderMarketDataProvider(timeout_seconds=1.0)
        mp.providers = [] # clear default
        
        fail_1 = MockFailingProvider("Fail1", priority=1)
        fail_2 = MockFailingProvider("Fail2", priority=2)
        success_3 = MockSuccessProvider("Success3", priority=3)
        
        mp.register_provider(fail_1, DataQualityTier.TIER_4_STANDARD_AGGREGATOR, 1)
        mp.register_provider(fail_2, DataQualityTier.TIER_4_STANDARD_AGGREGATOR, 2)
        mp.register_provider(success_3, DataQualityTier.TIER_5_UNVERIFIED_SECONDARY, 3)
        
        ctx = mp.get_market_context("TEST")
        
        # It should have failed on 1 and 2, and succeeded on 3
        self.assertEqual(ctx.source_provider, "Success3")
        self.assertEqual(ctx.data_quality_tier, DataQualityTier.TIER_5_UNVERIFIED_SECONDARY)
        
        # Check health scores
        self.assertEqual(mp.health_scores["Fail1"].failure_count, 1)
        self.assertEqual(mp.health_scores["Fail2"].failure_count, 1)
        self.assertEqual(mp.health_scores["Success3"].success_count, 1)
        
    def test_timeout_protection(self):
        mp = MultiProviderMarketDataProvider(timeout_seconds=0.1)
        mp.providers = []
        
        slow_fail = MockFailingProvider("Slow", priority=1, delay=0.5)
        success = MockSuccessProvider("Fast", priority=2, delay=0)
        
        mp.register_provider(slow_fail, DataQualityTier.TIER_4_STANDARD_AGGREGATOR, 1)
        mp.register_provider(success, DataQualityTier.TIER_5_UNVERIFIED_SECONDARY, 2)
        
        ctx = mp.get_market_context("TEST")
        
        self.assertEqual(ctx.source_provider, "Fast")
        self.assertEqual(mp.health_scores["Slow"].failure_count, 1)
        
    def test_ranking_system(self):
        mp = MultiProviderMarketDataProvider()
        mp.providers = []
        
        p1 = MockSuccessProvider("P1", priority=1)
        p2 = MockSuccessProvider("P2", priority=2)
        
        mp.register_provider(p1, DataQualityTier.TIER_4_STANDARD_AGGREGATOR, 1)
        mp.register_provider(p2, DataQualityTier.TIER_4_STANDARD_AGGREGATOR, 2)
        
        # Simulate p1 failing many times
        for _ in range(4):
            mp.health_scores["P1"].record_failure()
            
        ranked = mp._rank_providers()
        # Because P1 has >= 3 consecutive failures, P2 should be ranked first now despite lower base priority
        self.assertEqual(ranked[0].name, "P2")

if __name__ == '__main__':
    unittest.main()
