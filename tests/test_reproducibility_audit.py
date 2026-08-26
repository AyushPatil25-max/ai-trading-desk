"""
Unit tests for Reproducibility Audit — Phase 5.5

Validates deterministic reproducibility hashing across identical configurations and datasets.
"""

from datetime import datetime
import hashlib
import unittest

from backend.scanner.historical_universe import HistoricalUniverse
from backend.simulation.simulation_config import SimulationConfig
from backend.validation.ablation_runner import RealAblationRunner


class TestReproducibilityAudit(unittest.IsolatedAsyncioTestCase):
    async def test_identical_executions_yield_identical_hashes(self):
        dataset = {
            "TCS.NS": {
                "current_price": 3000.0,
                "ohlcv_historical": [
                    {"timestamp": "2023-01-01 10:00:00", "close": 3000.0},
                    {"timestamp": "2023-06-01 10:00:00", "close": 3200.0},
                ],
                "technical_indicators": {"ema_20": 2900.0, "ema_50": 2800.0, "rsi_14": 58.0},
            }
        }
        runner1 = RealAblationRunner(
            simulation_config=SimulationConfig(initial_cash=100000.0),
            historical_universe=HistoricalUniverse(),
        )
        runner2 = RealAblationRunner(
            simulation_config=SimulationConfig(initial_cash=100000.0),
            historical_universe=HistoricalUniverse(),
        )

        res1 = await runner1.run_single_variant(
            variant_name="Variant F: Full Pipeline",
            description="",
            active_specialists=["TechnicalSpecialist"],
            debate_enabled=True,
            committee_enabled=True,
            safety_enabled=True,
            historical_datasets=dataset,
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 12, 31),
        )
        res2 = await runner2.run_single_variant(
            variant_name="Variant F: Full Pipeline",
            description="",
            active_specialists=["TechnicalSpecialist"],
            debate_enabled=True,
            committee_enabled=True,
            safety_enabled=True,
            historical_datasets=dataset,
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 12, 31),
        )

        hash1 = hashlib.sha256(f"{res1.total_return_pct}_{res1.trades}_{res1.turnover}".encode("utf-8")).hexdigest()
        hash2 = hashlib.sha256(f"{res2.total_return_pct}_{res2.trades}_{res2.turnover}".encode("utf-8")).hexdigest()

        self.assertEqual(hash1, hash2)
        self.assertEqual(res1.total_return_pct, res2.total_return_pct)


if __name__ == "__main__":
    unittest.main()
