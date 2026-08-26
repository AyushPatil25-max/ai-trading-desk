"""
Unit tests for Simulation Performance Engine — Phase 5.2

Tests mathematical correctness, Sharpe/Sortino guards, drawdowns, win rates, and benchmark comparisons.
"""

from datetime import datetime, timedelta
import unittest

from backend.domain.execution_schemas import (
    ExecutionDecision,
    OrderSide,
    OrderStatus,
)
from backend.domain.investment_committee_schemas import (
    InvestmentDecisionState,
)
from backend.simulation.performance import PerformanceEngine
from backend.simulation.simulation_state import (
    EquityCurvePoint,
    TradeJournalEntry,
)


class TestSimulationPerformance(unittest.TestCase):
    def setUp(self):
        self.engine = PerformanceEngine(risk_free_rate=0.05)
        self.t0 = datetime(2024, 1, 1)

    def test_total_return_and_benchmark_comparison(self):
        # 100k -> 110k (10% strategy return). Benchmark 20k -> 21k (5% benchmark return).
        # Excess return = 10% - 5% = +5%
        curve = [
            EquityCurvePoint(
                timestamp=self.t0,
                portfolio_value=100000.0,
                cash=100000.0,
                daily_return=0.0,
            ),
            EquityCurvePoint(
                timestamp=self.t0 + timedelta(days=1),
                portfolio_value=110000.0,
                cash=110000.0,
                daily_return=0.10,
            ),
        ]
        metrics = self.engine.calculate_metrics(
            initial_capital=100000.0,
            equity_curve=curve,
            trade_journal=[],
            benchmark_initial=20000.0,
            benchmark_final=21000.0,
        )
        self.assertEqual(metrics.total_return_pct, 10.0)
        self.assertEqual(metrics.benchmark_return_pct, 5.0)
        self.assertEqual(metrics.excess_return_pct, 5.0)

    def test_max_drawdown_calculation(self):
        # Peak = 120k, drops to 90k -> Drawdown amount = 30k, Drawdown pct = 25%
        curve = [
            EquityCurvePoint(timestamp=self.t0, portfolio_value=100000.0, cash=100000.0, drawdown=0.0, drawdown_pct=0.0),
            EquityCurvePoint(timestamp=self.t0 + timedelta(days=1), portfolio_value=120000.0, cash=120000.0, drawdown=0.0, drawdown_pct=0.0),
            EquityCurvePoint(timestamp=self.t0 + timedelta(days=2), portfolio_value=90000.0, cash=90000.0, drawdown=30000.0, drawdown_pct=25.0),
            EquityCurvePoint(timestamp=self.t0 + timedelta(days=3), portfolio_value=110000.0, cash=110000.0, drawdown=10000.0, drawdown_pct=8.33),
        ]
        metrics = self.engine.calculate_metrics(
            initial_capital=100000.0,
            equity_curve=curve,
            trade_journal=[],
        )
        self.assertEqual(metrics.max_drawdown_amount, 30000.0)
        self.assertEqual(metrics.max_drawdown_pct, 25.0)

    def test_sharpe_zero_volatility_guard(self):
        # Constant equity -> Daily returns = 0.0 -> Standard deviation = 0.0
        curve = [
            EquityCurvePoint(timestamp=self.t0, portfolio_value=100000.0, cash=100000.0, daily_return=0.0),
            EquityCurvePoint(timestamp=self.t0 + timedelta(days=1), portfolio_value=100000.0, cash=100000.0, daily_return=0.0),
            EquityCurvePoint(timestamp=self.t0 + timedelta(days=2), portfolio_value=100000.0, cash=100000.0, daily_return=0.0),
        ]
        metrics = self.engine.calculate_metrics(
            initial_capital=100000.0,
            equity_curve=curve,
            trade_journal=[],
        )
        self.assertEqual(metrics.annualized_volatility, 0.0)
        self.assertIsNone(metrics.sharpe_ratio)  # Must be None, not crashing with ZeroDivisionError

    def test_sortino_guard_with_no_downside(self):
        # Positive returns only -> downside deviation is 0 -> sortino is None
        curve = [
            EquityCurvePoint(timestamp=self.t0, portfolio_value=100000.0, cash=100000.0, daily_return=0.01),
            EquityCurvePoint(timestamp=self.t0 + timedelta(days=1), portfolio_value=102000.0, cash=102000.0, daily_return=0.02),
            EquityCurvePoint(timestamp=self.t0 + timedelta(days=2), portfolio_value=105000.0, cash=105000.0, daily_return=0.03),
        ]
        metrics = self.engine.calculate_metrics(
            initial_capital=100000.0,
            equity_curve=curve,
            trade_journal=[],
        )
        self.assertGreater(metrics.annualized_volatility, 0.0)
        self.assertIsNotNone(metrics.sharpe_ratio)

    def test_trade_journal_win_rate_and_profit_factor(self):
        trades = [
            TradeJournalEntry(
                trade_id="trd-1",
                order_id="ord-1",
                timestamp=self.t0,
                symbol="TCS.NS",
                side=OrderSide.BUY,
                quantity=10.0,
                requested_price=3000.0,
                executed_price=3000.0,
                commission=9.0,
                total_cost=30009.0,
                realized_pnl=0.0,
                context_id="ctx-1",
                committee_decision_state=InvestmentDecisionState.APPROVE,
                confidence=0.8,
                execution_decision=ExecutionDecision.ALLOWED,
                order_status=OrderStatus.FILLED,
            ),
            # Sell with +2000 profit
            TradeJournalEntry(
                trade_id="trd-2",
                order_id="ord-2",
                timestamp=self.t0 + timedelta(days=1),
                symbol="TCS.NS",
                side=OrderSide.SELL,
                quantity=5.0,
                requested_price=3400.0,
                executed_price=3400.0,
                commission=5.0,
                total_cost=16995.0,
                realized_pnl=2000.0,
                context_id="ctx-2",
                committee_decision_state=InvestmentDecisionState.APPROVE,
                confidence=0.8,
                execution_decision=ExecutionDecision.ALLOWED,
                order_status=OrderStatus.FILLED,
            ),
            # Sell with -500 loss
            TradeJournalEntry(
                trade_id="trd-3",
                order_id="ord-3",
                timestamp=self.t0 + timedelta(days=2),
                symbol="TCS.NS",
                side=OrderSide.SELL,
                quantity=5.0,
                requested_price=2900.0,
                executed_price=2900.0,
                commission=5.0,
                total_cost=14495.0,
                realized_pnl=-500.0,
                context_id="ctx-3",
                committee_decision_state=InvestmentDecisionState.APPROVE,
                confidence=0.8,
                execution_decision=ExecutionDecision.ALLOWED,
                order_status=OrderStatus.FILLED,
            ),
        ]
        metrics = self.engine.calculate_metrics(
            initial_capital=100000.0,
            equity_curve=[EquityCurvePoint(timestamp=self.t0, portfolio_value=101500.0, cash=101500.0, daily_return=0.015)],
            trade_journal=trades,
        )
        self.assertEqual(metrics.total_trades, 3)
        self.assertEqual(metrics.winning_trades, 1)
        self.assertEqual(metrics.losing_trades, 1)
        self.assertEqual(metrics.win_rate, 50.0)
        self.assertEqual(metrics.profit_factor, 4.0)  # 2000 win / 500 loss = 4.0
        self.assertEqual(metrics.total_commission_paid, 19.0)


if __name__ == "__main__":
    unittest.main()
