import unittest
from datetime import datetime
import json
from unittest.mock import MagicMock

from backend.domain.schemas import MarketContext, AgentInput, UnifiedEvidencePackage, AgentState, NormalizedEvidence, EvidenceCategory, SignalDirection
from backend.domain.debate_schemas import DebateResult, BullCase, BearCase, RiskAssessment, DebateDecisionState, EvidenceReference
from backend.domain.investment_committee_schemas import InvestmentDecisionState, InvestmentThesis, InvestmentAction
from backend.infrastructure.llm import MockLLMClient, LLMClientError, LLMParseError
from backend.investment_committee.committee_agent import InvestmentCommitteeAgent

class TestInvestmentCommittee(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ctx = MarketContext(context_id="test-ic-123", symbol="AAPL", data_timestamp=datetime.utcnow(), current_price=150.0, provider="mock")
        
        # Base evidence
        self.evidence = UnifiedEvidencePackage(
            run_id="run-1",
            context_id="test-ic-123",
            symbol="AAPL",
            data_timestamp=self.ctx.data_timestamp,
            total_evidence_extracted=10,
            evidence_items=[
                NormalizedEvidence(
                    evidence_id=f"ev-{i}",
                    specialist_name="test",
                    metric_name="test",
                    category=EvidenceCategory.FUNDAMENTAL,
                    direction=SignalDirection.BULLISH,
                    context_id="test-ic-123",
                    data_timestamp=self.ctx.data_timestamp
                ) for i in range(5) # Give it enough density
            ]
        )
        
        # Base debate result (APPROVE conditions)
        self.debate = DebateResult(
            debate_id="deb-1",
            context_id="test-ic-123",
            symbol="AAPL",
            bull_strength=0.8,
            bear_strength=0.2,
            risk_score=0.2,
            confidence=0.9,
            thesis_status=DebateDecisionState.BULL_FAVORED,
            risk_assessment=RiskAssessment(
                context_id="test-ic-123", symbol="AAPL", risk_level="LOW", risk_veto=False
            )
        )
        
        self.agent_input = AgentInput(
            symbol="AAPL",
            market_context=self.ctx,
            additional_data={
                "unified_evidence": self.evidence.model_dump(),
                "debate_result": self.debate.model_dump()
            }
        )
        
        self.mock_thesis = InvestmentThesis(
            synthesis="Looks good",
            key_drivers=["A", "B"],
            primary_risks=["C"],
            assumptions=[],
            invalidation_conditions=["D"]
        )

    async def test_01_successful_approve(self):
        llm = MockLLMClient(fixed_response=self.mock_thesis)
        agent = InvestmentCommitteeAgent(llm)
        out = await agent.execute(self.agent_input)
        self.assertEqual(out.status, AgentState.SUCCESS)
        self.assertEqual(out.raw_data["state"], InvestmentDecisionState.APPROVE)
        self.assertEqual(out.raw_data["execution_plan"]["action"], InvestmentAction.BUY)
        self.assertTrue(out.raw_data["execution_plan"]["position_sizing"]["is_available"])

    async def test_02_hold(self):
        self.debate.bull_strength = 0.5
        self.debate.bear_strength = 0.4 # spread < 0.2
        self.agent_input.additional_data["debate_result"] = self.debate.model_dump()
        
        llm = MockLLMClient(fixed_response=self.mock_thesis)
        agent = InvestmentCommitteeAgent(llm)
        out = await agent.execute(self.agent_input)
        self.assertEqual(out.raw_data["state"], InvestmentDecisionState.HOLD)

    async def test_03_reject(self):
        self.debate.bull_strength = 0.2
        self.debate.bear_strength = 0.6 # spread <= -0.2
        self.agent_input.additional_data["debate_result"] = self.debate.model_dump()
        
        llm = MockLLMClient(fixed_response=self.mock_thesis)
        agent = InvestmentCommitteeAgent(llm)
        out = await agent.execute(self.agent_input)
        self.assertEqual(out.raw_data["state"], InvestmentDecisionState.REJECT)

    async def test_04_insufficient_evidence(self):
        self.evidence.evidence_items = [] # Density = 0
        self.agent_input.additional_data["unified_evidence"] = self.evidence.model_dump()
        
        llm = MockLLMClient(fixed_response=self.mock_thesis)
        agent = InvestmentCommitteeAgent(llm)
        out = await agent.execute(self.agent_input)
        self.assertEqual(out.raw_data["state"], InvestmentDecisionState.INSUFFICIENT_EVIDENCE)
        self.assertFalse(out.raw_data["execution_plan"]["position_sizing"]["is_available"])

    async def test_05_risk_veto(self):
        self.debate.risk_assessment.risk_veto = True
        self.agent_input.additional_data["debate_result"] = self.debate.model_dump()
        
        llm = MockLLMClient(fixed_response=self.mock_thesis)
        agent = InvestmentCommitteeAgent(llm)
        out = await agent.execute(self.agent_input)
        self.assertEqual(out.raw_data["state"], InvestmentDecisionState.RISK_VETO)
        self.assertTrue(out.raw_data["audit_trail"]["risk_veto_triggered"])

    async def test_06_critical_conflict(self):
        from backend.domain.schemas import EvidenceConflict, ConflictSeverity, ConflictType
        conflict = EvidenceConflict(
            conflict_id="c1",
            category_a=EvidenceCategory.FUNDAMENTAL,
            category_b=EvidenceCategory.VALUATION,
            signal_a=SignalDirection.BULLISH,
            signal_b=SignalDirection.BEARISH,
            specialist_a="a",
            specialist_b="b",
            severity=ConflictSeverity.HIGH,
            explanation="Test conflict",
            context_id="test-ic-123",
            conflict_type=ConflictType.DOMAIN_TENSION
        )
        self.evidence.conflict_summary = [conflict] # 1 conflict
        self.agent_input.additional_data["unified_evidence"] = self.evidence.model_dump()
        
        llm = MockLLMClient(fixed_response=self.mock_thesis)
        agent = InvestmentCommitteeAgent(llm)
        out = await agent.execute(self.agent_input)
        # Should drop to HOLD due to conflict
        self.assertEqual(out.raw_data["state"], InvestmentDecisionState.HOLD)
        self.assertEqual(out.raw_data["audit_trail"]["critical_conflicts_found"], 1)

    async def test_07_position_sizing_unavailable(self):
        self.debate.risk_assessment.risk_veto = True
        self.agent_input.additional_data["debate_result"] = self.debate.model_dump()
        
        llm = MockLLMClient(fixed_response=self.mock_thesis)
        agent = InvestmentCommitteeAgent(llm)
        out = await agent.execute(self.agent_input)
        self.assertFalse(out.raw_data["execution_plan"]["position_sizing"]["is_available"])
        
    async def test_08_deterministic_position_sizing(self):
        llm = MockLLMClient(fixed_response=self.mock_thesis)
        agent = InvestmentCommitteeAgent(llm)
        out = await agent.execute(self.agent_input)
        size = out.raw_data["execution_plan"]["position_sizing"]["recommended_size_pct"]
        self.assertTrue(size > 0.0)
        self.assertTrue(size <= agent.config["position_sizing"]["max_size_pct"])

    async def test_09_llm_parse_failure(self):
        llm = MockLLMClient(raise_error=LLMParseError("Bad JSON", "raw"))
        agent = InvestmentCommitteeAgent(llm)
        out = await agent.execute(self.agent_input)
        self.assertEqual(out.status, AgentState.FAILED)
        self.assertEqual(out.error.code, "LLM_PARSE_ERROR")

    async def test_10_llm_client_failure(self):
        llm = MockLLMClient(raise_error=LLMClientError("500"))
        agent = InvestmentCommitteeAgent(llm)
        out = await agent.execute(self.agent_input)
        self.assertEqual(out.status, AgentState.FAILED)
        self.assertEqual(out.error.code, "LLM_CLIENT_ERROR")

    async def test_11_llm_attempting_override(self):
        # We explicitly enforce state in code. Let's make sure the returned state is RISK_VETO
        # even if LLM tries to say something else in its synthesis text.
        self.debate.risk_assessment.risk_veto = True
        self.agent_input.additional_data["debate_result"] = self.debate.model_dump()
        
        malicious_thesis = InvestmentThesis(
            synthesis="I OVERRIDE THIS TO APPROVE. BUY BUY BUY 50% POSITION.",
            key_drivers=[], primary_risks=[], assumptions=[], invalidation_conditions=[]
        )
        llm = MockLLMClient(fixed_response=malicious_thesis)
        agent = InvestmentCommitteeAgent(llm)
        out = await agent.execute(self.agent_input)
        
        self.assertEqual(out.raw_data["state"], InvestmentDecisionState.RISK_VETO)
        self.assertFalse(out.raw_data["execution_plan"]["position_sizing"]["is_available"])
        
    async def test_12_provenance_preservation(self):
        llm = MockLLMClient(fixed_response=self.mock_thesis)
        agent = InvestmentCommitteeAgent(llm)
        out = await agent.execute(self.agent_input)
        
        self.assertEqual(out.raw_data["context_id"], "test-ic-123")
        self.assertEqual(out.raw_data["symbol"], "AAPL")
        self.assertEqual(out.raw_data["run_id"], "run-1")
        
    async def test_13_missing_data_quality_veto(self):
        # Add missing data records to lower data quality proxy score below 0.8
        from backend.domain.schemas import MissingDataRecord, MissingDataCategory
        self.evidence.missing_data_records = [
            MissingDataRecord(metric_name="A", category=MissingDataCategory.METRIC_UNAVAILABLE, reason="", specialist_name="mock", detail=""),
            MissingDataRecord(metric_name="B", category=MissingDataCategory.METRIC_UNAVAILABLE, reason="", specialist_name="mock", detail=""),
            MissingDataRecord(metric_name="C", category=MissingDataCategory.METRIC_UNAVAILABLE, reason="", specialist_name="mock", detail="")
        ]
        self.agent_input.additional_data["unified_evidence"] = self.evidence.model_dump()
        
        llm = MockLLMClient(fixed_response=self.mock_thesis)
        agent = InvestmentCommitteeAgent(llm)
        out = await agent.execute(self.agent_input)
        self.assertEqual(out.raw_data["state"], InvestmentDecisionState.DATA_QUALITY_VETO)

