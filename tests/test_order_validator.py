"""
Unit tests for OrderValidator — Phase 5.1
"""

from datetime import datetime, timedelta
import unittest

from backend.domain.execution_schemas import (
    ExecutionDecision,
    OrderRequest,
    OrderSide,
    OrderType,
    PortfolioState,
    Position,
    RejectionReason,
    RiskLimits,
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
from backend.domain.schemas import DataQualityStatus, MarketContext
from backend.execution.order_validator import OrderValidator


class TestOrderValidator(unittest.TestCase):
    def setUp(self):
        self.risk_limits = RiskLimits(
            max_position_value=50000.0,
            max_order_value=25000.0,
            max_portfolio_exposure=0.8,
            max_daily_loss=10000.0,
            max_single_symbol_exposure=0.3,
            max_orders_per_symbol=5,
            minimum_confidence=0.5,
            maximum_context_age_seconds=300.0,
        )
        self.validator = OrderValidator(risk_limits=self.risk_limits)
        self.portfolio_state = PortfolioState(
            portfolio_id="port-1",
            initial_cash=100000.0,
            cash=100000.0,
            available_cash=100000.0,
            positions={},
            total_market_value=0.0,
            total_equity=100000.0,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            total_exposure=0.0,
            daily_realized_pnl=0.0,
        )
        self.market_context = MarketContext(
            context_id="ctx-123",
            symbol="TCS.NS",
            data_timestamp=datetime.utcnow(),
            current_price=3500.0,
            provider="NSE",
        )
        self.decision = InvestmentDecision(
            decision_id="dec-1",
            context_id="ctx-123",
            symbol="TCS.NS",
            state=InvestmentDecisionState.APPROVE,
            thesis=InvestmentThesis(synthesis="Strong fundamentals"),
            execution_plan=ExecutionPlan(
                action=InvestmentAction.BUY,
                horizon=InvestmentHorizon.SWING,
                position_sizing=PositionSizing(is_available=True, recommended_size_pct=10.0),
            ),
            audit_trail=DecisionAudit(deterministic_state=InvestmentDecisionState.APPROVE),
            confidence=0.85,
        )

    def test_valid_order_passes(self):
        order = OrderRequest(
            order_id="ord-1",
            symbol="TCS.NS",
            side=OrderSide.BUY,
            quantity=5.0,
            price=3500.0,  # Value: 17500 <= 25000 max order value
            context_id="ctx-123",
        )
        res = self.validator.validate(
            order=order,
            portfolio_state=self.portfolio_state,
            market_context=self.market_context,
            decision=self.decision,
        )
        self.assertTrue(res.is_valid)
        self.assertEqual(res.decision, ExecutionDecision.ALLOWED)
        self.assertEqual(len(res.rejection_reasons), 0)

    def test_invalid_symbol(self):
        order = OrderRequest(
            order_id="ord-1",
            symbol="   ",
            side=OrderSide.BUY,
            quantity=5.0,
            price=100.0,
            context_id="ctx-123",
        )
        res = self.validator.validate(order=order, portfolio_state=self.portfolio_state)
        self.assertFalse(res.is_valid)
        self.assertEqual(res.decision, ExecutionDecision.BLOCKED)

    def test_zero_or_negative_quantity(self):
        with self.assertRaises(Exception):
            OrderRequest(
                order_id="ord-1",
                symbol="TCS.NS",
                side=OrderSide.BUY,
                quantity=0.0,
                price=100.0,
                context_id="ctx-123",
            )

    def test_context_id_mismatch(self):
        order = OrderRequest(
            order_id="ord-1",
            symbol="TCS.NS",
            side=OrderSide.BUY,
            quantity=5.0,
            price=3500.0,
            context_id="mismatched-ctx",
        )
        res = self.validator.validate(
            order=order,
            portfolio_state=self.portfolio_state,
            market_context=self.market_context,
        )
        self.assertFalse(res.is_valid)
        self.assertEqual(res.decision, ExecutionDecision.BLOCKED)

    def test_committee_risk_veto_blocks(self):
        self.decision.state = InvestmentDecisionState.RISK_VETO
        order = OrderRequest(
            order_id="ord-1",
            symbol="TCS.NS",
            side=OrderSide.BUY,
            quantity=5.0,
            price=3500.0,
            context_id="ctx-123",
        )
        res = self.validator.validate(
            order=order,
            portfolio_state=self.portfolio_state,
            decision=self.decision,
        )
        self.assertFalse(res.is_valid)
        self.assertEqual(res.decision, ExecutionDecision.BLOCKED)
        self.assertIn(RejectionReason.RISK_VETO, res.rejection_reasons)

    def test_committee_hold_or_reject_blocks(self):
        for state in [InvestmentDecisionState.HOLD, InvestmentDecisionState.REJECT]:
            self.decision.state = state
            order = OrderRequest(
                order_id="ord-1",
                symbol="TCS.NS",
                side=OrderSide.BUY,
                quantity=5.0,
                price=3500.0,
                context_id="ctx-123",
            )
            res = self.validator.validate(
                order=order,
                portfolio_state=self.portfolio_state,
                decision=self.decision,
            )
            self.assertFalse(res.is_valid)
            self.assertIn(RejectionReason.COMMITTEE_REJECT, res.rejection_reasons)

    def test_stale_market_context_requires_revalidation(self):
        stale_context = MarketContext(
            context_id="ctx-123",
            symbol="TCS.NS",
            data_timestamp=datetime.utcnow() - timedelta(seconds=400),  # > 300s limit
            current_price=3500.0,
            provider="NSE",
        )
        order = OrderRequest(
            order_id="ord-1",
            symbol="TCS.NS",
            side=OrderSide.BUY,
            quantity=5.0,
            price=3500.0,
            context_id="ctx-123",
        )
        res = self.validator.validate(
            order=order,
            portfolio_state=self.portfolio_state,
            market_context=stale_context,
            decision=self.decision,
        )
        self.assertFalse(res.is_valid)
        self.assertEqual(res.decision, ExecutionDecision.REQUIRES_REVALIDATION)
        self.assertIn(RejectionReason.STALE_DATA, res.rejection_reasons)

    def test_max_order_value_exceeded(self):
        # 10 shares @ 3500 = 35000 > max_order_value 25000
        order = OrderRequest(
            order_id="ord-1",
            symbol="TCS.NS",
            side=OrderSide.BUY,
            quantity=10.0,
            price=3500.0,
            context_id="ctx-123",
        )
        res = self.validator.validate(
            order=order,
            portfolio_state=self.portfolio_state,
            market_context=self.market_context,
            decision=self.decision,
        )
        self.assertFalse(res.is_valid)
        self.assertIn(RejectionReason.RISK_LIMIT, res.rejection_reasons)

    def test_insufficient_cash_for_buy(self):
        self.portfolio_state.available_cash = 1000.0
        order = OrderRequest(
            order_id="ord-1",
            symbol="TCS.NS",
            side=OrderSide.BUY,
            quantity=2.0,
            price=3500.0,  # 7000 > 1000
            context_id="ctx-123",
        )
        res = self.validator.validate(
            order=order,
            portfolio_state=self.portfolio_state,
            market_context=self.market_context,
            decision=self.decision,
        )
        self.assertFalse(res.is_valid)
        self.assertIn(RejectionReason.INSUFFICIENT_CASH, res.rejection_reasons)

    def test_insufficient_position_for_sell(self):
        order = OrderRequest(
            order_id="ord-1",
            symbol="TCS.NS",
            side=OrderSide.SELL,
            quantity=5.0,
            price=3500.0,
            context_id="ctx-123",
        )
        res = self.validator.validate(
            order=order,
            portfolio_state=self.portfolio_state,  # No existing position
            market_context=self.market_context,
        )
        self.assertFalse(res.is_valid)
        self.assertIn(RejectionReason.INSUFFICIENT_POSITION, res.rejection_reasons)

    def test_daily_loss_limit_breached(self):
        self.portfolio_state.daily_realized_pnl = -15000.0  # limit is 10000
        order = OrderRequest(
            order_id="ord-1",
            symbol="TCS.NS",
            side=OrderSide.BUY,
            quantity=1.0,
            price=3500.0,
            context_id="ctx-123",
        )
        res = self.validator.validate(
            order=order,
            portfolio_state=self.portfolio_state,
            market_context=self.market_context,
            decision=self.decision,
        )
        self.assertFalse(res.is_valid)
        self.assertIn(RejectionReason.DAILY_LOSS_LIMIT, res.rejection_reasons)


if __name__ == "__main__":
    unittest.main()
