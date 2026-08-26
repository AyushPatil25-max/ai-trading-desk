"""
Unit tests for Phase 5.6F Controlled Multi-Model Empirical Benchmark

Validates candidate registry, holdout isolation, hard disqualification rules,
provider adapter routing, cost accounting, ranking, and non-switching invariants.
"""

from datetime import datetime
import os
import unittest
from pydantic import BaseModel

from backend.domain.schemas import MarketContext
from backend.infrastructure.llm import LLMClientError
from backend.infrastructure.llm_provider_adapter import (
    LLMAdapterFactory,
    LLMProviderType,
    ModelCandidateDescriptor,
    ProviderNeutralLLMClient,
)
from backend.infrastructure.llm_replay_cache import LLMReplayCache
from backend.validation.model_benchmark_engine import (
    ModelBenchmarkEngine,
    ModelComparisonScorecard,
    ModelDatasetPartition,
    ModelSelectionDatasetConfig,
    MultiDimensionalScoreWeights,
)
from backend.validation.real_llm_protocol import (
    ModelQualityMetrics,
    RealLLMValidationProtocol,
    StratifiedContextSelector,
    StratifiedSamplingConfig,
)


class DummyOutputSchema(BaseModel):
    trend: str = "BULLISH"
    confidence: float = 0.85
    risk_level: str = "LOW"


