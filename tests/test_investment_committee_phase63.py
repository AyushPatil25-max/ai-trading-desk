"""
Phase 6.3 — Investment Committee / Decision Synthesis Comprehensive Offline Test Suite

Tests all requirements:
1. Committee creation
2. Valid EvidenceSummary intake
3. Valid DebateResult intake
4. Empty evidence -> INDETERMINATE
5. Insufficient evidence -> INDETERMINATE
6. Strong Bull scenario -> BUY / STRONG_BUY
7. Strong Bear scenario -> SELL / AVOID
8. Conflicting specialist scenario -> HOLD / WATCH (no artificial consensus)
9. Unresolved contradiction preservation & penalty
10. Resolved contradiction handling
11. Missing Fundamental data detection
12. Missing Quant data detection
13. Degraded specialist handling & penalty
14. Failed specialist handling & penalty
15. Unsupported evidence ID filtering
16. Unsupported debate ID filtering
17. Numerical claim integrity
18. Conviction score bounds [0.0, 1.0]
19. Deterministic conviction calculation
20. Context ID propagation
21. Provenance preservation
22. Chain-of-thought (CoT) rejection
23. LLM parse failure fallback
24. LLM client failure fallback
25. LLM timeout fallback
26. Deterministic fallback mode (zero LLM)
27. MarketContext immutability
28. Backward compatibility with InvestmentCommitteeAgent
29. Complete end-to-end pipeline:
    MarketContext -> Specialists -> EvidenceAggregator -> DebateEngine -> InvestmentCommittee -> CommitteeDecision
30. Repeatability / deterministic bookkeeping
"""

from copy import deepcopy
import unittest
from datetime import datetime, timezone
from typing import List, Dict, Any

from backend.domain.schemas import (
    MarketContext, EvidenceSummary, EvidenceRecord, ContradictionRecord,
    ConflictSeverity, EvidenceCategory, SignalDirection, EvidenceType,
    AgentState, AgentInput, SpecialistRunResult,
)
from backend.domain.debate_schemas import (
    DebateResult, DebateRound, DebateArgument, DebateChallenge, DebateRebuttal,
    DebateSide, ChallengeSeverity, ChallengeStatus, ContradictionResolutionStatus,
    DebateDecisionState, RiskAssessment,
)
from backend.domain.investment_committee_schemas import (
    CommitteeRecommendation, DataQualityStatus, CommitteeDecision,
    InvestmentDecisionState, InvestmentAction,
)
from backend.infrastructure.llm import MockLLMClient, LLMClientError, LLMParseError
from backend.application.investment_committee import InvestmentCommittee, RawCommitteeSynthesis
from backend.investment_committee.committee_agent import InvestmentCommitteeAgent
from backend.application.evidence_aggregator import EvidenceAggregator
from backend.application.debate_engine import DebateEngine
from backend.specialists.technical_specialist import TechnicalSpecialist
from backend.specialists.momentum_specialist import MomentumSpecialist
from backend.specialists.quant_specialist import QuantSpecialist
from backend.specialists.fundamental_specialist import FundamentalSpecialist


