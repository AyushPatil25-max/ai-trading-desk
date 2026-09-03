from copy import deepcopy
import unittest
from datetime import datetime, timezone
import json
from unittest.mock import MagicMock, AsyncMock

from backend.domain.schemas import (
    MarketContext, AgentInput, UnifiedEvidencePackage, AgentState, NormalizedEvidence,
    EvidenceCategory, SignalDirection, EvidenceSummary, EvidenceRecord, ContradictionRecord,
    ConflictSeverity, EvidenceType,
)
from backend.domain.debate_schemas import (
    BullCase, BearCase, RiskAssessment, DebateDecisionState, DebateResult, EvidenceReference,
    DebateArgument, DebateChallenge, DebateRebuttal, DebateRound, DebateSide,
    ChallengeSeverity, ChallengeStatus, ContradictionResolutionStatus, ContradictionAnalysis,
)
from backend.infrastructure.llm import MockLLMClient, LLMClientError, LLMParseError
from backend.debate.bull_agent import BullAgent
from backend.debate.bear_agent import BearAgent
from backend.debate.risk_agent import RiskAgent
from backend.debate.debate_orchestrator import DebateOrchestrator
from backend.application.debate_engine import (
    DebateEngine, RawArgumentsResponse, RawArgumentItem,
    RawChallengesResponse, RawChallengeItem,
    RawRebuttalsResponse, RawRebuttalItem,
)

