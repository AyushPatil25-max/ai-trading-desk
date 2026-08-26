"""
Unit tests for Phase 5.6E Model Benchmark Forensic Verifier

Validates detection of placeholder scores, holdout isolation checks,
and verification status classification.
"""

from datetime import datetime
import unittest

from backend.domain.schemas import MarketContext
from backend.validation.model_benchmark_verifier import (
    BenchmarkForensicClassification,
    ModelBenchmarkVerifier,
)
from backend.validation.model_benchmark_engine import ModelSelectionDatasetConfig


class TestModelBenchmarkVerifier(unittest.TestCase):
    def setUp(self):
        self.contexts = [
            MarketContext(
                context_id="ctx-audit-001",
                symbol="RELIANCE.NS",
                data_timestamp=datetime(2021, 6, 1, 10, 0, 0),
                current_price=2200.0,
                provider="NSE",
                ohlcv_historical=[{"timestamp": "2021-06-01", "close": 2200.0}],
                technical_indicators={"rsi_14": 54.0},
            )
        ]

    def test_audit_detects_hardcoded_placeholder_locations(self):
        audit_res = ModelBenchmarkVerifier.audit_benchmark_execution(self.contexts)
        self.assertEqual(audit_res.classification, BenchmarkForensicClassification.INVALID_EMPIRICAL_BENCHMARK)
        self.assertEqual(audit_res.real_llm_execution, "NOT_VERIFIED")
        self.assertTrue(audit_res.hardcoded_scores_detected)
        self.assertGreater(len(audit_res.hardcoded_locations), 0)
        self.assertFalse(audit_res.holdout_access_detected)


if __name__ == "__main__":
    unittest.main()
