"""
End-to-End Simulation Integration Tests — Phase 5.2

Validates full Trading Desk simulation pipeline from Specialists to Simulation Report and API endpoints.
"""

from datetime import datetime
import unittest

from backend.debate.bear_agent import BearAgent
from backend.debate.bull_agent import BullAgent
from backend.debate.debate_orchestrator import DebateOrchestrator
from backend.debate.risk_agent import RiskAgent
from backend.domain.debate_schemas import BearCase, BullCase, EvidenceReference, RiskAssessment
from backend.domain.execution_schemas import (
    ExecutionDecision,
    OrderSide,
    OrderStatus,
)
from backend.domain.investment_committee_schemas import (
    DecisionAudit,
    ExecutionPlan,
    InvestmentAction,
    InvestmentDecision,
    InvestmentDecisionState,
    InvestmentHorizon,
    InvestmentThesis,
    PositionSizing,
)
from backend.domain.schemas import MarketContext
from backend.infrastructure.llm import MockLLMClient
from backend.investment_committee.committee_agent import InvestmentCommitteeAgent
from backend.simulation.replay_engine import HistoricalReplayEngine
from backend.simulation.simulation_config import SimulationConfig


class TestSimulationIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = SimulationConfig(
            simulation_id="sim-integration-1",
            initial_cash=100000.0,
            symbols=["TCS.NS"],
            commission_rate=0.0003,
            slippage_rate=0.0005,
        )

        # Mock LLM for Bull/Bear/Risk/Committee
        bull_mock = BullCase(
            thesis_id="b-1",
            context_id="ctx-1",
            symbol="TCS.NS",
            core_thesis="Strong Long Thesis",
            confidence=0.85,
            evidence_references=[EvidenceReference(evidence_id="e1", category="TECH", claim="EMA golden cross")],
        )
        bear_mock = BearCase(
            thesis_id="be-1",
            context_id="ctx-1",
            symbol="TCS.NS",
            attack_summary="Valuation slightly high",
            confidence=0.4,
            evidence_references=[],
        )
        risk_mock = RiskAssessment(
            context_id="ctx-1",
            symbol="TCS.NS",
            risk_level="LOW",
            risk_score=0.2,
            confidence=0.8,
            risk_veto=False,
        )
        thesis_mock = InvestmentThesis(
            synthesis="Approved based on strong consensus",
            key_drivers=["Earnings growth"],
        )

        self.bull_agent = BullAgent(MockLLMClient(fixed_response=bull_mock))
        self.bear_agent = BearAgent(MockLLMClient(fixed_response=bear_mock))
        self.risk_agent = RiskAgent(MockLLMClient(fixed_response=risk_mock))
        self.debate_orchestrator = DebateOrchestrator(
            bull_agent=self.bull_agent,
            bear_agent=self.bear_agent,
            risk_agent=self.risk_agent,
        )
        self.committee_agent = InvestmentCommitteeAgent(
            llm=MockLLMClient(fixed_response=thesis_mock)
        )

        self.engine = HistoricalReplayEngine(
            config=self.config,
            debate_orchestrator=self.debate_orchestrator,
            committee_agent=self.committee_agent,
        )

        self.t0 = datetime(2024, 1, 1, 10, 0, 0)
        self.t1 = datetime(2024, 1, 2, 10, 0, 0)

        self.dataset = {
            "TCS.NS": {
                "current_price": 3000.0,
                "ohlcv_historical": [
                    {"timestamp": "2024-01-01 10:00:00", "close": 3000.0},
                    {"timestamp": "2024-01-02 10:00:00", "close": 3200.0},
                ],
                "fundamental_data": {"pe": 25.0},
                "news_data": {},
                "institutional_data": [],
            }
        }

    async def test_full_pipeline_produces_valid_report_and_provenance(self):
        report = await self.engine.run(self.dataset)

        self.assertEqual(report.simulation_id, "sim-integration-1")
        self.assertEqual(len(report.equity_curve), 2)
        self.assertGreater(report.final_capital, 0.0)

        # Provenance check: Decision journal must have context_id and equity
        self.assertGreater(len(report.decision_journal), 0)
        d0 = report.decision_journal[0]
        self.assertEqual(d0.symbol, "TCS.NS")
        self.assertTrue(d0.context_id.startswith("pit-"))

    async def test_api_router_execution(self):
        from backend.simulation.routes import run_simulation, get_simulation_report
        res_report = await run_simulation(self.config)
        self.assertIsNotNone(res_report)
        self.assertEqual(res_report.simulation_id, self.config.simulation_id)

        queried_report = await get_simulation_report(self.config.simulation_id)
        self.assertEqual(queried_report.simulation_id, self.config.simulation_id)


if __name__ == "__main__":
    unittest.main()
