"""
Simulation Report Generator — Phase 5.2

Formats deterministic simulation results into structured reports, summaries, and Markdown logs.
"""

from datetime import datetime, timezone
from typing import List, Optional

from backend.simulation.simulation_config import SimulationConfig
from backend.simulation.simulation_state import (
    DataQualityStatistics,
    DecisionJournalEntry,
    EquityCurvePoint,
    PerformanceMetrics,
    SimulationReport,
    TradeJournalEntry,
)


class SimulationReportBuilder:
    """
    Builds structured simulation reports and exports Markdown summaries.
    """

    @staticmethod
    def build_report(
        simulation_id: str,
        config: SimulationConfig,
        metrics: PerformanceMetrics,
        data_quality: DataQualityStatistics,
        equity_curve: List[EquityCurvePoint],
        trade_journal: List[TradeJournalEntry],
        decision_journal: List[DecisionJournalEntry],
        start_date: datetime,
        end_date: datetime,
    ) -> SimulationReport:
        return SimulationReport(
            simulation_id=simulation_id,
            config=config,
            start_date=start_date,
            end_date=end_date,
            symbols=config.symbols,
            initial_capital=config.initial_cash,
            final_capital=metrics.final_capital,
            metrics=metrics,
            data_quality=data_quality,
            equity_curve=equity_curve,
            trade_journal=trade_journal,
            decision_journal=decision_journal,
            generated_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def to_markdown(report: SimulationReport) -> str:
        """Render a readable Markdown summary of the simulation."""
        m = report.metrics
        dq = report.data_quality
        lines = [
            f"# Simulation Report: {report.simulation_id}",
            "",
            f"**Execution Mode:** `{report.config.execution_mode.value}` | **Symbols:** {', '.join(report.symbols)}",
            f"**Period:** {report.start_date.strftime('%Y-%m-%d')} to {report.end_date.strftime('%Y-%m-%d')}",
            f"**Initial Capital:** ₹{report.initial_capital:,.2f} | **Final Capital:** ₹{report.final_capital:,.2f}",
            "",
            "## 1. Performance Overview",
            "",
            "| Metric | Strategy | Benchmark |",
            "|---|---|---|",
            f"| **Total Return** | `{m.total_return_pct:+.2f}%` | `{m.benchmark_return_pct if m.benchmark_return_pct is not None else 'N/A'}` |",
            f"| **Excess Return** | `{m.excess_return_pct if m.excess_return_pct is not None else 'N/A'}` | — |",
            f"| **Annualized Volatility** | `{m.annualized_volatility:.2f}%` | — |",
            f"| **Max Drawdown** | `{m.max_drawdown_pct:.2f}%` (₹{m.max_drawdown_amount:,.2f}) | — |",
            f"| **Sharpe Ratio** | `{m.sharpe_ratio if m.sharpe_ratio is not None else 'N/A'}` | — |",
            f"| **Sortino Ratio** | `{m.sortino_ratio if m.sortino_ratio is not None else 'N/A'}` | — |",
            "",
            "## 2. Trade Statistics",
            "",
            f"- **Total Executed Trades:** {m.total_trades}",
            f"- **Winning Trades:** {m.winning_trades} ({m.win_rate:.1f}%)",
            f"- **Losing Trades:** {m.losing_trades} ({m.loss_rate:.1f}%)",
            f"- **Profit Factor:** {m.profit_factor if m.profit_factor is not None else 'N/A'}",
            f"- **Average Win / Loss:** ₹{m.avg_win_amount:,.2f} / ₹{m.avg_loss_amount:,.2f}",
            f"- **Total Commission & Slippage:** ₹{m.total_commission_paid + m.total_slippage_cost:,.2f}",
            "",
            "## 3. Data Quality & Veto Audit",
            "",
            "| Check / Statistic | Count |",
            "|---|---|",
            f"| Contexts Processed | `{dq.contexts_processed}` |",
            f"| Contexts Stale / Requires Revalidation | `{dq.stale_contexts_count}` |",
            f"| Missing Fundamental Data | `{dq.missing_fundamentals_count}` |",
            f"| Missing News Data | `{dq.missing_news_count}` |",
            f"| Missing Institutional Data | `{dq.missing_institutional_count}` |",
            f"| Committee Risk Vetoes | `{dq.risk_veto_count}` |",
            f"| Committee Data Quality Vetoes | `{dq.data_quality_veto_count}` |",
            f"| Committee Insufficient Evidence | `{dq.committee_insufficient_evidence_count}` |",
            f"| Execution Safety Rejections | `{dq.execution_rejections_count}` |",
            "",
        ]

        if report.trade_journal:
            lines.extend([
                "## 4. Trade Journal (Latest 10)",
                "",
                "| Timestamp | Symbol | Side | Qty | Price | Cost | Realized P&L | Status |",
                "|---|---|---|---|---|---|---|---|",
            ])
            for t in report.trade_journal[-10:]:
                lines.append(
                    f"| {t.timestamp.strftime('%Y-%m-%d %H:%M')} | {t.symbol} | {t.side.value} | {t.quantity:.0f} | ₹{t.executed_price:,.2f} | ₹{t.total_cost:,.2f} | ₹{t.realized_pnl:+,.2f} | `{t.order_status.value}` |"
                )

        return "\n".join(lines)
