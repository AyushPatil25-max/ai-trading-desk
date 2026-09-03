"""
Phase 6.1 — Evidence Layer Foundation Offline Tests

Exhaustive offline tests (no network, no LLM calls, deterministic).
Covers:
1. Valid evidence extraction
2. Malformed evidence rejection (empty dict, non-dict, non-finite floats, missing fields)
3. Provenance preservation
4. Context ID preservation & consistency enforcement
5. Data timestamp preservation
6. Numerical value preservation (exact floats, ints, bools, zero rounding/mutation)
7. Degraded specialist handling (FundamentalSpecialist DEGRADED, no false signals)
8. Failed specialist handling (no crash, structured missing data)
9. Timeout specialist handling (no crash, structured missing data)
10. Contradiction detection (directional: BULLISH vs BEARISH)
11. Contradiction detection (numerical: metric discrepancies > 1%)
12. Chain-of-thought filtering (strict removal/rejection of forbidden keys)
13. Empty specialist result handling
14. Multiple specialists contributing evidence
15. Deterministic aggregation repeatability
16. No mutation of MarketContext
17. Backward compatibility with UnifiedEvidencePackage and aggregate()
"""

import math
import unittest
from datetime import datetime, timezone, timedelta
from copy import deepcopy

from backend.domain.schemas import (
    SpecialistRunResult, AgentExecutionRecord, AgentState, AgentOutput,
    MarketContext, ProviderType, ProvenanceRecord, DataSource, DataQuality,
    SourceTier, VerificationStatus,
    SignalDirection, EvidenceType, ConflictSeverity, MissingDataCategory,
    EvidenceRecord, ContradictionRecord, RejectedEvidenceRecord, EvidenceSummary,
    UnifiedEvidencePackage, EvidenceCategory,
)
from backend.application.evidence_aggregator import EvidenceAggregator, AggregationError


