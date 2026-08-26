"""
Unit tests for PaperPortfolio — Phase 5.1
"""

from datetime import datetime
import unittest

from backend.domain.execution_schemas import (
    ExecutionResult,
    OrderSide,
    OrderStatus,
)
from backend.execution.portfolio import PaperPortfolio


class TestPaperPortfolio(unittest.TestCase):
    def setUp(self):
        self.portfolio = PaperPortfolio(initial_cash=100000.0)

    def test_initial_state(self):
        state = self.portfolio.get_state()
        self.assertEqual(state.initial_cash, 100000.0)
        self.assertEqual(state.cash, 100000.0)
        self.assertEqual(state.available_cash, 100000.0)
        self.assertEqual(state.total_market_value, 0.0)
        self.assertEqual(state.total_equity, 100000.0)
        self.assertEqual(state.realized_pnl, 0.0)
        self.assertEqual(state.unrealized_pnl, 0.0)
        self.assertEqual(state.total_exposure, 0.0)
        self.assertEqual(len(state.positions), 0)

    def test_buy_execution_adds_position(self):
        exec_res = ExecutionResult(
            execution_id="exec-1",
            order_id="ord-1",
            symbol="TCS.NS",
            side=OrderSide.BUY,
            quantity_requested=10.0,
            quantity_filled=10.0,
            fill_price=3500.0,
            status=OrderStatus.FILLED,
            total_cost=35000.0 + 10.5,
            commission=10.5,
            context_id="ctx-1",
        )
        self.portfolio.apply_execution(exec_res)
        state = self.portfolio.get_state()

        self.assertAlmostEqual(state.cash, 100000.0 - 35010.5)
        self.assertIn("TCS.NS", state.positions)
        pos = state.positions["TCS.NS"]
        self.assertEqual(pos.quantity, 10.0)
        self.assertEqual(pos.average_price, 3500.0)
        self.assertEqual(pos.current_price, 3500.0)
        self.assertEqual(pos.market_value, 35000.0)
        self.assertAlmostEqual(state.total_equity, 100000.0 - 10.5)  # Cash + stock - commission

    def test_multiple_buys_averages_price(self):
        # 1st buy: 10 shares @ 3000
        self.portfolio.apply_execution(
            ExecutionResult(
                execution_id="exec-1",
                order_id="ord-1",
                symbol="INFY.NS",
                side=OrderSide.BUY,
                quantity_requested=10.0,
                quantity_filled=10.0,
                fill_price=3000.0,
                status=OrderStatus.FILLED,
                total_cost=30000.0,
                commission=0.0,
                context_id="ctx-1",
            )
        )
        # 2nd buy: 10 shares @ 4000
        self.portfolio.apply_execution(
            ExecutionResult(
                execution_id="exec-2",
                order_id="ord-2",
                symbol="INFY.NS",
                side=OrderSide.BUY,
                quantity_requested=10.0,
                quantity_filled=10.0,
                fill_price=4000.0,
                status=OrderStatus.FILLED,
                total_cost=40000.0,
                commission=0.0,
                context_id="ctx-1",
            )
        )

        state = self.portfolio.get_state()
        pos = state.positions["INFY.NS"]
        self.assertEqual(pos.quantity, 20.0)
        self.assertEqual(pos.average_price, 3500.0)  # (30000 + 40000) / 20 = 3500
        self.assertEqual(pos.market_value, 20 * 4000.0)  # 80000

    def test_sell_execution_realizes_profit(self):
        # Buy 10 @ 1000
        self.portfolio.apply_execution(
            ExecutionResult(
                execution_id="exec-1",
                order_id="ord-1",
                symbol="RELIANCE.NS",
                side=OrderSide.BUY,
                quantity_requested=10.0,
                quantity_filled=10.0,
                fill_price=1000.0,
                status=OrderStatus.FILLED,
                total_cost=10000.0,
                commission=0.0,
                context_id="ctx-1",
            )
        )
        # Sell 5 @ 1200
        self.portfolio.apply_execution(
            ExecutionResult(
                execution_id="exec-2",
                order_id="ord-2",
                symbol="RELIANCE.NS",
                side=OrderSide.SELL,
                quantity_requested=5.0,
                quantity_filled=5.0,
                fill_price=1200.0,
                status=OrderStatus.FILLED,
                total_cost=6000.0,
                commission=0.0,
                context_id="ctx-1",
            )
        )

        state = self.portfolio.get_state()
        self.assertEqual(state.realized_pnl, 1000.0)  # (1200 - 1000) * 5
        self.assertEqual(state.daily_realized_pnl, 1000.0)
        self.assertIn("RELIANCE.NS", state.positions)
        self.assertEqual(state.positions["RELIANCE.NS"].quantity, 5.0)
        self.assertEqual(state.cash, 90000.0 + 6000.0)

    def test_sell_entire_position_removes_it(self):
        # Buy 10 @ 1000
        self.portfolio.apply_execution(
            ExecutionResult(
                execution_id="exec-1",
                order_id="ord-1",
                symbol="RELIANCE.NS",
                side=OrderSide.BUY,
                quantity_requested=10.0,
                quantity_filled=10.0,
                fill_price=1000.0,
                status=OrderStatus.FILLED,
                total_cost=10000.0,
                commission=0.0,
                context_id="ctx-1",
            )
        )
        # Sell 10 @ 1000
        self.portfolio.apply_execution(
            ExecutionResult(
                execution_id="exec-2",
                order_id="ord-2",
                symbol="RELIANCE.NS",
                side=OrderSide.SELL,
                quantity_requested=10.0,
                quantity_filled=10.0,
                fill_price=1000.0,
                status=OrderStatus.FILLED,
                total_cost=10000.0,
                commission=0.0,
                context_id="ctx-1",
            )
        )

        state = self.portfolio.get_state()
        self.assertNotIn("RELIANCE.NS", state.positions)
        self.assertEqual(state.cash, 100000.0)
        self.assertEqual(state.total_market_value, 0.0)

    def test_update_market_price_recalculates_unrealized_pnl(self):
        self.portfolio.apply_execution(
            ExecutionResult(
                execution_id="exec-1",
                order_id="ord-1",
                symbol="HDFCBANK.NS",
                side=OrderSide.BUY,
                quantity_requested=10.0,
                quantity_filled=10.0,
                fill_price=1500.0,
                status=OrderStatus.FILLED,
                total_cost=15000.0,
                commission=0.0,
                context_id="ctx-1",
            )
        )
        # Price increases to 1600
        self.portfolio.update_price("HDFCBANK.NS", 1600.0)
        state = self.portfolio.get_state()

        self.assertEqual(state.unrealized_pnl, 1000.0)  # (1600 - 1500) * 10
        self.assertEqual(state.total_market_value, 16000.0)
        self.assertEqual(state.total_equity, 85000.0 + 16000.0)
        self.assertAlmostEqual(state.total_exposure, 16000.0 / 101000.0)


if __name__ == "__main__":
    unittest.main()
