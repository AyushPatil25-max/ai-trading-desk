"""
Unit tests for LLM Adversarial Safety & Risk Gate Precedence — Phase 5.6

Validates that LLM qualitative output cannot override deterministic risk limits,
kill switch signals, or position sizing caps.
"""

import unittest

from backend.domain.execution_schemas import (
    ExecutionDecision,
    OrderRequest,
    OrderSide,
    PortfolioState,
    Position,
)
from backend.domain.investment_committee_schemas import InvestmentDecisionState
from backend.execution.safety_engine import ExecutionSafetyEngine


class TestLLMAdversarialSafety(unittest.TestCase):
    def setUp(self):
        self.safety_engine = ExecutionSafetyEngine()
        self.portfolio_state = PortfolioState(
            portfolio_id="port-safe-001",
            initial_cash=100000.0,
            cash=100000.0,
            available_cash=100000.0,
            total_equity=100000.0,
            positions={},
        )

    def test_llm_approval_cannot_override_oversized_order_risk_block(self):
        # Order requests 50% of portfolio (limit is 10%)
        order = OrderRequest(
            order_id="ord-adv-001",
            symbol="TCS.NS",
            side=OrderSide.BUY,
            quantity=15.0,
            price=3500.0,  # 52,500 INR > 10% limit
            context_id="ctx-adv",
            committee_decision_state=InvestmentDecisionState.APPROVE,
            confidence=0.99,  # High LLM confidence
        )
        res = self.safety_engine.evaluate_order(order, self.portfolio_state)
        # Deterministic risk engine must block regardless of LLM confidence
        self.assertEqual(res.decision, ExecutionDecision.BLOCKED)
        self.assertGreater(len(res.rejection_details), 0)


if __name__ == "__main__":
    unittest.main()
