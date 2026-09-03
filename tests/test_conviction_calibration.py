"""
Phase 6.5 — Conviction & Decision Calibration Comprehensive Offline Tests

Verifies all 38 requirements:
1. calibration creation
2. deterministic repeatability
3. score range 0.0–1.0
4. score boundary conditions
5. conviction band mapping
6. strong evidence
7. weak evidence
8. insufficient evidence
9. specialist consensus
10. specialist disagreement
11. UNKNOWN specialist
12. degraded specialist
13. debate integration
14. strong bull case
15. strong bear case
16. balanced debate
17. unresolved contradiction
18. data quality penalty
19. stale data
20. missing critical data
21. committee integration
22. recommendation consistency
23. BUY with low conviction
24. SELL with high conviction
25. HOLD with high conviction
26. risk score separation
27. risk veto preservation
28. position sizing cannot be overridden
29. NaN handling
30. infinity handling
31. out-of-range input
32. provenance
33. context_id propagation
34. decision_id propagation
35. calibration version
36. correlation discounting
37. backward compatibility
38. complete end-to-end integration:
    MarketContext -> Specialists -> EvidenceAggregator -> DebateEngine -> InvestmentCommittee -> ConvictionCalibrator -> RiskEngine -> PositionSizingPlan
"""

from copy import deepcopy
from datetime import datetime, timezone
import math
import unittest
from typing import Any, Dict, List

from backend.domain.schemas import (
    MarketContext,
    EvidenceSummary,
    EvidenceRecord,
    EvidenceCategory,
    SignalDirection,
    EvidenceType,
    ConflictSeverity,
    ContradictionRecord,
    SpecialistRunResult,
    AgentInput,
    AgentOutput,
    AgentExecutionRecord,
    AgentState,
    _TechnicalLLMResponse, TrendDirection, SetupType,
    _MomentumLLMResponse, MomentumDirection, MomentumStrength,
    _QuantLLMResponse, QuantStatisticalRegime, QuantRiskCharacterization,
    _FundamentalLLMResponse, FundamentalQuality, GrowthAssessment, ProfitabilityAssessment, BalanceSheetAssessment,
)
from backend.domain.debate_schemas import (
    DebateResult, DebateArgument, DebateSide, DebateDecisionState, RiskAssessment,
)
from backend.domain.investment_committee_schemas import (
    CommitteeRecommendation,
    DataQualityStatus,
    CommitteeDecision,
)
from backend.domain.risk_schemas import (
    PositionDirection,
    RiskConfiguration,
    PositionSizingPlan,
)
from backend.domain.calibration_schemas import (
    CALIBRATION_VERSION,
    ConvictionBand,
    SpecialistAgreementLevel,
    RecommendationConsistency,
    PillarBreakdown,
    ConvictionCalibrationResult,
)
from backend.application.conviction_calibrator import ConvictionCalibrator
from backend.application.risk_engine import RiskEngine
from backend.application.investment_committee import InvestmentCommittee
from backend.application.debate_engine import DebateEngine
from backend.application.evidence_aggregator import EvidenceAggregator
from backend.specialists.technical_specialist import TechnicalSpecialist
from backend.specialists.momentum_specialist import MomentumSpecialist
from backend.specialists.quant_specialist import QuantSpecialist
from backend.specialists.fundamental_specialist import FundamentalSpecialist
from backend.infrastructure.llm import MockLLMClient


