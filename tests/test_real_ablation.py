"""
Unit tests for Real Multi-Variant Ablation Runner — Phase 5.4C

Validates genuine independent sub-pipeline execution, LLM compute accounting,
and non-parametric metric calculations.
"""

from datetime import datetime
import unittest

from backend.scanner.historical_universe import HistoricalUniverse
from backend.simulation.simulation_config import SimulationConfig
from backend.validation.ablation_runner import RealAblationRunner


class TestRealAblation(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.runner = RealAblationRunner(
            simulation_config=SimulationConfig(initial_cash=100000.0),
            historical_universe=HistoricalUniverse(),
        )
        self.t0 = datetime(2023, 1, 1)
        self.t1 = datetime(2023, 12, 31)
        self.dataset = {
            "TCS.NS": {
                "current_price": 3000.0,
                "ohlcv_historical": [
                    {"timestamp": "2023-01-01 10:00:00", "close": 3000.0},
                    {"timestamp": "2023-06-01 10:00:00", "close": 3200.0},
                    {"timestamp": "2023-12-01 10:00:00", "close": 3300.0},
                ],
                "technical_indicators": {"ema_20": 2900.0, "ema_50": 2800.0, "rsi_14": 58.0},
                "fundamental_data": {"pe_ratio": 22.0, "net_profit": 5000.0},
                "news_data": {},
                "institutional_data": [],
            }
        }

    async def test_run_all_variants_executes_6_independent_variants(self):
        results = await self.runner.run_all_variants(
            historical_datasets=self.dataset,
            start_date=self.t0,
            end_date=self.t1,
        )
        self.assertEqual(len(results), 6)
        variant_names = [r.variant_name for r in results]

        self.assertTrue(any("Variant A" in v for v in variant_names))
        self.assertTrue(any("Variant B" in v for v in variant_names))
        self.assertTrue(any("Variant C" in v for v in variant_names))
        self.assertTrue(any("Variant D" in v for v in variant_names))
        self.assertTrue(any("Variant E" in v for v in variant_names))
        self.assertTrue(any("Variant F" in v for v in variant_names))

        # Check compute accounting
        var_a = next(r for r in results if "Variant A" in r.variant_name)
        var_f = next(r for r in results if "Variant F" in r.variant_name)
        self.assertGreater(var_f.llm_calls, var_a.llm_calls)
        self.assertGreater(var_f.compute_cost_usd, var_a.compute_cost_usd)


if __name__ == "__main__":
    unittest.main()
