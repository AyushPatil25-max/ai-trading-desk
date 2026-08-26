"""
Unit tests for Real LLM Validation Protocol & Stratified Sampling — Phase 5.6B

Validates stratified context selection, model quality metric calculations, and paired model comparisons.
"""

from datetime import datetime
import unittest

from backend.domain.schemas import MarketContext
from backend.validation.real_llm_protocol import (
    ModelQualityMetrics,
    PairedModelExperimentConfig,
    RealLLMValidationProtocol,
    StratifiedContextSelector,
    StratifiedSamplingConfig,
)


class TestRealLLMProtocol(unittest.TestCase):
    def setUp(self):
        self.contexts = [
            MarketContext(
                context_id=f"ctx-strat-{i}",
                symbol=sym,
                data_timestamp=datetime(2021, 1 + i, 15, 10, 0, 0),
                current_price=1000.0 * (i + 1),
                provider="NSE",
                ohlcv_historical=[{"timestamp": "2021-01-01", "close": 1000.0}],
                technical_indicators={"rsi_14": 50.0 + i},
            )
            for i, sym in enumerate(["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "TATAMOTORS.NS", "LT.NS"])
        ]

    def test_stratified_context_selector_deterministic_selection(self):
        cfg = StratifiedSamplingConfig(total_contexts=3)
        selected = StratifiedContextSelector.select_stratified_contexts(self.contexts, cfg)
        self.assertEqual(len(selected), 3)

        # Selection is deterministic across repeated calls
        selected2 = StratifiedContextSelector.select_stratified_contexts(self.contexts, cfg)
        self.assertEqual([c.context_id for c in selected], [c.context_id for c in selected2])

    def test_evaluate_model_quality_returns_valid_metrics(self):
        metrics = RealLLMValidationProtocol.evaluate_model_quality("llama-3.3-70b-versatile", self.contexts)
        self.assertEqual(metrics.model_name, "llama-3.3-70b-versatile")
        self.assertEqual(metrics.contexts_evaluated, 5)
        self.assertGreater(metrics.specialist_agreement_pct, 80.0)
        self.assertEqual(metrics.numerical_boundary_violations, 0)
        self.assertEqual(metrics.pit_leakage_violations, 0)

    def test_compare_paired_models_evaluates_all_candidates(self):
        config = PairedModelExperimentConfig(
            candidate_models=["llama-3.3-70b-versatile", "gemini-2.5-flash", "gemini-2.5-pro"]
        )
        res = RealLLMValidationProtocol.compare_paired_models(config, self.contexts)
        self.assertEqual(len(res), 3)
        self.assertIn("gemini-2.5-pro", res)


if __name__ == "__main__":
    unittest.main()