class TestConvictionCalibrationPhase65(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 29, 12, 0, 0, tzinfo=timezone.utc)
        self.ctx = MarketContext(
            context_id="ctx-calib-p65-001",
            symbol="INFY.NS",
            data_timestamp=self.now,
            current_price=100.0,
            provider="mock-vendor",
            technical_indicators={
                "rsi": 65.0,
                "ema20": 96.0,
                "ema50": 95.0,
                "20_day_high": 115.0,
                "20_day_low": 90.0,
            },
            provenance=[{"source": "calib_test_setup", "timestamp": str(self.now)}],
        )

        self.decision = CommitteeDecision(
            decision_id="dec-calib-p65-001",
            run_id="run-calib-001",
            context_id="ctx-calib-p65-001",
            symbol="INFY.NS",
            decision_timestamp=self.now,
            started_at=self.now,
            completed_at=self.now,
            duration_seconds=0.1,
            recommendation=CommitteeRecommendation.BUY,
            conviction_score=0.75,
            confidence=0.80,
            time_horizon="MEDIUM_TERM",
            supporting_evidence_ids=["ev-tech-01", "ev-fund-01"],
            opposing_evidence_ids=[],
            strongest_bull_arguments=[],
            strongest_bear_arguments=[],
            unresolved_contradictions=[],
            risk_score=0.25,
            risk_level="LOW",
            risk_veto_applied=False,
            data_quality=DataQualityStatus.AVAILABLE,
            investment_thesis="Solid multi-pillar momentum and earnings.",
            decision_summary="Approved buy recommendation.",
            why_bull_case_wins="Decisive trend and margin expansion.",
            why_bear_case_wins="Limited downside risk.",
            what_would_change_the_decision="Close below 95.0.",
        )

        self.debate = DebateResult(
            debate_id="deb-calib-001",
            run_id="run-calib-001",
            context_id="ctx-calib-p65-001",
            symbol="INFY.NS",
            bull_strength=0.80,
            bear_strength=0.30,
            confidence=0.85,
            risk_score=0.25,
            evidence_coverage=0.85,
            final_debate_state=DebateDecisionState.BULL_FAVORED,
            unresolved_contradictions=[],
        )

    def _make_evidence(
        self,
        evidence_id: str,
        category: EvidenceCategory,
        strength: float = 0.80,
        confidence: float = 0.80,
        direction: SignalDirection = SignalDirection.BULLISH,
    ) -> EvidenceRecord:
        return EvidenceRecord(
            evidence_id=evidence_id,
            context_id="ctx-calib-p65-001",
            symbol="INFY.NS",
            specialist_name="TestSpecialist",
            data_timestamp=self.now,
            category=category,
            strength=strength,
            confidence=confidence,
            direction=direction,
            claim=f"Test claim {evidence_id}",
        )

    def _make_evidence_summary(
        self,
        records: List[EvidenceRecord],
        total: Optional[int] = None,
    ) -> EvidenceSummary:
        tot = len(records) if total is None else total
        return EvidenceSummary(
            run_id="run-calib-001",
            context_id="ctx-calib-p65-001",
            symbol="INFY.NS",
            evidence_records=records,
            total_evidence=tot,
            valid_evidence=tot,
        )

    # 1. Calibration creation
    def test_01_calibration_creation(self):
        calibrator = ConvictionCalibrator()
        self.assertEqual(calibrator.version, CALIBRATION_VERSION)
        self.assertEqual(calibrator.version, "6.5.0")

        res = calibrator.calibrate(self.decision, self.debate)
        self.assertIsInstance(res, ConvictionCalibrationResult)
        self.assertEqual(res.symbol, "INFY.NS")
        self.assertEqual(res.context_id, "ctx-calib-p65-001")
        self.assertEqual(res.decision_id, "dec-calib-p65-001")

    # 2. Deterministic repeatability
    def test_02_deterministic_repeatability(self):
        calibrator = ConvictionCalibrator()
        r1 = calibrator.calibrate(self.decision, self.debate)
        r2 = calibrator.calibrate(self.decision, self.debate)
        self.assertEqual(r1.calibrated_conviction, r2.calibrated_conviction)
        self.assertEqual(r1.conviction_band, r2.conviction_band)
        self.assertEqual(r1.specialist_agreement, r2.specialist_agreement)
        self.assertEqual(r1.recommendation_consistency, r2.recommendation_consistency)

    # 3. Score range 0.0–1.0
    def test_03_score_range(self):
        calibrator = ConvictionCalibrator()
        res = calibrator.calibrate(self.decision, self.debate)
        self.assertGreaterEqual(res.calibrated_conviction, 0.0)
        self.assertLessEqual(res.calibrated_conviction, 1.0)

    # 4. Score boundary conditions
    def test_04_score_boundary_conditions(self):
        calibrator = ConvictionCalibrator()
        # High extreme
        dec_high = self.decision.model_copy(update={"conviction_score": 1.0})
        deb_high = self.debate.model_copy(update={"bull_strength": 1.0, "bear_strength": 0.0})
        r_high = calibrator.calibrate(dec_high, deb_high)
        self.assertLessEqual(r_high.calibrated_conviction, 1.0)
        self.assertGreaterEqual(r_high.calibrated_conviction, 0.0)

        # Low extreme
        dec_low = self.decision.model_copy(update={"conviction_score": 0.0})
        deb_low = self.debate.model_copy(update={"bull_strength": 0.0, "bear_strength": 1.0})
        r_low = calibrator.calibrate(dec_low, deb_low)
        self.assertEqual(r_low.calibrated_conviction, 0.0)

    # 5. Conviction band mapping
    def test_05_conviction_band_mapping(self):
        self.assertEqual(ConvictionBand.from_score(0.05), ConvictionBand.VERY_LOW)
        self.assertEqual(ConvictionBand.from_score(0.25), ConvictionBand.LOW)
        self.assertEqual(ConvictionBand.from_score(0.45), ConvictionBand.MODERATE)
        self.assertEqual(ConvictionBand.from_score(0.65), ConvictionBand.HIGH)
        self.assertEqual(ConvictionBand.from_score(0.85), ConvictionBand.VERY_HIGH)

    # 6. Strong evidence
    def test_06_strong_evidence(self):
        records = [
            self._make_evidence("e1", EvidenceCategory.TECHNICAL, strength=0.90, confidence=0.90, direction=SignalDirection.BULLISH),
            self._make_evidence("e2", EvidenceCategory.FUNDAMENTAL, strength=0.90, confidence=0.90, direction=SignalDirection.BULLISH),
            self._make_evidence("e3", EvidenceCategory.QUANT, strength=0.85, confidence=0.85, direction=SignalDirection.BULLISH),
        ]
        ev = self._make_evidence_summary(records)
        calibrator = ConvictionCalibrator()
        res = calibrator.calibrate(self.decision, self.debate, evidence_summary=ev)
        self.assertIn(res.conviction_band, (ConvictionBand.HIGH, ConvictionBand.VERY_HIGH))
        self.assertGreaterEqual(res.calibrated_conviction, 0.60)

    # 7. Weak evidence
    def test_07_weak_evidence(self):
        records = [
            self._make_evidence("e1", EvidenceCategory.TECHNICAL, strength=0.25, confidence=0.30, direction=SignalDirection.NEUTRAL),
            self._make_evidence("e2", EvidenceCategory.FUNDAMENTAL, strength=0.20, confidence=0.25, direction=SignalDirection.NEUTRAL),
        ]
        ev = self._make_evidence_summary(records)
        dec = self.decision.model_copy(update={"conviction_score": 0.25, "recommendation": CommitteeRecommendation.WATCH})
        calibrator = ConvictionCalibrator()
        res = calibrator.calibrate(dec, self.debate, evidence_summary=ev)
        self.assertIn(res.conviction_band, (ConvictionBand.VERY_LOW, ConvictionBand.LOW))
        self.assertLess(res.calibrated_conviction, 0.40)

    # 8. Insufficient evidence
    def test_08_insufficient_evidence(self):
        ev = self._make_evidence_summary([], total=0)
        dec = self.decision.model_copy(update={"data_quality": DataQualityStatus.INSUFFICIENT, "conviction_score": 0.10, "recommendation": CommitteeRecommendation.INDETERMINATE})
        calibrator = ConvictionCalibrator()
        res = calibrator.calibrate(dec, self.debate, evidence_summary=ev)
        self.assertEqual(res.conviction_band, ConvictionBand.VERY_LOW)
        self.assertLessEqual(res.calibrated_conviction, 0.15)

    # 9. Specialist consensus
    def test_09_specialist_consensus(self):
        records = [
            self._make_evidence("e1", EvidenceCategory.TECHNICAL, strength=0.80, direction=SignalDirection.BULLISH),
            self._make_evidence("e2", EvidenceCategory.FUNDAMENTAL, strength=0.85, direction=SignalDirection.BULLISH),
            self._make_evidence("e3", EvidenceCategory.QUANT, strength=0.75, direction=SignalDirection.BULLISH),
        ]
        ev = self._make_evidence_summary(records)
        calibrator = ConvictionCalibrator()
        res = calibrator.calibrate(self.decision, self.debate, evidence_summary=ev)
        self.assertEqual(res.specialist_agreement, SpecialistAgreementLevel.STRONG_CONSENSUS)

    # 10. Specialist disagreement
    def test_10_specialist_disagreement(self):
        records = [
            self._make_evidence("e1", EvidenceCategory.TECHNICAL, strength=0.85, direction=SignalDirection.BULLISH),
            self._make_evidence("e2", EvidenceCategory.FUNDAMENTAL, strength=0.85, direction=SignalDirection.BEARISH),
        ]
        ev = self._make_evidence_summary(records)
        calibrator = ConvictionCalibrator()
        res = calibrator.calibrate(self.decision, self.debate, evidence_summary=ev)
        self.assertEqual(res.specialist_agreement, SpecialistAgreementLevel.CONFLICTING)

    # 11. UNKNOWN specialist
    def test_11_unknown_specialist(self):
        records = [
            self._make_evidence("e1", EvidenceCategory.TECHNICAL, strength=0.80, direction=SignalDirection.BULLISH),
            self._make_evidence("e2", EvidenceCategory.FUNDAMENTAL, strength=0.50, direction=SignalDirection.UNKNOWN),
        ]
        ev = self._make_evidence_summary(records)
        calibrator = ConvictionCalibrator()
        res = calibrator.calibrate(self.decision, self.debate, evidence_summary=ev)
        # Only 1 directional active pillar => INSUFFICIENT
        self.assertEqual(res.specialist_agreement, SpecialistAgreementLevel.INSUFFICIENT)

    # 12. Degraded specialist
    def test_12_degraded_specialist(self):
        calibrator = ConvictionCalibrator()
        dec_deg = self.decision.model_copy(update={
            "data_quality": DataQualityStatus.DEGRADED,
            "degraded_specialists": ["TechnicalSpecialist"],
        })
        res_norm = calibrator.calibrate(self.decision, self.debate)
        res_deg = calibrator.calibrate(dec_deg, self.debate)
        self.assertLess(res_deg.calibrated_conviction, res_norm.calibrated_conviction)
        self.assertLessEqual(res_deg.calibrated_conviction, 0.50)

    # 13. Debate integration
    def test_13_debate_integration(self):
        calibrator = ConvictionCalibrator()
        deb_decisive = self.debate.model_copy(update={"bull_strength": 0.85, "bear_strength": 0.20})
        deb_narrow = self.debate.model_copy(update={"bull_strength": 0.52, "bear_strength": 0.48})
        res_decisive = calibrator.calibrate(self.decision, deb_decisive)
        res_narrow = calibrator.calibrate(self.decision, deb_narrow)
        self.assertGreater(res_decisive.calibrated_conviction, res_narrow.calibrated_conviction)

    # 14. Strong bull case
    def test_14_strong_bull_case(self):
        deb_bull = self.debate.model_copy(update={"bull_strength": 0.90, "bear_strength": 0.15})
        calibrator = ConvictionCalibrator()
        res = calibrator.calibrate(self.decision, deb_bull)
        self.assertGreater(res.debate_strength, 0.80)
        self.assertGreater(res.calibrated_conviction, 0.60)

    # 15. Strong bear case
    def test_15_strong_bear_case(self):
        deb_bear = self.debate.model_copy(update={"bull_strength": 0.15, "bear_strength": 0.90})
        dec_sell = self.decision.model_copy(update={
            "recommendation": CommitteeRecommendation.SELL,
            "conviction_score": 0.80,
        })
        calibrator = ConvictionCalibrator()
        res = calibrator.calibrate(dec_sell, deb_bear)
        self.assertGreater(res.calibrated_conviction, 0.60)
        self.assertEqual(res.recommendation_consistency, RecommendationConsistency.CONSISTENT)

    # 16. Balanced debate
    def test_16_balanced_debate(self):
        deb_bal = self.debate.model_copy(update={"bull_strength": 0.50, "bear_strength": 0.50})
        calibrator = ConvictionCalibrator()
        res = calibrator.calibrate(self.decision, deb_bal)
        # Balanced debate receives penalty
        self.assertLess(res.calibrated_conviction, self.decision.conviction_score)

    # 17. Unresolved contradiction
    def test_17_unresolved_contradiction(self):
        crit_contra = ContradictionRecord(
            subject="Trend vs Earnings",
            specialist_a="TechnicalSpecialist",
            claim_a="Trend is rising",
            specialist_b="FundamentalSpecialist",
            claim_b="Earnings dropping",
            severity=ConflictSeverity.CRITICAL,
            explanation="Direct factual conflict between earnings and price trend.",
        )
        dec_contra = self.decision.model_copy(update={"unresolved_contradictions": [crit_contra]})
        calibrator = ConvictionCalibrator()
        res = calibrator.calibrate(dec_contra, self.debate)
        self.assertGreater(res.contradiction_penalty, 0.15)
        self.assertTrue(any("CRITICAL_CONTRADICTION" in w for w in res.warnings))

    # 18. Data quality penalty
    def test_18_data_quality_penalty(self):
        calibrator = ConvictionCalibrator()
        dec_partial = self.decision.model_copy(update={"data_quality": DataQualityStatus.PARTIAL})
        res_avail = calibrator.calibrate(self.decision, self.debate)
        res_partial = calibrator.calibrate(dec_partial, self.debate)
        self.assertLess(res_partial.calibrated_conviction, res_avail.calibrated_conviction)

    # 19. Stale data
    def test_19_stale_data(self):
        dec_stale = self.decision.model_copy(update={"data_quality": DataQualityStatus.STALE})
        calibrator = ConvictionCalibrator()
        res = calibrator.calibrate(dec_stale, self.debate)
        self.assertLessEqual(res.calibrated_conviction, 0.10)
        self.assertEqual(res.conviction_band, ConvictionBand.VERY_LOW)

    # 20. Missing critical data
    def test_20_missing_critical_data(self):
        dec_missing = self.decision.model_copy(update={"missing_critical_data": ["Missing Fundamental Data"]})
        calibrator = ConvictionCalibrator()
        res = calibrator.calibrate(dec_missing, self.debate)
        self.assertGreater(res.missing_data_penalty, 0.0)
        self.assertLessEqual(res.calibrated_conviction, 0.60)

    # 21. Committee integration
    def test_21_committee_integration(self):
        calibrator = ConvictionCalibrator()
        dec_calibrated = calibrator.calibrate_decision(self.decision, self.debate)
        self.assertIsInstance(dec_calibrated, CommitteeDecision)
        self.assertIsNotNone(dec_calibrated.calibrated_conviction)
        self.assertIsNotNone(dec_calibrated.calibration_id)
        self.assertEqual(dec_calibrated.conviction_score, dec_calibrated.calibrated_conviction)

    # 22. Recommendation consistency
    def test_22_recommendation_consistency(self):
        calibrator = ConvictionCalibrator()
        res = calibrator.calibrate(self.decision, self.debate)
        self.assertEqual(res.recommendation_consistency, RecommendationConsistency.CONSISTENT)

    # 23. BUY with low conviction
    def test_23_buy_with_low_conviction(self):
        dec_inconsistent = self.decision.model_copy(update={
            "recommendation": CommitteeRecommendation.BUY,
            "conviction_score": 0.15,
            "data_quality": DataQualityStatus.INSUFFICIENT,
        })
        calibrator = ConvictionCalibrator()
        res = calibrator.calibrate(dec_inconsistent, self.debate)
        self.assertEqual(res.recommendation_consistency, RecommendationConsistency.INCONSISTENT)
        self.assertTrue(any("RECOMMENDATION_INCONSISTENCY" in w for w in res.warnings))

    # 24. SELL with high conviction
    def test_24_sell_with_high_conviction(self):
        dec_sell = self.decision.model_copy(update={
            "recommendation": CommitteeRecommendation.SELL,
            "conviction_score": 0.85,
        })
        deb_bear = self.debate.model_copy(update={"bull_strength": 0.10, "bear_strength": 0.85})
        calibrator = ConvictionCalibrator()
        res = calibrator.calibrate(dec_sell, deb_bear)
        self.assertEqual(res.recommendation_consistency, RecommendationConsistency.CONSISTENT)

    # 25. HOLD with high conviction
    def test_25_hold_with_high_conviction(self):
        # Case A: Risk veto blocks entry -> CONSISTENT
        dec_hold_risk = self.decision.model_copy(update={
            "recommendation": CommitteeRecommendation.HOLD,
            "conviction_score": 0.80,
            "risk_veto_applied": True,
            "risk_veto_reason": "High sector correlation limit breached",
        })
        calibrator = ConvictionCalibrator()
        res_a = calibrator.calibrate(dec_hold_risk, self.debate)
        self.assertEqual(res_a.recommendation_consistency, RecommendationConsistency.CONSISTENT)

        # Case B: High conviction without risk reason -> CAUTIONARY
        dec_hold_clean = self.decision.model_copy(update={
            "recommendation": CommitteeRecommendation.HOLD,
            "conviction_score": 0.85,
            "risk_score": 0.15,
            "risk_veto_applied": False,
        })
        res_b = calibrator.calibrate(dec_hold_clean, self.debate)
        self.assertEqual(res_b.recommendation_consistency, RecommendationConsistency.CAUTIONARY)

    # 26. Risk score separation
    def test_26_risk_score_separation(self):
        calibrator = ConvictionCalibrator()
        res = calibrator.calibrate(self.decision, self.debate)
        self.assertNotEqual(res.calibrated_conviction, res.risk_score)
        self.assertEqual(res.risk_score, 0.25)

    # 27. Risk veto preservation
    def test_27_risk_veto_preservation(self):
        dec_veto = self.decision.model_copy(update={
            "risk_veto_applied": True,
            "risk_veto_reason": "Extreme tail risk",
            "risk_score": 0.90,
        })
        calibrator = ConvictionCalibrator()
        res = calibrator.calibrate(dec_veto, self.debate)
        self.assertTrue(res.risk_veto_applied)
        self.assertEqual(res.risk_veto_reason, "Extreme tail risk")
        self.assertTrue(any("UPSTREAM_RISK_VETO" in w for w in res.warnings))

    # 28. Position sizing cannot be overridden
    def test_28_position_sizing_cannot_be_overridden(self):
        dec_veto = self.decision.model_copy(update={
            "conviction_score": 0.95,
            "risk_veto_applied": True,
            "risk_veto_reason": "Hard safety limit violation",
        })
        calibrator = ConvictionCalibrator()
        calib_res = calibrator.calibrate(dec_veto, self.debate)

        risk_engine = RiskEngine()
        plan = risk_engine.evaluate_and_size(dec_veto, self.ctx, calibration=calib_res)
        self.assertTrue(plan.veto_applied)
        self.assertEqual(plan.position_quantity, 0)

    # 29. NaN handling
    def test_29_nan_handling(self):
        dec_nan = self.decision.model_copy(update={"conviction_score": float("nan")})
        calibrator = ConvictionCalibrator()
        res = calibrator.calibrate(dec_nan, self.debate)
        self.assertFalse(math.isnan(res.calibrated_conviction))
        self.assertEqual(res.calibrated_conviction, 0.0)

    # 30. Infinity handling
    def test_30_infinity_handling(self):
        dec_inf = self.decision.model_copy(update={"conviction_score": float("inf")})
        calibrator = ConvictionCalibrator()
        res = calibrator.calibrate(dec_inf, self.debate)
        self.assertFalse(math.isinf(res.calibrated_conviction))
        self.assertEqual(res.calibrated_conviction, 0.0)

    # 31. Out of range input
    def test_31_out_of_range_input(self):
        dec_neg = self.decision.model_copy(update={"conviction_score": -0.50})
        calibrator = ConvictionCalibrator()
        res = calibrator.calibrate(dec_neg, self.debate)
        self.assertGreaterEqual(res.calibrated_conviction, 0.0)

    # 32. Provenance
    def test_32_provenance(self):
        calibrator = ConvictionCalibrator()
        res = calibrator.calibrate(self.decision, self.debate, market_context=self.ctx)
        self.assertGreater(len(res.provenance), 0)
        self.assertEqual(res.provenance[0]["source"], "calib_test_setup")

    # 33. context_id propagation
    def test_33_context_id_propagation(self):
        calibrator = ConvictionCalibrator()
        res = calibrator.calibrate(self.decision, self.debate)
        self.assertEqual(res.context_id, "ctx-calib-p65-001")
        self.assertEqual(res.symbol, "INFY.NS")

    # 34. decision_id propagation
    def test_34_decision_id_propagation(self):
        calibrator = ConvictionCalibrator()
        res = calibrator.calibrate(self.decision, self.debate)
        self.assertEqual(res.decision_id, "dec-calib-p65-001")

    # 35. Calibration version
    def test_35_calibration_version(self):
        calibrator = ConvictionCalibrator()
        res = calibrator.calibrate(self.decision, self.debate)
        self.assertEqual(res.calibration_version, CALIBRATION_VERSION)
        self.assertEqual(res.calibration_version, "6.5.0")

    # 36. Correlation discounting
    def test_36_correlation_discounting(self):
        records = [
            self._make_evidence("e1", EvidenceCategory.TECHNICAL, strength=0.85, direction=SignalDirection.BULLISH),
            self._make_evidence("e2", EvidenceCategory.MOMENTUM, strength=0.85, direction=SignalDirection.BULLISH),
        ]
        ev = self._make_evidence_summary(records)
        calibrator = ConvictionCalibrator()
        res = calibrator.calibrate(self.decision, self.debate, evidence_summary=ev)
        self.assertGreater(res.correlation_discount, 0.0)
        tm_pillar = next(p for p in res.pillar_details if p.pillar_name == "technical_momentum")
        self.assertAlmostEqual(tm_pillar.correlation_discount_applied, 0.85)

    # 37. Backward compatibility
    def test_37_backward_compatibility(self):
        # CommitteeDecision can still be instantiated without calibration fields
        dec_clean = CommitteeDecision(
            decision_id="d1",
            context_id="c1",
            symbol="INFY.NS",
        )
        self.assertIsNone(dec_clean.calibrated_conviction)
        self.assertIsNone(dec_clean.calibration_id)

    # 38. Complete end-to-end integration test
    async def test_38_complete_end_to_end(self):
        """
        Complete end-to-end integration test verifying:
        MarketContext
        -> Specialists (Technical, Momentum, Quant, Fundamental)
        -> EvidenceAggregator -> EvidenceSummary
        -> DebateEngine -> DebateResult
        -> InvestmentCommittee -> CommitteeDecision
        -> ConvictionCalibrator -> ConvictionCalibrationResult
        -> RiskEngine -> PositionSizingPlan
        All sharing the exact same context_id and traceability.
        """
        e2e_ctx = MarketContext(
            context_id="ctx-e2e-calib-full-001",
            symbol="TCS.NS",
            data_timestamp=self.now,
            current_price=3500.0,
            provider="mock-e2e",
            ohlcv_historical=[
                {"timestamp": "2024-01-01T00:00:00+00:00", "open": 3400.0, "high": 3450.0, "low": 3390.0, "close": 3420.0, "volume": 100000},
                {"timestamp": "2024-01-02T00:00:00+00:00", "open": 3420.0, "high": 3480.0, "low": 3410.0, "close": 3460.0, "volume": 120000},
                {"timestamp": "2024-01-03T00:00:00+00:00", "open": 3460.0, "high": 3500.0, "low": 3450.0, "close": 3480.0, "volume": 110000},
                {"timestamp": "2024-01-04T00:00:00+00:00", "open": 3480.0, "high": 3520.0, "low": 3470.0, "close": 3500.0, "volume": 130000},
                {"timestamp": "2024-01-05T00:00:00+00:00", "open": 3500.0, "high": 3550.0, "low": 3490.0, "close": 3520.0, "volume": 140000},
            ],
            technical_indicators={"rsi": 62.0, "ema20": 3450.0, "ema50": 3400.0, "20_day_high": 3700.0, "20_day_low": 3350.0},
            fundamental_data={
                "period": "FY2024",
                "report_date": "2024-01-15",
                "revenue": 10000.0,
                "net_income": 1900.0,
                "eps": 25.0,
                "total_debt": 500.0,
                "total_equity": 8000.0,
            },
        )

        agent_input = AgentInput(
            symbol="TCS.NS",
            market_context=e2e_ctx,
            historical_ohlcv=e2e_ctx.ohlcv_historical,
            indicators=e2e_ctx.technical_indicators,
            additional_data={"pe_ratio": 24.5, "net_margin": 19.2},
        )

        # 1. Specialists
        tech_spec = TechnicalSpecialist(llm_client=MockLLMClient(fixed_response=_TechnicalLLMResponse(
            trend=TrendDirection.BULLISH,
            setup=SetupType.BREAKOUT,
            technical_score=8.0,
            confirmation=True,
            conclusion="Bullish breakout.",
            invalidation_conditions=["Break below EMA20"],
            risks=["Overbought"],
            assumptions=["Trend continues"],
            confidence=0.85,
        )))
        mom_spec = MomentumSpecialist(llm_client=MockLLMClient(fixed_response=_MomentumLLMResponse(
            momentum_direction=MomentumDirection.BULLISH,
            momentum_strength=MomentumStrength.STRONG,
            confirmation=True,
            conclusion="Accelerating momentum.",
            invalidation_conditions=["Momentum stall"],
            risks=["Exhaustion"],
            assumptions=["Volume sustained"],
            confidence=0.85,
        )))
        quant_spec = QuantSpecialist(llm_client=MockLLMClient(fixed_response=_QuantLLMResponse(
            statistical_regime=QuantStatisticalRegime.NORMAL_VOLATILITY,
            risk_characterization=QuantRiskCharacterization.SUBDUED,
            anomaly_detected=False,
            statistical_strength=0.75,
            conclusion="Normal volatility regime.",
            invalidation_conditions=["Volatility surge"],
            risks=["Fat tail"],
            assumptions=["Variance stability"],
            confidence=0.80,
        )))
        fund_spec = FundamentalSpecialist(llm_client=MockLLMClient(fixed_response=_FundamentalLLMResponse(
            fundamental_quality=FundamentalQuality.STRONG,
            growth_assessment=GrowthAssessment.HIGH_GROWTH,
            profitability_assessment=ProfitabilityAssessment.HIGHLY_PROFITABLE,
            balance_sheet_assessment=BalanceSheetAssessment.HEALTHY,
            financial_strength=0.85,
            conclusion="High margins and healthy balance sheet.",
            invalidation_conditions=["Margin drop"],
            risks=["Pricing pressure"],
            assumptions=["Enterprise demand holds"],
            confidence=0.85,
        )))

        outputs = [
            await tech_spec.execute(agent_input),
            await mom_spec.execute(agent_input),
            await quant_spec.execute(agent_input),
            await fund_spec.execute(agent_input),
        ]
        records = [
            AgentExecutionRecord(
                agent_name=out.agent_name,
                agent_version=out.version,
                context_id="ctx-e2e-calib-full-001",
                started_at=self.now,
                completed_at=self.now,
                status=out.status,
                duration_seconds=0.01,
                output=out,
            )
            for out in outputs
        ]
        run_result = SpecialistRunResult(
            run_id="run-e2e-calib-001",
            context_id="ctx-e2e-calib-full-001",
            symbol="TCS.NS",
            started_at=self.now,
            completed_at=self.now,
            duration_seconds=0.04,
            total_agents=4,
            successful_agents=4,
            failed_agents=0,
            timed_out_agents=0,
            degraded_agents=0,
            records=records,
            outputs=outputs,
        )

        # 2. Evidence Layer
        aggregator = EvidenceAggregator()
        evidence_summary = aggregator.aggregate_evidence(run_result, market_context=e2e_ctx)

        # 3. Debate Engine
        debate_engine = DebateEngine(llm_client=None)
        debate_result = await debate_engine.run_debate(evidence_summary, market_context=e2e_ctx)

        # 4. Investment Committee
        committee = InvestmentCommittee(llm_client=None)
        decision = await committee.synthesize_decision(evidence_summary, debate_result, market_context=e2e_ctx)
        self.assertEqual(decision.context_id, "ctx-e2e-calib-full-001")

        # 5. Conviction Calibration (Phase 6.5)
        calibrator = ConvictionCalibrator()
        calib_res = await calibrator.calibrate(decision, debate_result, evidence_summary, market_context=e2e_ctx)
        self.assertIsInstance(calib_res, ConvictionCalibrationResult)
        self.assertEqual(calib_res.context_id, "ctx-e2e-calib-full-001")
        self.assertEqual(calib_res.symbol, "TCS.NS")
        self.assertGreaterEqual(calib_res.calibrated_conviction, 0.0)
        self.assertLessEqual(calib_res.calibrated_conviction, 1.0)
        self.assertEqual(calib_res.calibration_version, "6.5.0")

        # 6. Risk Engine with Calibration Result (Phase 6.4 + 6.5)
        risk_engine = RiskEngine(config=RiskConfiguration(account_capital=200000.0, max_position_pct=0.25))
        
        # When decision is WATCH, verify safe flat positioning
        watch_plan = await risk_engine.evaluate_and_size(decision, market_context=e2e_ctx, calibration=calib_res)
        self.assertIsInstance(watch_plan, PositionSizingPlan)
        self.assertEqual(watch_plan.context_id, "ctx-e2e-calib-full-001")
        self.assertEqual(watch_plan.direction, PositionDirection.FLAT)
        self.assertTrue(watch_plan.veto_applied)

        # When committee decision is approved BUY, calibrate and size
        decision_approved = decision.model_copy(update={
            "recommendation": CommitteeRecommendation.BUY,
            "conviction_score": 0.85,
            "risk_score": 0.20,
            "risk_veto_applied": False,
        })
        calib_approved = await calibrator.calibrate(decision_approved, debate_result, evidence_summary, market_context=e2e_ctx)
        plan = await risk_engine.evaluate_and_size(decision_approved, market_context=e2e_ctx, calibration=calib_approved)

        self.assertIsInstance(plan, PositionSizingPlan)
        self.assertEqual(plan.context_id, "ctx-e2e-calib-full-001")
        self.assertEqual(plan.direction, PositionDirection.LONG)
        self.assertFalse(plan.veto_applied)
        self.assertGreater(plan.position_quantity, 0)
        self.assertEqual(plan.entry_price, 3500.0)
        self.assertGreater(plan.position_notional, 0.0)


if __name__ == "__main__":
    unittest.main()
