"""
Portfolio Performance Engine — Phase 5.2

Calculates deterministic risk-adjusted return metrics, drawdown curves, trade statistics,
and benchmark relative performance without look-ahead bias or mathematical singularities.
"""

from datetime import datetime
import math
from typing import List, Optional

from backend.domain.execution_schemas import OrderSide, OrderStatus
from backend.simulation.simulation_state import (
    EquityCurvePoint,
    PerformanceMetrics,
    TradeJournalEntry,
)


class PerformanceEngine:
    """
    Computes performance metrics from simulated equity curves and trade journals.
    """

    DEFAULT_ANNUAL_RISK_FREE_RATE = 0.05  # 5% risk-free rate for Indian G-Sec proxy

    def __init__(self, risk_free_rate: float = DEFAULT_ANNUAL_RISK_FREE_RATE) -> None:
        self.risk_free_rate = float(risk_free_rate)

    def calculate_metrics(
        self,
        initial_capital: float,
        equity_curve: List[EquityCurvePoint],
        trade_journal: List[TradeJournalEntry],
        benchmark_initial: Optional[float] = None,
        benchmark_final: Optional[float] = None,
    ) -> PerformanceMetrics:
        """
        Calculate complete portfolio performance metrics with strict zero-division guards.
        """
        if not equity_curve:
            return PerformanceMetrics(
                initial_capital=initial_capital,
                final_capital=initial_capital,
                total_return_pct=0.0,
            )

        final_capital = equity_curve[-1].portfolio_value
        total_return_pct = (
            ((final_capital - initial_capital) / initial_capital) * 100.0
            if initial_capital > 0
            else 0.0
        )

        # Benchmark calculations
        benchmark_return_pct: Optional[float] = None
        excess_return_pct: Optional[float] = None
        if benchmark_initial and benchmark_final and benchmark_initial > 0:
            benchmark_return_pct = (
                ((benchmark_final - benchmark_initial) / benchmark_initial) * 100.0
            )
            excess_return_pct = total_return_pct - benchmark_return_pct

        # Daily returns & Volatility
        daily_returns: List[float] = [p.daily_return for p in equity_curve if p.daily_return is not None]
        n_days = len(daily_returns)

        if n_days > 1:
            mean_daily = sum(daily_returns) / n_days
            variance = sum((r - mean_daily) ** 2 for r in daily_returns) / (n_days - 1)
            daily_std = math.sqrt(variance)
            annualized_volatility = daily_std * math.sqrt(252) * 100.0

            # Annualized Return
            first_ts = equity_curve[0].timestamp
            last_ts = equity_curve[-1].timestamp
            days_span = max(1, (last_ts - first_ts).days)
            if final_capital > 0 and initial_capital > 0:
                try:
                    annualized_return_pct = (
                        ((final_capital / initial_capital) ** (365.0 / days_span)) - 1.0
                    ) * 100.0
                except Exception:
                    annualized_return_pct = mean_daily * 252 * 100.0
            else:
                annualized_return_pct = -100.0

            # Sharpe Ratio
            daily_rf = self.risk_free_rate / 252.0
            excess_daily = mean_daily - daily_rf
            if daily_std > 1e-8:
                sharpe_ratio = (excess_daily / daily_std) * math.sqrt(252)
            else:
                sharpe_ratio = None

            # Sortino Ratio (Downside deviation only)
            negative_returns = [r - daily_rf for r in daily_returns if r < daily_rf]
            if negative_returns:
                downside_variance = sum(r**2 for r in negative_returns) / len(negative_returns)
                downside_std = math.sqrt(downside_variance)
                if downside_std > 1e-8:
                    sortino_ratio = (excess_daily / downside_std) * math.sqrt(252)
                else:
                    sortino_ratio = None
            else:
                sortino_ratio = None
        else:
            annualized_volatility = 0.0
            annualized_return_pct = total_return_pct
            sharpe_ratio = None
            sortino_ratio = None

        # Max Drawdown
        max_drawdown_amount = max((p.drawdown for p in equity_curve), default=0.0)
        max_drawdown_pct = max((p.drawdown_pct for p in equity_curve), default=0.0)

        # Trade Journal Statistics
        filled_trades = [t for t in trade_journal if t.order_status == OrderStatus.FILLED]
        total_trades = len(filled_trades)
        total_commission = sum(t.commission for t in filled_trades)
        total_slippage = sum(t.slippage for t in filled_trades)
        total_volume = sum(t.quantity * t.executed_price for t in filled_trades)
        turnover = total_volume / initial_capital if initial_capital > 0 else 0.0

        sell_trades = [t for t in filled_trades if t.side == OrderSide.SELL]
        winning_trades = [t for t in sell_trades if t.realized_pnl > 0]
        losing_trades = [t for t in sell_trades if t.realized_pnl < 0]

        total_closed = len(sell_trades)
        win_rate = (len(winning_trades) / total_closed) if total_closed > 0 else 0.0
        loss_rate = (len(losing_trades) / total_closed) if total_closed > 0 else 0.0

        total_win_amount = sum(t.realized_pnl for t in winning_trades)
        total_loss_amount = abs(sum(t.realized_pnl for t in losing_trades))

        avg_win_amount = (total_win_amount / len(winning_trades)) if winning_trades else 0.0
        avg_loss_amount = (total_loss_amount / len(losing_trades)) if losing_trades else 0.0

        profit_factor = (
            (total_win_amount / total_loss_amount)
            if total_loss_amount > 0
            else (float("inf") if total_win_amount > 0 else None)
        )
        if profit_factor == float("inf"):
            profit_factor = 999.99  # Safe capped representation

        win_loss_ratio = (
            (avg_win_amount / avg_loss_amount) if avg_loss_amount > 0 else None
        )

        return PerformanceMetrics(
            initial_capital=round(initial_capital, 2),
            final_capital=round(final_capital, 2),
            total_return_pct=round(total_return_pct, 2),
            benchmark_return_pct=round(benchmark_return_pct, 2) if benchmark_return_pct is not None else None,
            excess_return_pct=round(excess_return_pct, 2) if excess_return_pct is not None else None,
            annualized_return_pct=round(annualized_return_pct, 2),
            annualized_volatility=round(annualized_volatility, 2),
            max_drawdown_pct=round(max_drawdown_pct, 2),
            max_drawdown_amount=round(max_drawdown_amount, 2),
            sharpe_ratio=round(sharpe_ratio, 2) if sharpe_ratio is not None else None,
            sortino_ratio=round(sortino_ratio, 2) if sortino_ratio is not None else None,
            win_rate=round(win_rate * 100.0, 2),
            loss_rate=round(loss_rate * 100.0, 2),
            profit_factor=round(profit_factor, 2) if profit_factor is not None else None,
            total_trades=total_trades,
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            avg_win_amount=round(avg_win_amount, 2),
            avg_loss_amount=round(avg_loss_amount, 2),
            win_loss_ratio=round(win_loss_ratio, 2) if win_loss_ratio is not None else None,
            avg_holding_period_days=0.0,
            total_commission_paid=round(total_commission, 2),
            total_slippage_cost=round(total_slippage, 2),
            turnover=round(turnover, 2),
        )
