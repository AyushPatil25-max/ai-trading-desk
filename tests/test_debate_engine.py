import unittest
from datetime import datetime
import json
from unittest.mock import MagicMock, AsyncMock

from backend.domain.schemas import MarketContext, AgentInput, UnifiedEvidencePackage, AgentState, NormalizedEvidence, EvidenceCategory, SignalDirection
from backend.domain.debate_schemas import BullCase, BearCase, RiskAssessment, DebateDecisionState, DebateResult, EvidenceReference
from backend.infrastructure.llm import MockLLMClient, LLMClientError, LLMParseError
from backend.debate.bull_agent import BullAgent
from backend.debate.bear_agent import BearAgent
from backend.debate.risk_agent import RiskAgent
from backend.debate.debate_orchestrator import DebateOrchestrator

class TestDebateEngine(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ctx = MarketContext(context_id="test-ctx-123", symbol="AAPL", data_timestamp=datetime.utcnow(), current_price=150.0, provider="mock")
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