class TestPhase61EvidenceLayer(unittest.TestCase):
    def setUp(self):
        self.aggregator = EvidenceAggregator()
        self.now = datetime(2026, 8, 29, 10, 0, 0, tzinfo=timezone.utc)
        self.data_ts = datetime(2026, 8, 28, 15, 30, 0, tzinfo=timezone.utc)
        self.data_source = DataSource(
            provider_name="NSE",
            source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
            authority="National Stock Exchange of India",
            subscription_required=False,
            authentication_required=False,
            provider_version="1.0",
        )
        self.prov = ProvenanceRecord(
            metric="current_price",
            symbol="INFY.NS",
            value=1800.0,
            unit="INR",
            currency="INR",
            source=self.data_source,
            verification_status=VerificationStatus.VERIFIED,
            quality=DataQuality.HIGH,
            observed_at=self.data_ts,
            retrieved_at=self.now,
            publication_time=self.data_ts,
            effective_time=self.data_ts,
            period="real-time",
            context_id="ctx-phase6-001",
            adjusted=False,
        )
        self.ctx = MarketContext(
            context_id="ctx-phase6-001",
            symbol="INFY.NS",
            data_timestamp=self.data_ts,
            current_price=1800.0,
            provider=ProviderType.STANDARD_DATA_VENDOR,
            provider_timestamp=self.data_ts,
            provenance=[self.prov],
            provenance_records={"current_price": self.prov},
        )

    def _make_record(
        self,
        agent_name: str,
        state: AgentState,
        raw_data: dict,
        confidence: float = 0.85,
        conclusion: str = "Test conclusion",
        error_message: str = None,
        context_id: str = "ctx-phase6-001",
    ) -> AgentExecutionRecord:
        output = None
        if state in [AgentState.SUCCESS, AgentState.DEGRADED]:
            output = AgentOutput(
                agent_name=agent_name,
                version="1.0",
                model="mock-llm",
                status=state,
                data_timestamp=self.data_ts,
                confidence=confidence,
                conclusion=conclusion,
                risks=["Risk A", "Risk B"],
                assumptions=["Assumption 1"],
                invalidation_conditions=["Invalidate if price breaks 1750"],
                raw_data=raw_data,
            )
        return AgentExecutionRecord(
            agent_name=agent_name,
            agent_version="1.0",
            context_id=context_id,
            started_at=self.now,
            completed_at=self.now,
            duration_seconds=0.15,
            status=state,
            output=output,
            error_message=error_message,
        )

    def _make_run_result(self, records, context_id="ctx-phase6-001") -> SpecialistRunResult:
        return SpecialistRunResult(
            run_id="run-phase6-001",
            context_id=context_id,
            symbol="INFY.NS",
            started_at=self.now,
            completed_at=self.now,
            duration_seconds=0.5,
            total_agents=len(records),
            successful_agents=sum(1 for r in records if r.status == AgentState.SUCCESS),
            failed_agents=sum(1 for r in records if r.status == AgentState.FAILED),
            timed_out_agents=sum(1 for r in records if r.status == AgentState.TIMEOUT),
            degraded_agents=sum(1 for r in records if r.status == AgentState.DEGRADED),
            records=records,
            outputs=[r.output for r in records if r.output],
        )

    # 1. Valid evidence extraction
    def test_valid_evidence_extraction(self):
        rec_tech = self._make_record(
            "TechnicalSpecialist",
            AgentState.SUCCESS,
            {
                "trend": "BULLISH",
                "setup": "BREAKOUT",
                "technical_score": 8.5,
                "evidence": [
                    {"name": "CurrentPrice", "value": 1800.0, "interpretation": "Price above EMA20"},
                    {"name": "RSI", "value": 62.4, "unit": "index", "interpretation": "Bullish momentum"},
                ],
            },
        )
        rec_mom = self._make_record(
            "MomentumSpecialist",
            AgentState.SUCCESS,
            {
                "momentum_direction": "BULLISH",
                "momentum_score": 7.8,
                "evidence": [
                    {"name": "RSI_14", "value": 62.4, "unit": "index", "interpretation": "Positive slope"},
                    {"name": "EMA_Spread_Pct", "value": 2.15, "unit": "%", "interpretation": "Widening spread"},
                ],
            },
        )
        run_res = self._make_run_result([rec_tech, rec_mom])
        summary = self.aggregator.aggregate_evidence(run_res, market_context=self.ctx)

        self.assertIsInstance(summary, EvidenceSummary)
        self.assertEqual(summary.run_id, "run-phase6-001")
        self.assertEqual(summary.symbol, "INFY.NS")
        self.assertEqual(summary.context_id, "ctx-phase6-001")
        self.assertGreater(summary.valid_evidence, 0)
        self.assertEqual(summary.rejected_evidence, 0)
        self.assertEqual(len(summary.failed_specialists), 0)
        self.assertEqual(len(summary.degraded_specialists), 0)

        # Check fields of extracted EvidenceRecord
        tech_records = [r for r in summary.evidence_records if r.specialist_name == "TechnicalSpecialist"]
        self.assertGreater(len(tech_records), 0)
        for er in tech_records:
            self.assertEqual(er.context_id, "ctx-phase6-001")
            self.assertEqual(er.data_timestamp, self.data_ts)
            self.assertTrue(len(er.claim) > 0)
            self.assertEqual(er.status, AgentState.SUCCESS)

    # 2. Malformed evidence rejection
    def test_malformed_evidence_rejection(self):
        rec_tech = self._make_record(
            "TechnicalSpecialist",
            AgentState.SUCCESS,
            {
                "trend": "BULLISH",
                "evidence": [
                    {"name": "ValidMetric", "value": 100.0, "interpretation": "Valid"},
                    {},  # Empty dictionary
                    "not_a_dictionary",  # Primitive string
                    12345,  # Primitive int
                    {"random_key": "no_name_and_no_claim"},  # Missing metric name & claim
                    {"name": "NaNMetric", "value": float("nan")},  # NaN float
                    {"name": "InfMetric", "value": float("inf")},  # Infinity float
                ],
            },
        )
        run_res = self._make_run_result([rec_tech])
        summary = self.aggregator.aggregate_evidence(run_res)

        # Valid items: Regime record + ValidMetric = 2
        # Rejected items: empty dict, string, int, missing name/claim, nan, inf = 6
        self.assertEqual(summary.rejected_evidence, 6)
        self.assertEqual(len(summary.rejected_records), 6)
        self.assertGreater(summary.valid_evidence, 0)
        self.assertEqual(summary.total_evidence, summary.valid_evidence + summary.rejected_evidence)

    # 3. Provenance preservation
    def test_provenance_preservation(self):
        rec_tech = self._make_record(
            "TechnicalSpecialist",
            AgentState.SUCCESS,
            {
                "trend": "BULLISH",
                "evidence": [{"name": "Price", "value": 1800.0, "interpretation": "At high"}],
            },
        )
        run_res = self._make_run_result([rec_tech])
        summary = self.aggregator.aggregate_evidence(run_res, market_context=self.ctx)

        for er in summary.evidence_records:
            self.assertIsNotNone(er.provenance)
            self.assertEqual(len(er.provenance), 1)
            self.assertEqual(er.provenance[0].source.provider_name, "NSE")
            self.assertEqual(er.provenance[0].source.source_tier, SourceTier.TIER_1_PRIMARY_OFFICIAL)

    # 4. Context ID preservation & consistency enforcement
    def test_context_id_preservation_and_mismatch_rejection(self):
        rec_tech = self._make_record(
            "TechnicalSpecialist",
            AgentState.SUCCESS,
            {"trend": "BULLISH", "evidence": []},
            context_id="ctx-phase6-001",
        )
        run_res = self._make_run_result([rec_tech], context_id="ctx-phase6-001")
        summary = self.aggregator.aggregate_evidence(run_res)
        self.assertEqual(summary.context_id, "ctx-phase6-001")
        for er in summary.evidence_records:
            self.assertEqual(er.context_id, "ctx-phase6-001")

        # Inconsistent context_id across specialists must raise AggregationError
        rec_mismatch = self._make_record(
            "MomentumSpecialist",
            AgentState.SUCCESS,
            {"momentum_direction": "BULLISH"},
            context_id="ctx-DIFFERENT-404",
        )
        bad_run_res = self._make_run_result([rec_tech, rec_mismatch], context_id="ctx-phase6-001")
        with self.assertRaises(AggregationError):
            self.aggregator.aggregate_evidence(bad_run_res)

    # 5. Data timestamp preservation
    def test_data_timestamp_preservation(self):
        custom_data_ts = datetime(2026, 8, 25, 9, 15, 0, tzinfo=timezone.utc)
        rec_tech = self._make_record(
            "TechnicalSpecialist",
            AgentState.SUCCESS,
            {
                "trend": "NEUTRAL",
                "evidence": [{"name": "EMA20", "value": 1780.5, "interpretation": "Near price"}],
            },
        )
        rec_tech.output.data_timestamp = custom_data_ts
        run_res = self._make_run_result([rec_tech])
        summary = self.aggregator.aggregate_evidence(run_res)

        for er in summary.evidence_records:
            self.assertEqual(er.data_timestamp, custom_data_ts)

    # 6. Numerical value preservation (exact values without mutation)
    def test_numerical_value_preservation(self):
        exact_numbers = [
            ("float_a", 180.6358),
            ("float_b", 0.0000123),
            ("int_a", 42),
            ("int_zero", 0),
            ("large_num", 1000000000.55),
        ]
        rec = self._make_record(
            "QuantSpecialist",
            AgentState.SUCCESS,
            {
                "statistical_regime": "MEAN_REVERTING",
                "metrics": [{"metric_name": k, "value": v, "interpretation": f"Testing {k}"} for k, v in exact_numbers],
            },
        )
        run_res = self._make_run_result([rec])
        summary = self.aggregator.aggregate_evidence(run_res)

        extracted_vals = {er.metric_name: er.value for er in summary.evidence_records if er.metric_name in dict(exact_numbers)}
        for k, v in exact_numbers:
            self.assertIn(k, extracted_vals)
            self.assertEqual(extracted_vals[k], v)
            self.assertIsInstance(extracted_vals[k], type(v))

    # 7. Degraded specialist handling
    def test_degraded_specialist_handling(self):
        # FundamentalSpecialist degraded due to missing quarterly statement data
        rec_fund = self._make_record(
            "FundamentalSpecialist",
            AgentState.DEGRADED,
            {"fundamental_quality": "INDETERMINATE", "metrics": []},
            confidence=0.0,
            conclusion="Fundamental statements missing; operating in degraded mode",
            error_message="Statement data absent",
        )
        rec_tech = self._make_record(
            "TechnicalSpecialist",
            AgentState.SUCCESS,
            {"trend": "BULLISH", "evidence": [{"name": "Price", "value": 1800.0, "interpretation": "Strong"}]},
        )
        run_res = self._make_run_result([rec_fund, rec_tech])
        summary = self.aggregator.aggregate_evidence(run_res)

        self.assertIn("FundamentalSpecialist", summary.degraded_specialists)
        self.assertEqual(len(summary.failed_specialists), 0)

        # Missing data record logged
        fund_missing = [m for m in summary.missing_data_records if m.specialist_name == "FundamentalSpecialist"]
        self.assertEqual(len(fund_missing), 1)
        self.assertEqual(fund_missing[0].category, MissingDataCategory.SPECIALIST_DEGRADED)

        # Unavailable record created with UNKNOWN direction (not bullish or bearish)
        fund_records = [r for r in summary.evidence_records if r.specialist_name == "FundamentalSpecialist"]
        self.assertGreater(len(fund_records), 0)
        for fr in fund_records:
            self.assertEqual(fr.status, AgentState.DEGRADED)
            self.assertIn(fr.direction, [SignalDirection.UNKNOWN, SignalDirection.NEUTRAL])
            self.assertNotEqual(fr.direction, SignalDirection.BULLISH)
            self.assertNotEqual(fr.direction, SignalDirection.BEARISH)

    # 8. Failed specialist handling
    def test_failed_specialist_handling(self):
        rec_failed = self._make_record(
            "ValuationSpecialist",
            AgentState.FAILED,
            raw_data={},
            error_message="500 Internal Server Error in DCF engine",
        )
        rec_tech = self._make_record(
            "TechnicalSpecialist",
            AgentState.SUCCESS,
            {"trend": "BULLISH", "evidence": [{"name": "Price", "value": 1800.0, "interpretation": "Strong"}]},
        )
        run_res = self._make_run_result([rec_failed, rec_tech])
        summary = self.aggregator.aggregate_evidence(run_res)

        self.assertIn("ValuationSpecialist", summary.failed_specialists)
        val_missing = [m for m in summary.missing_data_records if m.specialist_name == "ValuationSpecialist"]
        self.assertEqual(len(val_missing), 1)
        self.assertEqual(val_missing[0].category, MissingDataCategory.SPECIALIST_FAILED)
        self.assertIn("500 Internal Server Error", val_missing[0].detail)

        # Failed specialist does not invent evidence records
        val_records = [r for r in summary.evidence_records if r.specialist_name == "ValuationSpecialist"]
        self.assertEqual(len(val_records), 0)

    # 9. Timeout specialist handling
    def test_timeout_specialist_handling(self):
        rec_timeout = self._make_record(
            "MacroSpecialist",
            AgentState.TIMEOUT,
            raw_data={},
            error_message="Macro execution exceeded 60.0s timeout",
        )
        run_res = self._make_run_result([rec_timeout])
        summary = self.aggregator.aggregate_evidence(run_res)

        self.assertIn("MacroSpecialist", summary.failed_specialists)
        macro_missing = [m for m in summary.missing_data_records if m.specialist_name == "MacroSpecialist"]
        self.assertEqual(len(macro_missing), 1)
        self.assertEqual(macro_missing[0].category, MissingDataCategory.SPECIALIST_TIMEOUT)

    # 10. Contradiction detection (directional)
    def test_contradiction_detection_directional(self):
        rec_bull = self._make_record(
            "TechnicalSpecialist",
            AgentState.SUCCESS,
            {"trend": "BULLISH", "evidence": []},
            conclusion="Clear upward trend and breakout setup",
        )
        rec_bear = self._make_record(
            "MomentumSpecialist",
            AgentState.SUCCESS,
            {"momentum_direction": "BEARISH", "evidence": []},
            conclusion="Severe momentum breakdown and divergence",
        )
        run_res = self._make_run_result([rec_bull, rec_bear])
        summary = self.aggregator.aggregate_evidence(run_res)

        self.assertGreater(len(summary.contradictions), 0)
        contra = summary.contradictions[0]
        self.assertIsInstance(contra, ContradictionRecord)
        self.assertEqual(contra.severity, ConflictSeverity.HIGH)
        self.assertIn("TechnicalSpecialist", [contra.specialist_a, contra.specialist_b])
        self.assertIn("MomentumSpecialist", [contra.specialist_a, contra.specialist_b])
        # Verify both opposing claims are preserved without resolving
        self.assertIn(contra.direction_a, [SignalDirection.BULLISH, SignalDirection.BEARISH])
        self.assertIn(contra.direction_b, [SignalDirection.BULLISH, SignalDirection.BEARISH])
        self.assertNotEqual(contra.direction_a, contra.direction_b)

    # 11. Contradiction detection (numerical metric discrepancy)
    def test_contradiction_detection_numerical(self):
        rec_tech = self._make_record(
            "TechnicalSpecialist",
            AgentState.SUCCESS,
            {
                "trend": "BULLISH",
                "evidence": [{"name": "RSI", "value": 75.0, "interpretation": "Overbought"}],
            },
        )
        rec_quant = self._make_record(
            "QuantSpecialist",
            AgentState.SUCCESS,
            {
                "statistical_regime": "MEAN_REVERTING",
                "metrics": [{"metric_name": "RSI", "value": 35.0, "interpretation": "Oversold"}],
            },
        )
        run_res = self._make_run_result([rec_tech, rec_quant])
        summary = self.aggregator.aggregate_evidence(run_res)

        num_contras = [c for c in summary.contradictions if "RSI" in c.subject]
        self.assertEqual(len(num_contras), 1)
        contra = num_contras[0]
        self.assertEqual(contra.severity, ConflictSeverity.CRITICAL)
        self.assertIn(75.0, [contra.value_a, contra.value_b])
        self.assertIn(35.0, [contra.value_a, contra.value_b])

    # 12. Chain-of-thought filtering
    def test_chain_of_thought_filtering(self):
        rec_tech = self._make_record(
            "TechnicalSpecialist",
            AgentState.SUCCESS,
            {
                "trend": "BULLISH",
                "chain_of_thought": "Step 1: Let's consider whether RSI is too high. Step 2: Yes, wait.",
                "evidence": [
                    {
                        "name": "EMA20",
                        "value": 1780.0,
                        "interpretation": "Price above EMA20",
                        "internal_reasoning": "Hidden thought block that must be stripped",
                    },
                    {
                        "chain_of_thought": "Only CoT, no metric or claim",
                        "thinking": "Thinking process details...",
                    },
                ],
            },
            conclusion="Thinking Process: Trend is solidly bullish after evaluation.",
        )
        run_res = self._make_run_result([rec_tech])
        summary = self.aggregator.aggregate_evidence(run_res)

        # Sole CoT item rejected
        cot_rejections = [r for r in summary.rejected_records if "Chain-of-thought" in r.reason]
        self.assertEqual(len(cot_rejections), 1)

        # Valid EMA20 item preserved without CoT
        ema_records = [r for r in summary.evidence_records if r.metric_name == "EMA20"]
        self.assertEqual(len(ema_records), 1)
        ema_rec = ema_records[0]
        self.assertEqual(ema_rec.value, 1780.0)

        # Verify no EvidenceRecord has CoT markers in its claim
        for er in summary.evidence_records:
            self.assertNotIn("Thinking Process:", er.claim)
            self.assertNotIn("<think>", er.claim)

    # 13. Empty specialist result handling
    def test_empty_specialist_result_handling(self):
        empty_run = SpecialistRunResult(
            run_id="run-empty-001",
            context_id="ctx-empty",
            symbol="EMPTY.NS",
            started_at=self.now,
            completed_at=self.now,
            duration_seconds=0.01,
            total_agents=0,
            successful_agents=0,
            failed_agents=0,
            timed_out_agents=0,
            degraded_agents=0,
            records=[],
            outputs=[],
        )
        summary = self.aggregator.aggregate_evidence(empty_run)
        self.assertEqual(summary.total_evidence, 0)
        self.assertEqual(summary.valid_evidence, 0)
        self.assertEqual(summary.rejected_evidence, 0)
        self.assertEqual(len(summary.evidence_records), 0)
        self.assertEqual(len(summary.contradictions), 0)

    # 14. Multiple specialists contributing evidence
    def test_multiple_specialists_contributing_evidence(self):
        rec_tech = self._make_record(
            "TechnicalSpecialist",
            AgentState.SUCCESS,
            {"trend": "BULLISH", "evidence": [{"name": "EMA20", "value": 1780.0}]},
        )
        rec_mom = self._make_record(
            "MomentumSpecialist",
            AgentState.SUCCESS,
            {"momentum_direction": "BULLISH", "evidence": [{"name": "RSI", "value": 55.0}]},
        )
        rec_quant = self._make_record(
            "QuantSpecialist",
            AgentState.SUCCESS,
            {"statistical_regime": "TREND_CONSISTENT", "metrics": [{"metric_name": "ZScore", "value": 1.25}]},
        )
        rec_fund = self._make_record(
            "FundamentalSpecialist",
            AgentState.DEGRADED,
            {"fundamental_quality": "INDETERMINATE", "metrics": []},
            confidence=0.0,
        )
        run_res = self._make_run_result([rec_tech, rec_mom, rec_quant, rec_fund])
        summary = self.aggregator.aggregate_evidence(run_res)

        specialist_names = set(r.specialist_name for r in summary.evidence_records)
        self.assertIn("TechnicalSpecialist", specialist_names)
        self.assertIn("MomentumSpecialist", specialist_names)
        self.assertIn("QuantSpecialist", specialist_names)
        self.assertIn("FundamentalSpecialist", specialist_names)
        self.assertEqual(summary.total_evidence, len(summary.evidence_records) + len(summary.rejected_records))

    # 15. Deterministic aggregation repeatability
    def test_deterministic_aggregation_repeatability(self):
        rec_tech = self._make_record(
            "TechnicalSpecialist",
            AgentState.SUCCESS,
            {"trend": "BULLISH", "evidence": [{"name": "Price", "value": 1800.0}]},
        )
        rec_mom = self._make_record(
            "MomentumSpecialist",
            AgentState.SUCCESS,
            {"momentum_direction": "BEARISH", "evidence": [{"name": "RSI", "value": 40.0}]},
        )
        run_res = self._make_run_result([rec_tech, rec_mom])

        sum1 = self.aggregator.aggregate_evidence(run_res)
        sum2 = self.aggregator.aggregate_evidence(run_res)

        self.assertEqual(sum1.total_evidence, sum2.total_evidence)
        self.assertEqual(sum1.valid_evidence, sum2.valid_evidence)
        self.assertEqual(sum1.rejected_evidence, sum2.rejected_evidence)
        self.assertEqual(len(sum1.contradictions), len(sum2.contradictions))
        self.assertEqual(
            [c.subject for c in sum1.contradictions],
            [c.subject for c in sum2.contradictions],
        )

    # 16. No mutation of MarketContext
    def test_no_mutation_of_market_context(self):
        rec_tech = self._make_record(
            "TechnicalSpecialist",
            AgentState.SUCCESS,
            {"trend": "BULLISH", "evidence": [{"name": "Price", "value": 1800.0}]},
        )
        run_res = self._make_run_result([rec_tech])

        ctx_before = deepcopy(self.ctx.model_dump())
        _ = self.aggregator.aggregate_evidence(run_res, market_context=self.ctx)
        ctx_after = deepcopy(self.ctx.model_dump())

        self.assertEqual(ctx_before, ctx_after)

    # 17. Backward compatibility with UnifiedEvidencePackage and aggregate()
    def test_backward_compatibility_with_aggregate(self):
        rec_tech = self._make_record(
            "TechnicalSpecialist",
            AgentState.SUCCESS,
            {"trend": "BULLISH", "evidence": [{"name": "Price", "value": 1800.0}]},
        )
        run_res = self._make_run_result([rec_tech])

        # Default aggregate() call returns UnifiedEvidencePackage
        pkg = self.aggregator.aggregate(run_res)
        self.assertIsInstance(pkg, UnifiedEvidencePackage)
        self.assertEqual(pkg.symbol, "INFY.NS")

        # aggregate(as_summary=True) returns EvidenceSummary
        summary = self.aggregator.aggregate(run_res, as_summary=True)
        self.assertIsInstance(summary, EvidenceSummary)
        self.assertEqual(summary.symbol, "INFY.NS")


if __name__ == "__main__":
    unittest.main()
