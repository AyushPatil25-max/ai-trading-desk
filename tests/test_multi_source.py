import unittest
import asyncio
from datetime import datetime, timezone

from backend.infrastructure.providers.yfinance_provider import YFinanceProvider
from backend.infrastructure.providers.nse_provider import NSEProvider
from backend.infrastructure.providers.rbi_provider import RBIProvider
from backend.infrastructure.providers.orchestrator import MultiSourceOrchestrator
from backend.domain.schemas import HistoricalWindow

class TestMultiSourceOrchestrator(unittest.TestCase):
    def setUp(self):
        self.providers = [
            NSEProvider(),
            RBIProvider(),
            YFinanceProvider()
        ]
        self.orchestrator = MultiSourceOrchestrator(self.providers)

    def test_provider_capabilities(self):
        nse = NSEProvider()
        self.assertTrue(nse.capabilities.quotes)
        self.assertFalse(nse.capabilities.macro)
        
        rbi = RBIProvider()
        self.assertFalse(rbi.capabilities.quotes)
        self.assertTrue(rbi.capabilities.macro)

    def test_multi_source_quote_fallback(self):
        from unittest.mock import MagicMock
        from backend.domain.schemas import MarketContext
        
        mock_yf = YFinanceProvider()
        mock_ctx = MarketContext(context_id="test-yf", symbol="RELIANCE.NS", data_timestamp=datetime.now(timezone.utc), current_price=100.0, provider="yfinance", quality_summary={"yfinance": "ok"})
        mock_yf.get_market_context = MagicMock(return_value=mock_ctx)
        
        self.orchestrator = MultiSourceOrchestrator([NSEProvider(), RBIProvider(), mock_yf])
        ctx = self.orchestrator.get_market_context("RELIANCE.NS", HistoricalWindow.RECENT)
        self.assertIsNotNone(ctx)
        
        # It should fall back successfully and populate current_price
        self.assertGreaterEqual(ctx.current_price, 0.0)
        
        # The provider field should report MultiSource
        self.assertEqual(ctx.provider, "MultiSource")


if __name__ == '__main__':
    unittest.main()