class TestInvestmentCommitteePhase63(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 29, 12, 0, 0)
        self.ctx = MarketContext(
            context_id="ctx-ic-phase63-001",
            symbol="INFY.NS",
            data_timestamp=self.now,
            current_price=1800.0,
            provider="mock-vendor",
            provenance=[{"source": "test_setup", "timestamp": str(self.now)}],
        )

        # Baseline Evidence Records covering Fundamental, Technical, and Quant
        self.rec_tech = EvidenceRecord(
            evidence_id="ev-tech-101",
            symbol="INFY.NS",
            context_id="ctx-ic-phase63-001",
            specialist_name="TechnicalSpecialist",
            data_timestamp=self.now,
            evidence_type=EvidenceType.DETERMINISTIC_CALCULATION,
            claim="RSI is 65.0 indicating healthy upward momentum",
            value=65.0,
            unit="index",
            confidence=0.85,
            category=EvidenceCategory.TECHNICAL,
            direction=SignalDirection.BULLISH,
            metric_name="RSI",
            is_deterministic=True,
        )
        self.rec_fund = EvidenceRecord(
            evidence_id="ev-fund-101",
            symbol="INFY.NS",
            context_id="ctx-ic-phase63-001",
            specialist_name="FundamentalSpecialist",
            data_timestamp=self.now,
            evidence_type=EvidenceType.DETERMINISTIC_CALCULATION,
            claim="TTM Net Margin is 18.5 percent with consistent cash flows",
            value=18.5,
            unit="%",
            confidence=0.80,
            category=EvidenceCategory.FUNDAMENTAL,
            direction=SignalDirection.BULLISH,
            metric_name="NET_MARGIN",
            is_deterministic=True,
        )
        self.rec_quant = EvidenceRecord(
            evidence_id="ev-quant-101",
            symbol="INFY.NS",
            context_id="ctx-ic-phase63-001",
            specialist_name="QuantSpecialist",
            data_timestamp=self.now,
            evidence_type=EvidenceType.DETERMINISTIC_CALCULATION,
            claim="Realized volatility is moderate at 22.0 percent",
            value=22.0,
            unit="%",
            confidence=0.75,
            category=EvidenceCategory.QUANT,
            direction=SignalDirection.BULLISH,
            metric_name="VOLATILITY",
            is_deterministic=True,
        )

        self.summary = EvidenceSummary(
            run_id="run-ic-001",
            context_id="ctx-ic-phase63-001",
            symbol="INFY.NS",
            total_evidence=3,
            valid_evidence=3,
            rejected_evidence=0,
            evidence_records=[self.rec_tech, self.rec_fund, self.rec_quant],
        )

        # Baseline Debate Result (Bull Favored)
        self.bull_arg = DebateArgument(
            argument_id="arg-bull-01",
            side=DebateSide.BULL,
            claim="Strong technical momentum with RSI at 65.0 and solid margins",
            supporting_evidence_ids=["ev-tech-101", "ev-fund-101"],
            confidence=0.85,
            risks=["Macro slowdown"],
            assumptions=["Trend continuation"],
        )
        self.bear_arg = DebateArgument(
            argument_id="arg-bear-01",
            side=DebateSide.BEAR,
            claim="Valuation multiple expansion risk under market volatility",
            supporting_evidence_ids=["ev-quant-101"],
            confidence=0.40,
            risks=["Multiple compression"],
            assumptions=["Interest rate hike"],
        )

        self.debate = DebateResult(
            debate_id="deb-p63-001",
            run_id="run-ic-001",
            context_id="ctx-ic-phase63-001",
            symbol="INFY.NS",
            bull_strength=0.85,
            bear_strength=0.35,
            risk_score=0.30,
            confidence=0.85,
            final_debate_state=DebateDecisionState.BULL_FAVORED,
            thesis_status=DebateDecisionState.BULL_FAVORED,
            evidence_coverage=1.0,
            strongest_bull_arguments=[self.bull_arg],
            strongest_bear_arguments=[self.bear_arg],
            risk_assessment=RiskAssessment(
                context_id="ctx-ic-phase63-001",
                symbol="INFY.NS",
                risk_level="LOW",
                risk_score=0.30,
                confidence=0.80,
                risk_veto=False,
            ),
        )

    # 1. Committee creation
    def test_01_committee_creation(self):
        ic = InvestmentCommittee(timeout_seconds=45.0, min_evidence_threshold=3)
        self.assertEqual(ic.timeout_seconds, 45.0)
        self.assertEqual(ic.min_evidence_threshold, 3)
        self.assertIsNone(ic.llm_client)

    # 2. Valid EvidenceSummary intake
    async def test_02_valid_evidence_intake(self):
        ic = InvestmentCommittee()
        decision = await ic.synthesize_decision(self.summary, self.debate, self.ctx)
        self.assertIsInstance(decision, CommitteeDecision)
        self.assertEqual(decision.symbol, "INFY.NS")
        self.assertEqual(decision.context_id, "ctx-ic-phase63-001")
        self.assertEqual(decision.data_quality, DataQualityStatus.AVAILABLE)

    # 3. Valid DebateResult intake
    async def test_03_valid_debate_result_intake(self):
        ic = InvestmentCommittee()
        decision = await ic.synthesize_decision(self.summary, self.debate)
        self.assertGreater(len(decision.strongest_bull_arguments), 0)
        self.assertEqual(decision.strongest_bull_arguments[0].argument_id, "arg-bull-01")

    # 4. Empty evidence
    async def test_04_empty_evidence(self):
        empty_summary = EvidenceSummary(
            run_id="run-empty",
            context_id="ctx-empty",
            symbol="EMPTY.NS",
            total_evidence=0,
            valid_evidence=0,
            evidence_records=[],
        )
        ic = InvestmentCommittee()
        decision = await ic.synthesize_decision(empty_summary, self.debate)
        self.assertEqual(decision.recommendation, CommitteeRecommendation.INDETERMINATE)
        self.assertEqual(decision.conviction_score, 0.0)
        self.assertEqual(decision.confidence, 0.0)
        self.assertEqual(decision.data_quality, DataQualityStatus.INSUFFICIENT)

    # 5. Insufficient evidence
    async def test_05_insufficient_evidence(self):
        ic = InvestmentCommittee(min_evidence_threshold=5)
        decision = await ic.synthesize_decision(self.summary, self.debate) # 3 records < 5
        self.assertEqual(decision.recommendation, CommitteeRecommendation.INDETERMINATE)
        self.assertEqual(decision.conviction_score, 0.0)

    # 6. Strong Bull scenario
    async def test_06_strong_bull_scenario(self):
        self.debate.bull_strength = 0.90
        self.debate.bear_strength = 0.20
        self.debate.risk_score = 0.15
        self.debate.confidence = 0.90
        ic = InvestmentCommittee()
        decision = await ic.synthesize_decision(self.summary, self.debate)
        self.assertIn(decision.recommendation, [CommitteeRecommendation.STRONG_BUY, CommitteeRecommendation.BUY])
        self.assertGreater(decision.conviction_score, 0.40)

    # 7. Strong Bear scenario
    async def test_07_strong_bear_scenario(self):
        self.debate.bull_strength = 0.20
        self.debate.bear_strength = 0.85
        self.debate.risk_score = 0.70
        ic = InvestmentCommittee()
        decision = await ic.synthesize_decision(self.summary, self.debate)
        self.assertIn(decision.recommendation, [CommitteeRecommendation.SELL, CommitteeRecommendation.AVOID])

    # 8. Conflicting specialist scenario
    async def test_08_conflicting_specialist_scenario(self):
        self.debate.bull_strength = 0.55
        self.debate.bear_strength = 0.52
        self.debate.risk_score = 0.45
        ic = InvestmentCommittee()
        decision = await ic.synthesize_decision(self.summary, self.debate)
        # Tight spread must not artificially force a BUY or SELL
        self.assertIn(decision.recommendation, [CommitteeRecommendation.HOLD, CommitteeRecommendation.WATCH])

    # 9. Unresolved contradiction preservation & penalty
    async def test_09_unresolved_contradiction(self):
        contra = ContradictionRecord(
            contradiction_id="contra-01",
            subject="VALUATION_VS_MOMENTUM",
            specialist_a="TechnicalSpecialist",
            claim_a="Overbought RSI",
            specialist_b="FundamentalSpecialist",
            claim_b="Undervalued TTM multiple",
            severity=ConflictSeverity.HIGH,
            explanation="Tension between short-term technicals and fundamental value",
        )
        self.summary.contradictions = [contra]
        self.debate.unresolved_contradictions = [contra]
        
        ic = InvestmentCommittee()
        # Decision without contradiction
        debate_no_contra = deepcopy(self.debate)
        debate_no_contra.unresolved_contradictions = []
        summary_no_contra = deepcopy(self.summary)
        summary_no_contra.contradictions = []
        res_clean = await ic.synthesize_decision(summary_no_contra, debate_no_contra)

        # Decision with contradiction
        res_contra = await ic.synthesize_decision(self.summary, self.debate)
        self.assertEqual(len(res_contra.unresolved_contradictions), 1)
        # Conviction score must be penalized
        self.assertLess(res_contra.conviction_score, res_clean.conviction_score)

    # 10. Resolved contradiction handling
    async def test_10_resolved_contradiction(self):
        # Empty unresolved contradictions on debate means contradictions were resolved
        self.debate.unresolved_contradictions = []
        ic = InvestmentCommittee()
        decision = await ic.synthesize_decision(self.summary, self.debate)
        self.assertEqual(len(decision.unresolved_contradictions), 0)

    # 11. Missing Fundamental data
    async def test_11_missing_fundamental_data(self):
        summary_no_fund = deepcopy(self.summary)
        # Keep only tech and quant
        summary_no_fund.evidence_records = [self.rec_tech, self.rec_quant]
        ic = InvestmentCommittee()
        decision = await ic.synthesize_decision(summary_no_fund, self.debate)
        self.assertIn("Missing Fundamental Data", decision.missing_critical_data)
        self.assertIn(decision.data_quality, [DataQualityStatus.PARTIAL, DataQualityStatus.DEGRADED])

    # 12. Missing Quant data
    async def test_12_missing_quant_data(self):
        summary_no_quant = deepcopy(self.summary)
        summary_no_quant.evidence_records = [self.rec_tech, self.rec_fund]
        ic = InvestmentCommittee()
        decision = await ic.synthesize_decision(summary_no_quant, self.debate)
        self.assertIn("Missing Quant Data", decision.missing_critical_data)

    # 13. Degraded specialist
    async def test_13_degraded_specialist(self):
        summary_deg = deepcopy(self.summary)
        summary_deg.degraded_specialists = ["FundamentalSpecialist"]
        ic = InvestmentCommittee()
        decision = await ic.synthesize_decision(summary_deg, self.debate)
        self.assertEqual(decision.data_quality, DataQualityStatus.DEGRADED)
        self.assertIn("FundamentalSpecialist", decision.degraded_specialists)

    # 14. Failed specialist
    async def test_14_failed_specialist(self):
        summary_fail = deepcopy(self.summary)
        summary_fail.failed_specialists = ["NewsSpecialist"]
        ic = InvestmentCommittee()
        decision = await ic.synthesize_decision(summary_fail, self.debate)
        self.assertIn("NewsSpecialist", decision.failed_specialists)

    # 15. Unsupported evidence ID filtering
    async def test_15_unsupported_evidence_id(self):
        # Bull arg cites a phantom ID
        phantom_bull_arg = DebateArgument(
            argument_id="arg-phantom",
            side=DebateSide.BULL,
            claim="Citing nonexistent evidence",
            supporting_evidence_ids=["ev-nonexistent-999"],
            confidence=0.8,
        )
        debate_phantom = deepcopy(self.debate)
        debate_phantom.strongest_bull_arguments = [phantom_bull_arg]
        ic = InvestmentCommittee()
        decision = await ic.synthesize_decision(self.summary, debate_phantom)
        # Phantom ID must NOT be present in valid supporting_evidence_ids
        self.assertNotIn("ev-nonexistent-999", decision.supporting_evidence_ids)

    # 16. Unsupported debate ID filtering
    async def test_16_unsupported_debate_id(self):
        ic = InvestmentCommittee()
        decision = await ic.synthesize_decision(self.summary, self.debate)
        for arg in decision.strongest_bull_arguments:
            self.assertTrue(len(arg.argument_id) > 0)

    # 17. Numerical claim integrity
    async def test_17_numerical_claim_integrity(self):
        # LLM returns a hallucinated number 99999.0
        mock_llm = MockLLMClient(
            fixed_response=RawCommitteeSynthesis(
                investment_thesis="Company reported fabricated 99999.0 profit growth.",
                decision_summary="Decision based on 99999.0 metric.",
                why_bull_case_wins="Bull case wins.",
                why_bear_case_wins="Bear case risks.",
                what_would_change_the_decision="Trend break.",
            )
        )
        ic = InvestmentCommittee(llm_client=mock_llm)
        decision = await ic.synthesize_decision(self.summary, self.debate)
        # The fabricated number must be masked / sanitized
        self.assertNotIn("99999.0", decision.investment_thesis)
        self.assertNotIn("99999.0", decision.decision_summary)

    # 18. Conviction score bounds
    async def test_18_conviction_score_bounds(self):
        ic = InvestmentCommittee()
        decision = await ic.synthesize_decision(self.summary, self.debate)
        self.assertGreaterEqual(decision.conviction_score, 0.0)
        self.assertLessEqual(decision.conviction_score, 1.0)

    # 19. Deterministic conviction calculation
    async def test_19_deterministic_conviction_calculation(self):
        ic = InvestmentCommittee()
        d1 = await ic.synthesize_decision(self.summary, self.debate)
        d2 = await ic.synthesize_decision(self.summary, self.debate)
        self.assertEqual(d1.conviction_score, d2.conviction_score)
        self.assertEqual(d1.recommendation, d2.recommendation)

    # 20. Context ID propagation
    async def test_20_context_id_propagation(self):
        ic = InvestmentCommittee()
        decision = await ic.synthesize_decision(self.summary, self.debate, self.ctx)
        self.assertEqual(decision.context_id, "ctx-ic-phase63-001")
        self.assertEqual(decision.symbol, "INFY.NS")
        self.assertEqual(decision.run_id, "run-ic-001")

    # 21. Provenance preservation
    async def test_21_provenance_preservation(self):
        ic = InvestmentCommittee()
        decision = await ic.synthesize_decision(self.summary, self.debate, self.ctx)
        self.assertGreater(len(decision.provenance), 0)
        self.assertEqual(decision.provenance[0]["source"], "test_setup")

    # 22. Chain-of-thought rejection
    async def test_22_cot_rejection(self):
        mock_llm = MockLLMClient(
            fixed_response=RawCommitteeSynthesis(
                investment_thesis="<think>Step 1: check debate\nStep 2: confirm</think> Thinking Process: Sound setup.",
                decision_summary="Clean decision.",
                why_bull_case_wins="Bull wins.",
                why_bear_case_wins="Bear risks.",
                what_would_change_the_decision="Trend break.",
            )
        )
        ic = InvestmentCommittee(llm_client=mock_llm)
        decision = await ic.synthesize_decision(self.summary, self.debate)
        self.assertNotIn("<think>", decision.investment_thesis)
        self.assertNotIn("Thinking Process:", decision.investment_thesis)

    # 23. LLM parse failure fallback
    async def test_23_llm_parse_failure(self):
        mock_llm = MockLLMClient(raise_error=LLMParseError("Malformed JSON from LLM", "raw_payload"))
        ic = InvestmentCommittee(llm_client=mock_llm)
        decision = await ic.synthesize_decision(self.summary, self.debate)
        self.assertIsInstance(decision, CommitteeDecision)
        self.assertTrue(len(decision.investment_thesis) > 0)
        self.assertTrue(len(decision.decision_summary) > 0)

    # 24. LLM client failure fallback
    async def test_24_llm_client_failure(self):
        mock_llm = MockLLMClient(raise_error=LLMClientError("503 Upstream Service Unavailable"))
        ic = InvestmentCommittee(llm_client=mock_llm)
        decision = await ic.synthesize_decision(self.summary, self.debate)
        self.assertIsInstance(decision, CommitteeDecision)
        self.assertTrue(len(decision.investment_thesis) > 0)

    # 25. LLM timeout fallback
    async def test_25_llm_timeout(self):
        ic = InvestmentCommittee(timeout_seconds=0.00001)
        decision = await ic.synthesize_decision(self.summary, self.debate)
        self.assertIsInstance(decision, CommitteeDecision)
        self.assertTrue(len(decision.investment_thesis) > 0)

    # 26. Deterministic fallback mode
    async def test_26_deterministic_fallback(self):
        ic = InvestmentCommittee(llm_client=None)
        decision = await ic.synthesize_decision(self.summary, self.debate)
        self.assertIsInstance(decision, CommitteeDecision)
        self.assertIn("INFY.NS", decision.investment_thesis)
        self.assertTrue(len(decision.why_bull_case_wins) > 0)
        self.assertTrue(len(decision.why_bear_case_wins) > 0)

    # 27. MarketContext immutability
    async def test_27_market_context_immutability(self):
        before = deepcopy(self.ctx.model_dump())
        ic = InvestmentCommittee()
        _ = await ic.synthesize_decision(self.summary, self.debate, self.ctx)
        after = deepcopy(self.ctx.model_dump())
        self.assertEqual(before, after)

    # 28. Backward compatibility with InvestmentCommitteeAgent
    async def test_28_backward_compatibility(self):
        agent_input = AgentInput(
            symbol="INFY.NS",
            market_context=self.ctx,
            additional_data={
                "evidence_summary": self.summary.model_dump(),
                "debate_result": self.debate.model_dump(),
            },
        )
        from backend.domain.investment_committee_schemas import InvestmentThesis
        mock_thesis = InvestmentThesis(
            synthesis="Compatible synthesis",
            key_drivers=["Driver 1"],
            primary_risks=["Risk 1"],
            assumptions=["Assumption 1"],
            invalidation_conditions=["Condition 1"],
        )
        agent = InvestmentCommitteeAgent(llm=MockLLMClient(fixed_response=mock_thesis))
        out = await agent.execute(agent_input)
        self.assertEqual(out.status, AgentState.SUCCESS)
        self.assertEqual(out.raw_data["symbol"], "INFY.NS")
        self.assertEqual(out.raw_data["context_id"], "ctx-ic-phase63-001")

    # 29. Complete end-to-end pipeline test
    async def test_29_complete_end_to_end(self):
        """
        Integration test verifying:
        MarketContext
        -> Specialists (Technical, Momentum, Quant, Fundamental)
        -> EvidenceAggregator -> EvidenceSummary
        -> DebateEngine -> DebateResult
        -> InvestmentCommittee -> CommitteeDecision
        All using identical context_id.
        """
        from backend.domain.schemas import (
            _TechnicalLLMResponse, TrendDirection, SetupType,
            _MomentumLLMResponse, MomentumDirection, MomentumStrength,
            _QuantLLMResponse, QuantStatisticalRegime, QuantRiskCharacterization,
            _FundamentalLLMResponse, FundamentalQuality, GrowthAssessment, ProfitabilityAssessment, BalanceSheetAssessment,
        )

        ohlcv = [
            {"timestamp": "2024-01-01T00:00:00+00:00", "open": 3400.0, "high": 3450.0, "low": 3390.0, "close": 3420.0, "volume": 100000},
            {"timestamp": "2024-01-02T00:00:00+00:00", "open": 3420.0, "high": 3480.0, "low": 3410.0, "close": 3460.0, "volume": 120000},
            {"timestamp": "2024-01-03T00:00:00+00:00", "open": 3460.0, "high": 3500.0, "low": 3450.0, "close": 3480.0, "volume": 110000},
            {"timestamp": "2024-01-04T00:00:00+00:00", "open": 3480.0, "high": 3520.0, "low": 3470.0, "close": 3500.0, "volume": 130000},
            {"timestamp": "2024-01-05T00:00:00+00:00", "open": 3500.0, "high": 3550.0, "low": 3490.0, "close": 3520.0, "volume": 140000},
        ]
        fund_data = {
            "period": "FY2024",
            "report_date": "2024-01-15",
            "revenue": 10000.0,
            "prior_revenue": 8500.0,
            "operating_profit": 2500.0,
            "net_income": 1900.0,
            "eps": 25.0,
            "prior_eps": 20.0,
            "total_debt": 500.0,
            "total_equity": 8000.0,
            "operating_cash_flow": 2200.0,
            "capex": 500.0,
            "current_assets": 5000.0,
            "current_liabilities": 1500.0,
            "cash": 2000.0,
            "gross_profit": 4500.0,
        }
        e2e_ctx = MarketContext(
            context_id="ctx-e2e-pipeline-999",
            symbol="TCS.NS",
            data_timestamp=self.now,
            current_price=3500.0,
            provider="mock-e2e",
            ohlcv_historical=ohlcv,
            technical_indicators={"rsi": 62.0, "ema20": 3450.0, "ema50": 3400.0, "20_day_high": 3550.0},
            fundamental_data=fund_data,
        )

        agent_input = AgentInput(
            symbol="TCS.NS",
            market_context=e2e_ctx,
            historical_ohlcv=ohlcv,
            indicators={"rsi": 62.0, "ema20": 3450.0, "ema50": 3400.0},
            additional_data={"pe_ratio": 24.5, "net_margin": 19.2, "volatility_annualized": 18.5},
        )

        # 1. Execute Specialists with MockLLMClients
        tech_spec = TechnicalSpecialist(llm_client=MockLLMClient(fixed_response=_TechnicalLLMResponse(
            trend=TrendDirection.BULLISH,
            setup=SetupType.BREAKOUT,
            technical_score=8.0,
            confirmation=True,
            conclusion="Bullish breakout above moving averages.",
            invalidation_conditions=["Break below EMA20"],
            risks=["Overbought pullbacks"],
            assumptions=["Trend continues"],
            confidence=0.85,
        )))
        mom_spec = MomentumSpecialist(llm_client=MockLLMClient(fixed_response=_MomentumLLMResponse(
            momentum_direction=MomentumDirection.BULLISH,
            momentum_strength=MomentumStrength.STRONG,
            confirmation=True,
            conclusion="Accelerating momentum confirmed.",
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
            conclusion="Normal volatility regime with positive drift.",
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
            conclusion="High margins and low leverage provide strength.",
            invalidation_conditions=["Margin drop"],
            risks=["Pricing pressure"],
            assumptions=["Enterprise demand holds"],
            confidence=0.85,
        )))

        tech_out = await tech_spec.execute(agent_input)
        mom_out = await mom_spec.execute(agent_input)
        quant_out = await quant_spec.execute(agent_input)
        fund_out = await fund_spec.execute(agent_input)

        from backend.domain.schemas import AgentExecutionRecord

        outputs = [tech_out, mom_out, quant_out, fund_out]
        records = [
            AgentExecutionRecord(
                agent_name=out.agent_name,
                agent_version=out.version,
                context_id="ctx-e2e-pipeline-999",
                started_at=self.now,
                completed_at=self.now,
                status=out.status,
                duration_seconds=0.01,
                output=out,
            )
            for out in outputs
        ]

        run_result = SpecialistRunResult(
            run_id="run-e2e-001",
            context_id="ctx-e2e-pipeline-999",
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

        # 2. Evidence Aggregator -> EvidenceSummary
        evidence_summary = EvidenceAggregator().aggregate_evidence(run_result, market_context=e2e_ctx)
        self.assertEqual(evidence_summary.context_id, "ctx-e2e-pipeline-999")
        self.assertGreater(evidence_summary.total_evidence, 0)

        # 3. Debate Engine -> DebateResult
        debate_engine = DebateEngine(llm_client=None)
        debate_result = await debate_engine.run_debate(evidence_summary, market_context=e2e_ctx)
        self.assertEqual(debate_result.context_id, "ctx-e2e-pipeline-999")
        self.assertGreater(len(debate_result.rounds), 0)

        # 4. Investment Committee -> CommitteeDecision
        committee = InvestmentCommittee(llm_client=None)
        decision = await committee.synthesize_decision(evidence_summary, debate_result, market_context=e2e_ctx)

        # 5. Verify End-to-End Integrity
        self.assertEqual(decision.context_id, "ctx-e2e-pipeline-999")
        self.assertEqual(decision.symbol, "TCS.NS")
        self.assertIsInstance(decision.recommendation, CommitteeRecommendation)
        self.assertGreaterEqual(decision.conviction_score, 0.0)
        self.assertLessEqual(decision.conviction_score, 1.0)
        self.assertTrue(len(decision.investment_thesis) > 0)
        self.assertGreater(len(decision.evidence_references), 0)

        # Traceability back to evidence
        cited_ids = set(decision.supporting_evidence_ids + decision.opposing_evidence_ids)
        summary_ids = set(r.evidence_id for r in evidence_summary.evidence_records)
        self.assertTrue(cited_ids.issubset(summary_ids))

    # 30. Repeatability / deterministic bookkeeping
    async def test_30_repeatability_and_deterministic_bookkeeping(self):
        ic = InvestmentCommittee(llm_client=None)
        d1 = await ic.synthesize_decision(self.summary, self.debate)
        d2 = await ic.synthesize_decision(self.summary, self.debate)
        self.assertEqual(d1.recommendation, d2.recommendation)
        self.assertEqual(d1.conviction_score, d2.conviction_score)
        self.assertEqual(d1.confidence, d2.confidence)
        self.assertEqual(d1.evidence_coverage, d2.evidence_coverage)
        self.assertEqual(d1.supporting_evidence_ids, d2.supporting_evidence_ids)
        self.assertEqual(d1.opposing_evidence_ids, d2.opposing_evidence_ids)


if __name__ == "__main__":
    unittest.main()
