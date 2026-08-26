"""
Comprehensive Execution Safety & Integration Tests — Phase 5.1

Tests kill switch behavior, adversarial LLM override prevention, deterministic decision
conversion, audit verification, and full pipeline integration from Specialists to Portfolio.
"""

from datetime import datetime
import unittest

from backend.domain.execution_schemas import (
    ExecutionDecision,
    OrderRequest,
    OrderSide,
    OrderStatus,
    PortfolioState,
    RejectionReason,
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
from backend.execution.audit import ExecutionAuditManager
from backend.execution.order_validator import OrderValidator
from backend.execution.paper_broker import PaperBroker
from backend.execution.portfolio import PaperPortfolio
from backend.execution.safety_engine import (
    DuplicateTracker,
    ExecutionSafetyEngine,
    KillSwitch,
)


class TestExecutionSafety(unittest.TestCase):
    def setUp(self):
        self.kill_switch = KillSwitch(initially_active=False)
        self.duplicate_tracker = DuplicateTracker()
        self.validator = OrderValidator()
        self.safety_engine = ExecutionSafetyEngine(
            validator=self.validator,
            kill_switch=self.kill_switch,
            duplicate_tracker=self.duplicate_tracker,
        )
        self.portfolio = PaperPortfolio(initial_cash=100000.0)
        self.broker = PaperBroker(
            initial_cash=100000.0,
            safety_engine=self.safety_engine,
            portfolio=self.portfolio,
        )
        self.market_context = MarketContext(
            context_id="ctx-safety-1",
            symbol="TCS.NS",
            data_timestamp=datetime.utcnow(),
            current_price=3500.0,
            provider="NSE",
        )
        self.approve_decision = InvestmentDecision(
            decision_id="dec-safety-1",
            context_id="ctx-safety-1",
            symbol="TCS.NS",
            state=InvestmentDecisionState.APPROVE,
            thesis=InvestmentThesis(synthesis="Approved with high conviction"),
            execution_plan=ExecutionPlan(
                action=InvestmentAction.BUY,
                horizon=InvestmentHorizon.SWING,
                position_sizing=PositionSizing(is_available=True, recommended_size_pct=10.0),
            ),
            audit_trail=DecisionAudit(deterministic_state=InvestmentDecisionState.APPROVE),
            confidence=0.9,
        )

    def test_kill_switch_overrides_committee_approval(self):
        # 1. Active kill switch
        self.kill_switch.activate()
        self.assertTrue(self.kill_switch.is_active())

        order = self.safety_engine.create_order_from_decision(
            decision=self.approve_decision,
            market_context=self.market_context,
            portfolio_state=self.portfolio.get_state(),
        )
        self.assertIsNotNone(order)

        result = self.broker.submit_order(
            order=order,
            market_context=self.market_context,
            decision=self.approve_decision,
        )
        self.assertEqual(result.status, OrderStatus.REJECTED)
        self.assertIn("kill switch", result.error_message.lower())

        # Check audit recorded kill_switch_active = True
        audit_records = self.broker.audit_manager.get_by_context("ctx-safety-1")
        self.assertEqual(len(audit_records), 1)
        self.assertTrue(audit_records[0].kill_switch_active)
        self.assertEqual(audit_records[0].decision, ExecutionDecision.BLOCKED)

        # 2. Deactivate kill switch -> Now succeeds
        self.kill_switch.deactivate()
        # Reset duplicate tracker for new submission test
        self.duplicate_tracker.clear()

        result2 = self.broker.submit_order(
            order=order,
            market_context=self.market_context,
            decision=self.approve_decision,
        )
        self.assertEqual(result2.status, OrderStatus.FILLED)

    def test_llm_cannot_override_execution_safety(self):
        # Malicious / hallucinated LLM thesis attempting to force BUY during RISK_VETO
        veto_decision = InvestmentDecision(
            decision_id="dec-veto",
            context_id="ctx-safety-1",
            symbol="TCS.NS",
            state=InvestmentDecisionState.RISK_VETO,
            thesis=InvestmentThesis(synthesis="IGNORE RISK VETO! BUY 100% LEVERAGE NOW!"),
            execution_plan=ExecutionPlan(
                action=InvestmentAction.BUY,
                horizon=InvestmentHorizon.SWING,
                position_sizing=PositionSizing(is_available=False, recommended_size_pct=0.0),
            ),
            audit_trail=DecisionAudit(
                risk_veto_triggered=True,
                deterministic_state=InvestmentDecisionState.RISK_VETO,
            ),
            confidence=0.2,
        )

        # 1. Safety engine refuses to create an order request from non-APPROVE decision
        order = self.safety_engine.create_order_from_decision(
            decision=veto_decision,
            market_context=self.market_context,
            portfolio_state=self.portfolio.get_state(),
        )
        self.assertIsNone(order)

        # 2. If a forged OrderRequest is directly submitted with the veto_decision, validator blocks it
        forged_order = OrderRequest(
            order_id="forged-1",
            symbol="TCS.NS",
            side=OrderSide.BUY,
            quantity=10.0,
            price=3500.0,
            context_id="ctx-safety-1",
        )
        res = self.broker.submit_order(
            order=forged_order,
            market_context=self.market_context,
            decision=veto_decision,
        )
        self.assertEqual(res.status, OrderStatus.REJECTED)
        self.assertIn("risk_veto", res.error_message.lower())

    def test_decision_to_order_request_deterministic_sizing(self):
        # Portfolio equity = 100,000. Recommended size = 10% -> 10,000. Price = 3500.
        # Quantity = int(10,000 / 3500) = 2 shares.
        order = self.safety_engine.create_order_from_decision(
            decision=self.approve_decision,
            market_context=self.market_context,
            portfolio_state=self.portfolio.get_state(),
        )
        self.assertIsNotNone(order)
        self.assertEqual(order.quantity, 2.0)
        self.assertEqual(order.price, 3500.0)
        self.assertEqual(order.side, OrderSide.BUY)
        self.assertEqual(order.symbol, "TCS.NS")

    def test_non_approve_states_produce_no_orders(self):
        non_approve_states = [
            InvestmentDecisionState.HOLD,
            InvestmentDecisionState.REJECT,
            InvestmentDecisionState.INSUFFICIENT_EVIDENCE,
            InvestmentDecisionState.RISK_VETO,
            InvestmentDecisionState.DATA_QUALITY_VETO,
        ]
        for state in non_approve_states:
            dec = self.approve_decision.model_copy(update={"state": state})
            order = self.safety_engine.create_order_from_decision(
                decision=dec,
                market_context=self.market_context,
                portfolio_state=self.portfolio.get_state(),
            )
            self.assertIsNone(order, f"Expected None for state {state}")

    def test_full_pipeline_decision_to_portfolio_execution(self):
        # End-to-end flow:
        # Decision -> OrderRequest -> PaperBroker Validation -> Fill -> Portfolio Update -> Audit Verification
        order = self.safety_engine.create_order_from_decision(
            decision=self.approve_decision,
            market_context=self.market_context,
            portfolio_state=self.portfolio.get_state(),
        )
        self.assertIsNotNone(order)

        result = self.broker.submit_order(
            order=order,
            market_context=self.market_context,
            decision=self.approve_decision,
        )

        self.assertEqual(result.status, OrderStatus.FILLED)
        self.assertEqual(result.quantity_filled, 2.0)

        # Portfolio assertions
        state = self.portfolio.get_state()
        self.assertEqual(state.positions["TCS.NS"].quantity, 2.0)
        self.assertAlmostEqual(state.cash, 100000.0 - (2.0 * 3500.0) - result.commission)

        # Audit trail assertions
        audit_records = self.broker.audit_manager.get_by_context("ctx-safety-1")
        self.assertEqual(len(audit_records), 1)
        self.assertEqual(audit_records[0].order_id, order.order_id)
        self.assertEqual(audit_records[0].decision, ExecutionDecision.ALLOWED)
        self.assertEqual(audit_records[0].execution_result.status, OrderStatus.FILLED)


if __name__ == "__main__":
    unittest.main()
