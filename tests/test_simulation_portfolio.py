"""
Unit tests for Simulation Portfolio & Slippage — Phase 5.2

Tests multi-symbol portfolio tracking, slippage models, and commission deductions.
"""

from datetime import datetime
import unittest

from backend.domain.execution_schemas import (
    ExecutionResult,
    OrderRequest,
    OrderSide,
    OrderStatus,
)
from backend.execution.paper_broker import PaperBroker
from backend.execution.portfolio import PaperPortfolio


class TestSimulationPortfolio(unittest.TestCase):
    def setUp(self):
        self.portfolio = PaperPortfolio(initial_cash=100000.0)
        self.broker = PaperBroker(
            initial_cash=100000.0,
            commission_rate=0.0003,  # 0.03%
            slippage_rate=0.0010,    # 0.10% (10 bps)
            portfolio=self.portfolio,
        )

    def test_buy_execution_applies_slippage_upwards(self):
        order = OrderRequest(
            order_id="ord-buy-slip",
            symbol="TCS.NS",
            side=OrderSide.BUY,
            quantity=5.0,
            price=3000.0,
            context_id="ctx-1",
        )
        res = self.broker.submit_order(order)
        self.assertEqual(res.status, OrderStatus.FILLED)
        # Expected fill price = 3000 * (1 + 0.0010) = 3003.0
        self.assertAlmostEqual(res.fill_price, 3003.0)
        self.assertEqual(res.quantity_filled, 5.0)

        # Cost = 5 * 3003.0 + commission
        expected_commission = 5.0 * 3003.0 * 0.0003
        self.assertAlmostEqual(res.commission, expected_commission)

        state = self.portfolio.get_state()
        self.assertAlmostEqual(state.positions["TCS.NS"].average_price, 3003.0)

    def test_sell_execution_applies_slippage_downwards(self):
        # 1. Fill buy at base price 3000 -> 3003
        buy_order = OrderRequest(
            order_id="ord-b1",
            symbol="TCS.NS",
            side=OrderSide.BUY,
            quantity=5.0,
            price=3000.0,
            context_id="ctx-1",
        )
        self.broker.submit_order(buy_order)

        # 2. Sell at requested 3500 -> Fill price = 3500 * (1 - 0.0010) = 3496.5
        sell_order = OrderRequest(
            order_id="ord-s1",
            symbol="TCS.NS",
            side=OrderSide.SELL,
            quantity=5.0,
            price=3500.0,
            context_id="ctx-2",
        )
        res_sell = self.broker.submit_order(sell_order)
        self.assertEqual(res_sell.status, OrderStatus.FILLED)
        self.assertAlmostEqual(res_sell.fill_price, 3496.5)

        # Realized PnL = (3496.5 - 3003.0) * 5 - sell_commission
        state = self.portfolio.get_state()
        expected_pnl = (3496.5 - 3003.0) * 5.0 - res_sell.commission
        self.assertAlmostEqual(state.realized_pnl, expected_pnl)

    def test_multi_symbol_portfolio_exposure(self):
        # Buy TCS 5 shares @ 3000 (~15k)
        self.broker.submit_order(
            OrderRequest(order_id="ord-tcs", symbol="TCS.NS", side=OrderSide.BUY, quantity=5.0, price=3000.0, context_id="c1")
        )
        # Buy INFY 10 shares @ 1500 (~15k)
        self.broker.submit_order(
            OrderRequest(order_id="ord-infy", symbol="INFY.NS", side=OrderSide.BUY, quantity=10.0, price=1500.0, context_id="c2")
        )

        state = self.portfolio.get_state()
        self.assertEqual(len(state.positions), 2)
        total_market_val = state.total_market_value
        self.assertGreater(total_market_val, 29000.0)
        self.assertAlmostEqual(state.total_exposure, total_market_val / state.total_equity)


if __name__ == "__main__":
    unittest.main()