class TestDebateEngine(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ctx = MarketContext(context_id="test-ctx-123", symbol="AAPL", data_timestamp=datetime.now(timezone.utc), current_price=150.0, provider="mock")
        self.evidence = UnifiedEvidencePackage(
            run_id="run-1",
            context_id="test-ctx-123",
            symbol="AAPL",
            data_timestamp=self.ctx.data_timestamp,
            total_evidence_extracted=5,
            evidence_items=[]
        )
        self.agent_input = AgentInput(
            symbol="AAPL",
            market_context=self.ctx,
            additional_data={"unified_evidence": self.evidence.model_dump()}
        )
        
        # Default mock responses
        self.bull_case = BullCase(thesis_id="bull-1", context_id="test-ctx-123", symbol="AAPL", core_thesis="Strong buy", confidence=0.8, evidence_references=[EvidenceReference(claim="ref1", category="FUNDAMENTAL", evidence_id="ev1")])
        self.bear_case = BearCase(thesis_id="bear-1", context_id="test-ctx-123", symbol="AAPL", attack_summary="Overvalued", confidence=0.7, evidence_references=[EvidenceReference(claim="ref1", category="VALUATION", evidence_id="ev2")])
        self.risk_assessment = RiskAssessment(context_id="test-ctx-123", symbol="AAPL", risk_level="MEDIUM", risk_score=0.4, risk_veto=False)

    def _get_valid_evidence(self):
        return NormalizedEvidence(
            evidence_id="1",
            specialist_name="test",
            metric_name="test",
            category=EvidenceCategory.FUNDAMENTAL,
            direction=SignalDirection.BULLISH,
            context_id="test-ctx-123",
            data_timestamp=self.ctx.data_timestamp
        )

    async def test_01_bull_execution_success(self):
        llm = MockLLMClient(fixed_response=self.bull_case)
        agent = BullAgent(llm)
        self.evidence.evidence_items.append(self._get_valid_evidence())
        self.agent_input.additional_data["unified_evidence"] = self.evidence.model_dump()
        output = await agent.execute(self.agent_input)
        self.assertEqual(output.status, AgentState.SUCCESS)
        
    async def test_02_bull_missing_evidence(self):
        # Empty evidence -> Degraded
        llm = MockLLMClient(fixed_response=self.bull_case)
        agent = BullAgent(llm)
        inp = AgentInput(symbol="AAPL", market_context=self.ctx, additional_data={"unified_evidence": self.evidence.model_dump()}) # empty items
        out = await agent.execute(inp)
        self.assertEqual(out.status, AgentState.DEGRADED)
        
    async def test_03_bull_llm_parse_error(self):
        llm = MockLLMClient(raise_error=LLMParseError("Bad JSON", "raw"))
        agent = BullAgent(llm)
        self.evidence.evidence_items.append(self._get_valid_evidence()) # Add fake evidence to bypass DEGRADED
        inp = AgentInput(symbol="AAPL", market_context=self.ctx, additional_data={"unified_evidence": self.evidence.model_dump()})
        out = await agent.execute(inp)
        self.assertEqual(out.status, AgentState.FAILED)
        self.assertEqual(out.error.code, "LLM_PARSE_ERROR")
        
    async def test_04_bull_llm_client_error(self):
        llm = MockLLMClient(raise_error=LLMClientError("500 API Error"))
        agent = BullAgent(llm)
        self.evidence.evidence_items.append(self._get_valid_evidence())
        inp = AgentInput(symbol="AAPL", market_context=self.ctx, additional_data={"unified_evidence": self.evidence.model_dump()})
        out = await agent.execute(inp)
        self.assertEqual(out.status, AgentState.FAILED)
        self.assertEqual(out.error.code, "LLM_CLIENT_ERROR")

    async def test_05_bear_execution_success(self):
        llm = MockLLMClient(fixed_response=self.bear_case)
        agent = BearAgent(llm)
        self.evidence.evidence_items.append(self._get_valid_evidence())
        inp = AgentInput(symbol="AAPL", market_context=self.ctx, additional_data={"unified_evidence": self.evidence.model_dump(), "bull_case": self.bull_case.model_dump()})
        out = await agent.execute(inp)
        self.assertEqual(out.status, AgentState.SUCCESS)

    async def test_06_bear_missing_bull_case(self):
        llm = MockLLMClient(fixed_response=self.bear_case)
        agent = BearAgent(llm)
        inp = AgentInput(symbol="AAPL", market_context=self.ctx, additional_data={"unified_evidence": self.evidence.model_dump()})
        out = await agent.execute(inp)
        self.assertEqual(out.status, AgentState.FAILED)
        self.assertEqual(out.error.code, "INVALID_INPUT")
        
    async def test_07_risk_execution_success(self):
        llm = MockLLMClient(fixed_response=self.risk_assessment)
        agent = RiskAgent(llm)
        inp = AgentInput(symbol="AAPL", market_context=self.ctx, additional_data={"unified_evidence": self.evidence.model_dump(), "bull_case": self.bull_case.model_dump(), "bear_case": self.bear_case.model_dump()})
        out = await agent.execute(inp)
        self.assertEqual(out.status, AgentState.SUCCESS)

    async def test_08_risk_missing_cases(self):
        llm = MockLLMClient(fixed_response=self.risk_assessment)
        agent = RiskAgent(llm)
        inp = AgentInput(symbol="AAPL", market_context=self.ctx, additional_data={"unified_evidence": self.evidence.model_dump()})
        out = await agent.execute(inp)
        self.assertEqual(out.status, AgentState.FAILED)

    async def test_09_orchestrator_success(self):
        bull_llm = MockLLMClient(fixed_response=self.bull_case)
        bear_llm = MockLLMClient(fixed_response=self.bear_case)
        risk_llm = MockLLMClient(fixed_response=self.risk_assessment)
        orch = DebateOrchestrator(BullAgent(bull_llm), BearAgent(bear_llm), RiskAgent(risk_llm))
        self.evidence.evidence_items.append(self._get_valid_evidence())
        result = await orch.run_debate(self.ctx, self.evidence)
        self.assertIsNotNone(result.bull_case)
        self.assertIsNotNone(result.bear_case)
        self.assertIsNotNone(result.risk_assessment)

    async def test_10_orchestrator_bull_failure(self):
        bull_llm = MockLLMClient(raise_error=LLMClientError("err"))
        bear_llm = MockLLMClient(fixed_response=self.bear_case)
        risk_llm = MockLLMClient(fixed_response=self.risk_assessment)
        orch = DebateOrchestrator(BullAgent(bull_llm), BearAgent(bear_llm), RiskAgent(risk_llm))
        self.evidence.evidence_items.append(self._get_valid_evidence())
        result = await orch.run_debate(self.ctx, self.evidence)
        self.assertEqual(result.thesis_status, DebateDecisionState.INSUFFICIENT_EVIDENCE)
        
    async def test_11_orchestrator_risk_veto(self):
        self.risk_assessment.risk_veto = True
        bull_llm = MockLLMClient(fixed_response=self.bull_case)
        bear_llm = MockLLMClient(fixed_response=self.bear_case)
        risk_llm = MockLLMClient(fixed_response=self.risk_assessment)
        orch = DebateOrchestrator(BullAgent(bull_llm), BearAgent(bear_llm), RiskAgent(risk_llm))
        self.evidence.evidence_items.append(self._get_valid_evidence())
        result = await orch.run_debate(self.ctx, self.evidence)
        self.assertEqual(result.thesis_status, DebateDecisionState.RISK_VETO)


# ===========================================================================
# Phase 6.2: Adversarial Debate Engine Comprehensive Offline Test Suite
# ===========================================================================

class TestPhase62AdversarialDebateEngine(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 29, 12, 0, 0)
        self.ctx = MarketContext(
            context_id="ctx-phase6-2-001",
            symbol="INFY.NS",
            data_timestamp=self.now,
            current_price=1800.0,
            provider="mock-vendor",
        )
        self.rec1 = EvidenceRecord(
            evidence_id="ev-tech-01",
            symbol="INFY.NS",
            context_id="ctx-phase6-2-001",
            specialist_name="TechnicalSpecialist",
            data_timestamp=self.now,
            evidence_type=EvidenceType.DETERMINISTIC_CALCULATION,
            claim="RSI is 62.5 indicating healthy upward momentum",
            value=62.5,
            unit="index",
            confidence=0.85,
            category=EvidenceCategory.TECHNICAL,
            direction=SignalDirection.BULLISH,
            metric_name="RSI",
            is_deterministic=True,
        )
        self.rec2 = EvidenceRecord(
            evidence_id="ev-mom-01",
            symbol="INFY.NS",
            context_id="ctx-phase6-2-001",
            specialist_name="MomentumSpecialist",
            data_timestamp=self.now,
            evidence_type=EvidenceType.DETERMINISTIC_CALCULATION,
            claim="Price is 1800.0 trading above EMA20 at 1750.0",
            value=1800.0,
            unit="INR",
            confidence=0.80,
            category=EvidenceCategory.MOMENTUM,
            direction=SignalDirection.BULLISH,
            metric_name="CURRENT_PRICE",
            is_deterministic=True,
        )
        self.rec3 = EvidenceRecord(
            evidence_id="ev-quant-01",
            symbol="INFY.NS",
            context_id="ctx-phase6-2-001",
            specialist_name="QuantSpecialist",
            data_timestamp=self.now,
            evidence_type=EvidenceType.DETERMINISTIC_CALCULATION,
            claim="Volatility percentile is elevated at 78.0",
            value=78.0,
            unit="%",
            confidence=0.75,
            category=EvidenceCategory.QUANT,
            direction=SignalDirection.BEARISH,
            metric_name="VOLATILITY_PERCENTILE",
            is_deterministic=True,
        )
        self.contra = ContradictionRecord(
            contradiction_id="contra-01",
            subject="DIRECTION:TechnicalSpecialist_VS_QuantSpecialist",
            specialist_a="TechnicalSpecialist",
            claim_a="Bullish trend above key moving averages",
            direction_a=SignalDirection.BULLISH,
            specialist_b="QuantSpecialist",
            claim_b="Elevated volatility indicating high reversal probability",
            direction_b=SignalDirection.BEARISH,
            severity=ConflictSeverity.HIGH,
            explanation="TechnicalSpecialist signals BULLISH while QuantSpecialist signals BEARISH",
        )
        self.summary = EvidenceSummary(
            run_id="run-p62-001",
            context_id="ctx-phase6-2-001",
            symbol="INFY.NS",
            total_evidence=3,
            valid_evidence=3,
            rejected_evidence=0,
            contradictions=[self.contra],
            evidence_records=[self.rec1, self.rec2, self.rec3],
        )

    # 1. Debate engine creation
    def test_01_debate_engine_creation(self):
        engine = DebateEngine(max_rounds=3, min_evidence_for_debate=2, timeout_seconds=45.0)
        self.assertEqual(engine.max_rounds, 3)
        self.assertEqual(engine.min_evidence_for_debate, 2)
        self.assertEqual(engine.timeout_seconds, 45.0)
        self.assertIsNone(engine.llm_client)

    # 2. Valid evidence intake
    async def test_02_valid_evidence_intake(self):
        engine = DebateEngine()
        result = await engine.run_debate(self.summary, self.ctx)
        self.assertIsInstance(result, DebateResult)
        self.assertEqual(result.symbol, "INFY.NS")
        self.assertEqual(result.context_id, "ctx-phase6-2-001")
        self.assertEqual(len(result.rounds), 1)
        self.assertGreater(len(result.strongest_bull_arguments), 0)
        self.assertGreater(len(result.strongest_bear_arguments), 0)

    # 3. Empty evidence
    async def test_03_empty_evidence(self):
        engine = DebateEngine()
        empty_summary = EvidenceSummary(
            run_id="run-empty",
            context_id="ctx-empty",
            symbol="EMPTY.NS",
            total_evidence=0,
            valid_evidence=0,
            rejected_evidence=0,
            evidence_records=[],
        )
        result = await engine.run_debate(empty_summary)
        self.assertEqual(result.final_debate_state, DebateDecisionState.INSUFFICIENT_EVIDENCE)
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.evidence_coverage, 0.0)

    # 4. Insufficient evidence
    async def test_04_insufficient_evidence(self):
        engine = DebateEngine(min_evidence_for_debate=5)
        result = await engine.run_debate(self.summary)
        self.assertEqual(result.final_debate_state, DebateDecisionState.INSUFFICIENT_EVIDENCE)
        self.assertEqual(result.confidence, 0.0)

    # 5. Bull argument generation
    async def test_05_bull_argument_generation(self):
        engine = DebateEngine()
        result = await engine.run_debate(self.summary)
        self.assertGreater(len(result.strongest_bull_arguments), 0)
        for arg in result.strongest_bull_arguments:
            self.assertEqual(arg.side, DebateSide.BULL)
            self.assertGreater(len(arg.supporting_evidence_ids), 0)
            self.assertFalse(arg.is_unsupported)

    # 6. Bear argument generation
    async def test_06_bear_argument_generation(self):
        engine = DebateEngine()
        result = await engine.run_debate(self.summary)
        self.assertGreater(len(result.strongest_bear_arguments), 0)
        for arg in result.strongest_bear_arguments:
            self.assertEqual(arg.side, DebateSide.BEAR)
            self.assertGreater(len(arg.supporting_evidence_ids), 0)
            self.assertFalse(arg.is_unsupported)

    # 7. Cross-examination
    async def test_07_cross_examination(self):
        engine = DebateEngine()
        result = await engine.run_debate(self.summary)
        challenges = result.rounds[0].challenges
        self.assertGreater(len(challenges), 0)
        for ch in challenges:
            self.assertTrue(len(ch.target_argument_id) > 0)
            self.assertIsInstance(ch.severity, ChallengeSeverity)

    # 8. Rebuttal
    async def test_08_rebuttal(self):
        engine = DebateEngine()
        result = await engine.run_debate(self.summary)
        rebuttals = result.rounds[0].rebuttals
        self.assertGreater(len(rebuttals), 0)
        for reb in rebuttals:
            self.assertTrue(len(reb.challenge_id) > 0)
            self.assertGreater(len(reb.supporting_evidence_ids), 0)

    # 9. Contradiction preservation
    async def test_09_contradiction_preservation(self):
        engine = DebateEngine()
        result = await engine.run_debate(self.summary)
        self.assertEqual(len(result.unresolved_contradictions), 1)
        self.assertEqual(result.unresolved_contradictions[0].contradiction_id, "contra-01")

    # 10. Resolved contradiction
    async def test_10_resolved_contradiction(self):
        fact_rec = EvidenceRecord(
            evidence_id="ev-fact-01",
            symbol="INFY.NS",
            context_id="ctx-phase6-2-001",
            specialist_name="NSEProvider",
            data_timestamp=self.now,
            evidence_type=EvidenceType.DETERMINISTIC_FACT,
            claim="Official close price is 1800.0",
            value=1800.0,
            is_deterministic=True,
        )
        interp_rec = EvidenceRecord(
            evidence_id="ev-interp-01",
            symbol="INFY.NS",
            context_id="ctx-phase6-2-001",
            specialist_name="ModelSpecialist",
            data_timestamp=self.now,
            evidence_type=EvidenceType.LLM_INTERPRETATION,
            claim="Estimated fair value price 1700.0",
            value=1700.0,
            is_deterministic=False,
        )
        resolvable_contra = ContradictionRecord(
            contradiction_id="contra-resolvable",
            subject="METRIC:PRICE",
            specialist_a="NSEProvider",
            claim_a="Official close 1800.0",
            specialist_b="ModelSpecialist",
            claim_b="Estimated price 1700.0",
            severity=ConflictSeverity.MODERATE,
            explanation="NSEProvider fact vs ModelSpecialist estimate",
        )
        summary = EvidenceSummary(
            run_id="run-res-01",
            context_id="ctx-phase6-2-001",
            symbol="INFY.NS",
            total_evidence=2,
            valid_evidence=2,
            contradictions=[resolvable_contra],
            evidence_records=[fact_rec, interp_rec],
        )
        engine = DebateEngine()
        result = await engine.run_debate(summary)
        self.assertEqual(len(result.unresolved_contradictions), 0)
        self.assertEqual(len(result.contradiction_analyses), 1)
        self.assertEqual(result.contradiction_analyses[0].status, ContradictionResolutionStatus.RESOLVED)

    # 11. Unresolved contradiction
    async def test_11_unresolved_contradiction(self):
        engine = DebateEngine()
        result = await engine.run_debate(self.summary)
        self.assertIn("contra-01", [c.contradiction_id for c in result.unresolved_contradictions])
        self.assertIn(ContradictionResolutionStatus.UNRESOLVED, [a.status for a in result.contradiction_analyses])

    # 12. Evidence ID enforcement
    async def test_12_evidence_id_enforcement(self):
        mock_llm = MockLLMClient(
            fixed_response=RawArgumentsResponse(
                arguments=[
                    RawArgumentItem(
                        claim="RSI at 62.5 indicates strength",
                        supporting_evidence_ids=["ev-tech-01"],
                        confidence=0.85,
                    )
                ]
            )
        )
        engine = DebateEngine(llm_client=mock_llm)
        result = await engine.run_debate(self.summary)
        bull_args = result.rounds[0].bull_arguments
        self.assertEqual(len(bull_args), 1)
        self.assertEqual(bull_args[0].supporting_evidence_ids, ["ev-tech-01"])
        self.assertFalse(bull_args[0].is_unsupported)

    # 13. Unsupported claim rejection
    async def test_13_unsupported_claim_rejection(self):
        mock_llm = MockLLMClient(
            fixed_response=RawArgumentsResponse(
                arguments=[
                    RawArgumentItem(
                        claim="Phantom argument without valid evidence citation",
                        supporting_evidence_ids=["ev-fake-999"],
                        confidence=0.9,
                    )
                ]
            )
        )
        engine = DebateEngine(llm_client=mock_llm)
        result = await engine.run_debate(self.summary)
        bull_args = result.rounds[0].bull_arguments
        self.assertEqual(len(bull_args), 1)
        self.assertTrue(bull_args[0].is_unsupported)
        self.assertEqual(bull_args[0].supporting_evidence_ids, [])

    # 14. Numerical integrity
    async def test_14_numerical_integrity(self):
        mock_llm = MockLLMClient(
            fixed_response=RawArgumentsResponse(
                arguments=[
                    RawArgumentItem(
                        claim="Manufactured profit margin of 9999.99 percent",
                        supporting_evidence_ids=["ev-tech-01"],
                        confidence=0.9,
                    )
                ]
            )
        )
        engine = DebateEngine(llm_client=mock_llm)
        result = await engine.run_debate(self.summary)
        bull_args = result.rounds[0].bull_arguments
        self.assertEqual(len(bull_args), 1)
        # Manufactured number not in ev-tech-01 (value=62.5) must be flagged unsupported
        self.assertTrue(bull_args[0].is_unsupported)

    # 15. Context ID propagation
    async def test_15_context_id_propagation(self):
        engine = DebateEngine()
        result = await engine.run_debate(self.summary, self.ctx)
        self.assertEqual(result.context_id, "ctx-phase6-2-001")
        self.assertEqual(result.symbol, "INFY.NS")
        self.assertEqual(result.run_id, "run-p62-001")
        if result.bull_case:
            self.assertEqual(result.bull_case.context_id, "ctx-phase6-2-001")
        if result.bear_case:
            self.assertEqual(result.bear_case.context_id, "ctx-phase6-2-001")

    # 16. Provenance preservation
    async def test_16_provenance_preservation(self):
        engine = DebateEngine()
        result = await engine.run_debate(self.summary)
        self.assertGreater(result.evidence_coverage, 0.0)
        self.assertIsNotNone(result.bull_case)
        self.assertGreater(len(result.bull_case.evidence_references), 0)

    # 17. Chain-of-thought rejection
    async def test_17_cot_rejection(self):
        mock_llm = MockLLMClient(
            fixed_response=RawArgumentsResponse(
                arguments=[
                    RawArgumentItem(
                        claim="<think>Step 1: Check moving averages</think> Thinking Process: Solid trend.",
                        supporting_evidence_ids=["ev-mom-01"],
                    )
                ]
            )
        )
        engine = DebateEngine(llm_client=mock_llm)
        result = await engine.run_debate(self.summary)
        claim = result.rounds[0].bull_arguments[0].claim
        self.assertNotIn("<think>", claim)
        self.assertNotIn("Thinking Process:", claim)

    # 18. LLM parse failure fallback
    async def test_18_llm_parse_failure(self):
        mock_llm = MockLLMClient(raise_error=LLMParseError("Bad JSON from LLM", "raw_text"))
        engine = DebateEngine(llm_client=mock_llm)
        result = await engine.run_debate(self.summary)
        self.assertIsInstance(result, DebateResult)
        self.assertGreater(len(result.strongest_bull_arguments), 0)
        self.assertGreater(len(result.strongest_bear_arguments), 0)

    # 19. LLM client failure fallback
    async def test_19_llm_client_failure(self):
        mock_llm = MockLLMClient(raise_error=LLMClientError("503 Service Unavailable"))
        engine = DebateEngine(llm_client=mock_llm)
        result = await engine.run_debate(self.summary)
        self.assertIsInstance(result, DebateResult)
        self.assertGreater(len(result.strongest_bull_arguments), 0)

    # 20. Timeout handling
    async def test_20_timeout_handling(self):
        engine = DebateEngine(timeout_seconds=0.00001)
        result = await engine.run_debate(self.summary)
        self.assertIsInstance(result, DebateResult)
        self.assertEqual(len(result.rounds), 1)

    # 21. Degraded specialist evidence
    async def test_21_degraded_specialist_evidence(self):
        degraded_rec = EvidenceRecord(
            evidence_id="ev-degraded-01",
            symbol="INFY.NS",
            context_id="ctx-phase6-2-001",
            specialist_name="FundamentalSpecialist",
            data_timestamp=self.now,
            evidence_type=EvidenceType.UNAVAILABLE,
            claim="Fundamental statements unavailable in DEGRADED mode",
            value=None,
            confidence=0.0,
            direction=SignalDirection.UNKNOWN,
            status=AgentState.DEGRADED,
        )
        summary = EvidenceSummary(
            run_id="run-deg",
            context_id="ctx-phase6-2-001",
            symbol="INFY.NS",
            total_evidence=4,
            valid_evidence=3,
            degraded_specialists=["FundamentalSpecialist"],
            evidence_records=[self.rec1, self.rec2, self.rec3, degraded_rec],
        )
        engine = DebateEngine()
        result = await engine.run_debate(summary)
        # Verify degraded evidence record with UNKNOWN direction was not turned into a bull argument
        bull_claims = [a.claim for a in result.strongest_bull_arguments]
        self.assertFalse(any("Fundamental statements unavailable" in c for c in bull_claims))

    # 22. Failed specialist evidence
    async def test_22_failed_specialist_evidence(self):
        summary = deepcopy(self.summary)
        summary.failed_specialists = ["NewsSpecialist"]
        engine = DebateEngine()
        result = await engine.run_debate(summary)
        self.assertIsInstance(result, DebateResult)
        self.assertGreater(len(result.strongest_bull_arguments), 0)

    # 23. Deterministic bookkeeping
    async def test_23_deterministic_bookkeeping(self):
        engine = DebateEngine()
        res1 = await engine.run_debate(self.summary)
        res2 = await engine.run_debate(self.summary)
        self.assertEqual(res1.evidence_coverage, res2.evidence_coverage)
        self.assertEqual(res1.bull_strength, res2.bull_strength)
        self.assertEqual(res1.bear_strength, res2.bear_strength)
        self.assertEqual(res1.confidence, res2.confidence)
        self.assertEqual(res1.final_debate_state, res2.final_debate_state)

    # 24. MarketContext immutability
    async def test_24_market_context_immutability(self):
        engine = DebateEngine()
        ctx_before = deepcopy(self.ctx.model_dump())
        _ = await engine.run_debate(self.summary, market_context=self.ctx)
        ctx_after = deepcopy(self.ctx.model_dump())
        self.assertEqual(ctx_before, ctx_after)

    # 25. Backward compatibility with legacy committee
    async def test_25_backward_compatibility(self):
        engine = DebateEngine()
        result = await engine.run_debate(self.summary)
        self.assertIsNotNone(result.bull_case)
        self.assertIsNotNone(result.bear_case)
        self.assertIsNotNone(result.risk_assessment)
        self.assertIsInstance(result.thesis_status, DebateDecisionState)
        self.assertIsInstance(result.bull_strength, float)
        self.assertIsInstance(result.bear_strength, float)
        self.assertIsInstance(result.risk_score, float)
        self.assertTrue(len(result.recommended_action) > 0)

    # 26. Complete multi-round debate flow
    async def test_26_complete_multi_round_debate_flow(self):
        engine = DebateEngine(max_rounds=2)
        result = await engine.run_debate(self.summary)
        self.assertEqual(len(result.rounds), 2)
        self.assertEqual(result.rounds[0].round_number, 1)
        self.assertEqual(result.rounds[1].round_number, 2)
        self.assertGreater(len(result.rounds[0].bull_arguments), 0)
        self.assertGreater(len(result.rounds[1].bull_arguments), 0)
        self.assertGreater(len(result.rounds[0].challenges), 0)
        self.assertGreater(len(result.rounds[0].rebuttals), 0)
        self.assertGreater(result.evidence_coverage, 0.0)


if __name__ == "__main__":
    unittest.main()



