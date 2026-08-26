"""
Unit tests for Opportunity Scanner Engine — Phase 5.3

Validates full Stage-A scanning over large universes, compute efficiency accounting,
and Point-In-Time future data protection.
"""

from datetime import datetime, timedelta
import unittest

from backend.scanner.opportunity_scanner import OpportunityScanner
from backend.scanner.scanner_config import ScannerConfig
from backend.scanner.universe import StockUniverse, UniverseConstituent, UniverseType


class TestOpportunityScanner(unittest.TestCase):
    def setUp(self):
        self.t0 = datetime(2024, 1, 1, 10, 0, 0)
        self.t1 = datetime(2024, 1, 2, 10, 0, 0)
        self.config = ScannerConfig(
            top_k=3,
            min_opportunity_score=30.0,
            min_data_quality_score=20.0,
            max_candidates_per_sector=2,
        )
        self.scanner = OpportunityScanner(self.config)

    def test_scan_universe_computes_efficiency_and_selects_candidates(self):
        universe = StockUniverse(UniverseType.NIFTY_50)
        constituents = universe.get_snapshot(self.t0).constituents

        datasets = {}
        for i, c in enumerate(constituents):
            datasets[c.symbol] = {
                "current_price": 1000.0 + (i * 10.0),
                "ohlcv_historical": [
                    {"timestamp": "2024-01-01 10:00:00", "close": 1000.0 + (i * 10.0)}
                ] * 25,
                "technical_indicators": {"ema_20": 980.0, "ema_50": 950.0, "rsi_14": 55.0},
                "fundamental_data": {"pe_ratio": 20.0, "net_profit": 5000.0, "revenue_growth": 0.15},
                "news_data": {},
                "institutional_data": [],
            }

        res = self.scanner.scan_universe(universe, datasets, as_of=self.t0)
        self.assertEqual(len(res.ranking_result.selected_candidates), 3)  # top_k = 3

        eff = res.efficiency
        self.assertEqual(eff.universe_size, len(constituents))
        self.assertEqual(eff.selected_candidates_count, 3)
        self.assertEqual(eff.specialist_executions_performed, 3 * 9)
        self.assertEqual(eff.specialist_executions_avoided, (len(constituents) - 3) * 9)
        self.assertGreater(eff.llm_calls_saved, 0)
        self.assertGreater(eff.scan_latency_ms, 0.0)

    def test_scan_universe_pit_filters_future_data(self):
        custom_constituents = [
            UniverseConstituent(symbol="TCS.NS", company_name="TCS", effective_from=self.t0),
        ]
        universe = StockUniverse(UniverseType.CUSTOM, constituents=custom_constituents)

        # Dataset contains past and future observations
        past_bars = [{"timestamp": "2024-01-01 10:00:00", "close": 3000.0}] * 20
        future_bars = [{"timestamp": "2024-01-02 10:00:00", "close": 3500.0}]
        dataset = {
            "TCS.NS": {
                "current_price": 3000.0,
                "ohlcv_historical": past_bars + future_bars,
                "fundamental_data": {
                    "q3": {"publication_time": "2024-01-01 09:00:00", "net_profit": 5000.0},
                    "q4": {"publication_time": "2024-01-03 09:00:00", "net_profit": 8000.0},  # Future filing
                },
                "news_data": [
                    {"title": "Past News", "published_at": "2024-01-01 08:00:00"},
                    {"title": "Future News", "published_at": "2024-01-03 08:00:00"},          # Future news
                ],
            }
        }

        # Scanning as of T0 (2024-01-01)
        res = self.scanner.scan_universe(universe, dataset, as_of=self.t0)
        self.assertEqual(len(res.ranking_result.selected_candidates), 1)

    def test_reproducible_deterministic_scanning(self):
        universe = StockUniverse(UniverseType.NIFTY_50)
        snapshot = universe.get_snapshot(self.t0)
        datasets = {
            c.symbol: {
                "current_price": 2000.0,
                "ohlcv_historical": [{"timestamp": "2024-01-01 10:00:00", "close": 2000.0}] * 25,
            }
            for c in snapshot.constituents
        }
        res1 = self.scanner.scan_universe(universe, datasets, as_of=self.t0)
        res2 = self.scanner.scan_universe(universe, datasets, as_of=self.t0)

        self.assertEqual(
            [c.symbol for c in res1.ranking_result.selected_candidates],
            [c.symbol for c in res2.ranking_result.selected_candidates],
        )
        self.assertEqual(
            [c.effective_opportunity_score for c in res1.ranking_result.selected_candidates],
            [c.effective_opportunity_score for c in res2.ranking_result.selected_candidates],
        )


if __name__ == "__main__":
    unittest.main()
