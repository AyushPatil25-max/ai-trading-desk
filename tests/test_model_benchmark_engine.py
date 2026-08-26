"""
Unit tests for Model Benchmark Engine & Multi-Dimensional Selection — Phase 5.6C

Validates multi-dimensional composite scoring, candidate ranking, and partition leakage isolation.
"""

from datetime import datetime
import unittest

from backend.domain.schemas import MarketContext
from backend.validation.model_benchmark_engine import (
    ModelBenchmarkEngine,
    ModelDatasetPartition,
    ModelSelectionDatasetConfig,
    MultiDimensionalScoreWeights,
)


class TestModelBenchmarkEngine(unittest.TestCase):
    def setUp(self):
        self.contexts = [
            MarketContext(
                context_id="ctx-bench-001",
                symbol="RELIANCE.NS",
                data_timestamp=datetime(2022, 6, 1, 10, 0, 0),
                current_price=2500.0,
                provider="NSE",
                ohlcv_historical=[{"timestamp": "2022-06-01", "close": 2500.0}],
                technical_indicators={"rsi_14": 56.0},
            )
        ]

    def test_evaluate_candidates_computes_ranks_and_scores(self):
        scorecards = ModelBenchmarkEngine.evaluate_candidates(self.contexts)
        self.assertEqual(len(scorecards), 4)
        # Verify scores are bounded between 0 and 100
        for sc in scorecards:
            self.assertGreaterEqual(sc.composite_score, 0.0)
            self.assertLessEqual(sc.composite_score, 100.0)
            self.assertGreaterEqual(sc.rank, 1)

    def test_partition_isolation_blocks_leakage(self):
        cfg = ModelSelectionDatasetConfig()
        # Context from 2022 belongs to selection dataset, NOT holdout
        dt_2022 = datetime(2022, 6, 1)
        dt_2023 = datetime(2023, 6, 1)

        self.assertTrue(cfg.validate_partition_isolation(dt_2022, ModelDatasetPartition.MODEL_SELECTION_DATASET))
        self.assertFalse(cfg.validate_partition_isolation(dt_2022, ModelDatasetPartition.HOLDOUT_OOS_DATASET))

        self.assertFalse(cfg.validate_partition_isolation(dt_2023, ModelDatasetPartition.MODEL_SELECTION_DATASET))
        self.assertTrue(cfg.validate_partition_isolation(dt_2023, ModelDatasetPartition.HOLDOUT_OOS_DATASET))


if __name__ == "__main__":
    unittest.main()
