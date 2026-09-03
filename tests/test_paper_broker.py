"""
Unit tests for PaperBroker — Phase 5.1
"""

from datetime import datetime, timezone
import unittest

from backend.domain.execution_schemas import (
    OrderRequest,
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
from backend.execution.paper_broker import PaperBroker


class TestPaperBroker(unittest.TestCase):
    def setUp(self):
        self.broker = PaperBroker(initial_cash=100000.0)
        self.market_context = MarketContext(
            context_id="ctx-paper-1",
            symbol="TCS.NS",
            data_timestamp=datetime.now(timezone.utc),
            current_price=3500.0,
            provider="NSE",
        )
        self.decision = InvestmentDecision(
            decision_id="dec-1",
            context_id="ctx-paper-1",
            symbol="TCS.NS",
            state=InvestmentDecisionState.APPROVE,
            thesis=InvestmentThesis(synthesis="Approved"),
            execution_plan=ExecutionPlan(
                action=InvestmentAction.BUY,
                horizon=InvestmentHorizon.SWING,
                position_sizing=PositionSizing(is_available=True, recommended_size_pct=10.0),
            ),
            audit_trail=DecisionAudit(deterministic_state=InvestmentDecisionState.APPROVE),
            confidence=0.8,
        )

    def test_submit_valid_buy_order_fills_and_updates_portfolio(self):
        order = OrderRequest(
            order_id="ord-buy-1",
            symbol="TCS.NS",
            side=OrderSide.BUY,
            quantity=5.0,
            price=3500.0,
            context_id="ctx-paper-1",
            run_id="run-1",
        )
        result = self.broker.submit_order(
            order=order,
            market_context=self.market_context,
            decision=self.decision,
        )
        self.assertEqual(result.status, OrderStatus.FILLED)
        self.assertEqual(result.quantity_filled, 5.0)
        self.assertEqual(result.fill_price, 3500.0)

        # Check portfolio
        state = self.broker.get_account_state()
        self.assertIn("TCS.NS", state.positions)
        self.assertEqual(state.positions["TCS.NS"].quantity, 5.0)
        self.assertAlmostEqual(state.cash, 100000.0 - (5.0 * 3500.0) - result.commission)

        # Check audit
        records = self.broker.audit_manager.get_by_context("ctx-paper-1")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].order_id, "ord-buy-1")
        self.assertEqual(records[0].context_id, "ctx-paper-1")
        self.assertEqual(records[0].run_id, "run-1")

    def test_duplicate_order_rejected(self):
        order1 = OrderRequest(
            order_id="ord-1",
            symbol="TCS.NS",
            side=OrderSide.BUY,
            quantity=5.0,
            price=3500.0,
            context_id="ctx-paper-1",
            run_id="run-dup",
        )
        res1 = self.broker.submit_order(order=order1, market_context=self.market_context, decision=self.decision)
        self.assertEqual(res1.status, OrderStatus.FILLED)

        # Same decision/order parameters submitted second time
        order2 = OrderRequest(
            order_id="ord-2",
            symbol="TCS.NS",
            side=OrderSide.BUY,
            quantity=5.0,
            price=3500.0,
            context_id="ctx-paper-1",
            run_id="run-dup",
        )
        res2 = self.broker.submit_order(order=order2, market_context=self.market_context, decision=self.decision)
        self.assertEqual(res2.status, OrderStatus.REJECTED)
        self.assertIn("duplicate", res2.error_message.lower())

    def test_submit_valid_sell_order_after_buy(self):
        # 1. Buy 10 @ 1000
        buy_order = OrderRequest(
            order_id="ord-b1",
            symbol="INFY.NS",
            side=OrderSide.BUY,
            quantity=10.0,
            price=1000.0,
            context_id="ctx-paper-1",
        )
        ctx = MarketContext(
            context_id="ctx-paper-1",
            symbol="INFY.NS",
            data_timestamp=datetime.now(timezone.utc),
            current_price=1000.0,
            provider="NSE",
        )
        dec = self.decision.model_copy(update={"symbol": "INFY.NS"})
        self.broker.submit_order(order=buy_order, market_context=ctx, decision=dec)

        # 2. Sell 5 @ 1200
        sell_order = OrderRequest(
            order_id="ord-s1",
            symbol="INFY.NS",
            side=OrderSide.SELL,
            quantity=5.0,
            price=1200.0,
            context_id="ctx-paper-1",
        )
        res_sell = self.broker.submit_order(order=sell_order, market_context=ctx)
        self.assertEqual(res_sell.status, OrderStatus.FILLED)

        state = self.broker.get_account_state()
        self.assertEqual(state.positions["INFY.NS"].quantity, 5.0)
        self.assertGreater(state.realized_pnl, 900.0)  # ~1000 minus small commission

    def test_insufficient_cash_rejected(self):
        # Initial cash is 100,000. Try to buy 100 shares @ 3500 = 350,000
        order = OrderRequest(
            order_id="ord-huge",
            symbol="TCS.NS",
            side=OrderSide.BUY,
            quantity=100.0,
            price=3500.0,
            context_id="ctx-paper-1",
        )
        res = self.broker.submit_order(order=order, market_context=self.market_context, decision=self.decision)
        self.assertEqual(res.status, OrderStatus.REJECTED)

        # Portfolio state remains untouched
        state = self.broker.get_account_state()
        self.assertEqual(state.cash, 100000.0)
        self.assertEqual(len(state.positions), 0)


if __name__ == "__main__":
    unittest.main()