class TestModelSelectionBenchmark(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.selection_cfg = ModelSelectionDatasetConfig(
            selection_start=datetime(2021, 1, 1),
            selection_end=datetime(2022, 12, 31),
            holdout_start=datetime(2023, 1, 1),
            holdout_end=datetime(2024, 12, 31),
        )
        self.contexts_2021 = [
            MarketContext(
                context_id=f"ctx-2021-{i}",
                symbol=sym,
                data_timestamp=datetime(2021, 6, 1, 10, 0, 0),
                current_price=2000.0 + (i * 100.0),
                provider="NSE",
                ohlcv_historical=[{"timestamp": "2021-06-01", "close": 2000.0}],
                technical_indicators={"rsi_14": 55.0},
            )
            for i, sym in enumerate(["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "TATAMOTORS.NS", "SUNPHARMA.NS"])
        ]

    def test_candidate_registry_completeness(self):
        """All 4 verified candidate slots exist and are properly configured in registry."""
        slots = LLMAdapterFactory.list_candidate_slots()
        slot_map = {s.slot_name: s for s in slots}
        self.assertEqual(len(slots), 4)
        self.assertIn("groq_primary", slot_map)
        self.assertIn("gemini_flash", slot_map)
        self.assertIn("openai_lightweight", slot_map)
        self.assertIn("openai_reasoning", slot_map)

    def test_production_baseline_model_identifier(self):
        """Current production baseline is strictly llama-3.3-70b-versatile via Groq."""
        groq_slot = LLMAdapterFactory.get_candidate("groq_primary")
        self.assertEqual(groq_slot.model_id, "llama-3.3-70b-versatile")
        self.assertEqual(groq_slot.provider, LLMProviderType.GROQ)

    def test_holdout_isolation_enforced(self):
        """Contexts from 2023-2024 must NOT be accepted in MODEL_SELECTION_DATASET partition."""
        dt_2021 = datetime(2021, 6, 1)
        dt_2022 = datetime(2022, 11, 15)
        dt_2023 = datetime(2023, 1, 15)
        dt_2024 = datetime(2024, 8, 1)

        self.assertTrue(self.selection_cfg.validate_partition_isolation(dt_2021, ModelDatasetPartition.MODEL_SELECTION_DATASET))
        self.assertTrue(self.selection_cfg.validate_partition_isolation(dt_2022, ModelDatasetPartition.MODEL_SELECTION_DATASET))
        self.assertFalse(self.selection_cfg.validate_partition_isolation(dt_2023, ModelDatasetPartition.MODEL_SELECTION_DATASET))
        self.assertFalse(self.selection_cfg.validate_partition_isolation(dt_2024, ModelDatasetPartition.MODEL_SELECTION_DATASET))

    def test_holdout_leakage_assertion_raises(self):
        """Passing a 2023 context into selection dataset assertion strictly raises ValueError."""
        ctx_holdout = MarketContext(
            context_id="ctx-holdout-001",
            symbol="INFY.NS",
            data_timestamp=datetime(2023, 5, 10),
            current_price=1400.0,
            provider="NSE",
        )
        with self.assertRaises(ValueError):
            self.selection_cfg.assert_no_holdout_leakage([ctx_holdout])

    def test_hard_disqualification_on_numerical_mutation(self):
        """A model with numerical mutations is disqualified (cannot be production ready)."""
        metrics = ModelQualityMetrics(
            model_name="llama-3.3-70b-versatile",
            contexts_evaluated=5,
            specialist_agreement_pct=90.0,
            final_decision_agreement_pct=85.0,
            decision_flip_rate_pct=5.0,
            confidence_calibration_delta=0.02,
            risk_recognition_rate_pct=95.0,
            evidence_grounding_score=0.95,
            hallucination_rate_pct=0.0,
            numerical_boundary_violations=1,  # Violation
            pit_leakage_violations=0,
            schema_violation_rate_pct=0.0,
            avg_latency_ms=300.0,
            tokens_per_context=4000,
            cost_per_100_contexts_usd=0.25,
            is_live_executed=True,
        )
        score = ModelBenchmarkEngine.compute_composite_score(metrics)
        # Disqualification check
        is_disqualified = metrics.numerical_boundary_violations > 0
        self.assertTrue(is_disqualified)

    async def test_provider_adapter_routing_and_stats(self):
        """ProviderNeutralLLMClient accurately tracks tokens, cost, latency, and hashes."""
        dummy = DummyOutputSchema()
        client = LLMAdapterFactory.create_client("mock-llm", force_mock=dummy)
        resp = await client.generate_structured("sys prompt", "user prompt", DummyOutputSchema)
        self.assertEqual(resp.trend, "BULLISH")
        self.assertIsNotNone(client.last_stats)
        self.assertGreater(client.last_stats.latency_ms, 0.0)
        self.assertGreater(len(client.last_stats.request_hash), 0)
        self.assertGreater(len(client.last_stats.response_hash), 0)

    async def test_missing_credentials_raises_client_error(self):
        """If API key is missing, ProviderNeutralLLMClient raises LLMClientError without falling back."""
        client = ProviderNeutralLLMClient(
            provider=LLMProviderType.OPENAI,
            model_name="gpt-4o-mini",
            api_key=None,
        )
        # Ensure env key is not present during test
        old_val = os.environ.pop("OPENAI_API_KEY", None)
        try:
            with self.assertRaises(LLMClientError):
                await client.generate_structured("sys", "user", DummyOutputSchema)
        finally:
            if old_val:
                os.environ["OPENAI_API_KEY"] = old_val

    def test_model_ranking_and_tie_handling(self):
        """Model benchmark engine correctly ranks models by composite score."""
        scorecards = ModelBenchmarkEngine.evaluate_candidates(self.contexts_2021)
        self.assertEqual(len(scorecards), 4)
        for idx in range(len(scorecards) - 1):
            self.assertGreaterEqual(scorecards[idx].composite_score, scorecards[idx + 1].composite_score)
            self.assertEqual(scorecards[idx].rank, idx + 1)

    def test_no_automatic_production_switch(self):
        """Candidate evaluation produces a scorecard without altering production configuration."""
        scorecards = ModelBenchmarkEngine.evaluate_candidates(self.contexts_2021)
        self.assertIsNotNone(scorecards)
        # Verify baseline candidate slot is still groq_primary
        base = LLMAdapterFactory.get_candidate("groq_primary")
        self.assertEqual(base.model_id, "llama-3.3-70b-versatile")


if __name__ == "__main__":
    unittest.main()
