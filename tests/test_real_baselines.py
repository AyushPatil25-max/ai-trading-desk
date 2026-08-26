"""
Unit tests for Real Strategy Baselines Runner — Phase 5.4C

Validates independent simulation of benchmark strategies (Buy & Hold, Equal-Weight, EMA, Momentum, Scanner).
"""

from datetime import datetime
import unittest

from backend.scanner.historical_universe import HistoricalUniverse
from backend.simulation.simulation_config import SimulationConfig
from backend.validation.baseline_runner import RealBaselineRunner


class TestRealBaselines(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.runner = RealBaselineRunner(
            simulation_config=SimulationConfig(initial_cash=100000.0),
            historical_universe=HistoricalUniverse(),
        )
        self.t0 = datetime(2023, 1, 1)
        self.t1 = datetime(2023, 12, 31)
        self.dataset = {
            "RELIANCE.NS": {
                "current_price": 2500.0,
                "ohlcv_historical": [
                    {"timestamp": "2023-01-01 10:00:00", "close": 2400.0},
                    {"timestamp": "2023-06-01 10:00:00", "close": 2500.0},
                    {"timestamp": "2023-12-01 10:00:00", "close": 2600.0},
                ],
                "technical_indicators": {"ema_20": 2450.0, "ema_50": 2400.0, "rsi_14": 56.0},
            }
        }

    async def test_run_all_baselines_executes_independent_strategies(self):
        results = await self.runner.run_all_baselines(
            historical_datasets=self.dataset,
            start_date=self.t0,
            end_date=self.t1,
        )
        self.assertEqual(len(results), 6)
        names = [r.strategy_name for r in results]

        self.assertTrue(any("Buy-and-Hold" in n for n in names))
        self.assertTrue(any("Equal-Weight" in n for n in names))
        self.assertTrue(any("Technical Baseline" in n for n in names))
        self.assertTrue(any("Momentum Baseline" in n for n in names))
        self.assertTrue(any("Scanner-Only" in n for n in names))
        self.assertTrue(any("Full AI" in n for n in names))


if __name__ == "__main__":
    unittest.main()
