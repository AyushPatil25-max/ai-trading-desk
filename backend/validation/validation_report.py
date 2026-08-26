"""
Validation Report Generator — Phase 5.4

Formats complete walk-forward validation results, baseline comparisons,
ablation results, and scorecards into clean Markdown reports.
"""

from backend.validation.validation_state import WalkForwardResult


class ValidationReportBuilder:
    """
    Builds human-readable validation summary reports.
    """

    @staticmethod
    def to_markdown(result: WalkForwardResult) -> str:
        m = result.overall_out_of_sample_metrics
        sc = result.scorecard

        lines = [
            f"# Walk-Forward Strategy Validation Report: {result.run_id}",
            "",
            f"**Validation Period:** {result.start_date.strftime('%Y-%m-%d')} to {result.end_date.strftime('%Y-%m-%d')} | **Windows Evaluated:** {len(result.windows)}",
            f"**Overall Out-of-Sample Score:** `{sc.overall_validation_score:.1f}/100` | **Status:** `{'PASSED' if sc.passed_validation else 'REJECTED'}`",
            "",
            "## 1. Validation Scorecard",
            "",
            "| Dimension | Score (0-100) | Weight | Status |",
            "|---|---|---|---|",
            f"| **Predictive Quality** | `{sc.predictive_quality_score:.1f}` | 20% | {'✅' if sc.predictive_quality_score >= 50 else '⚠️'} |",
            f"| **Risk-Adjusted Performance** | `{sc.risk_adjusted_score:.1f}` | 20% | {'✅' if sc.risk_adjusted_score >= 50 else '⚠️'} |",
            f"| **Drawdown Control** | `{sc.drawdown_score:.1f}` | 15% | {'✅' if sc.drawdown_score >= 50 else '⚠️'} |",
            f"| **Consistency** | `{sc.consistency_score:.1f}` | 15% | {'✅' if sc.consistency_score >= 50 else '⚠️'} |",
            f"| **Robustness** | `{sc.robustness_score:.1f}` | 10% | {'✅' if sc.robustness_score >= 50 else '⚠️'} |",
            f"| **PIT & Data Integrity** | `{sc.data_quality_score:.1f}` | 20% | {'✅' if sc.data_quality_score == 100 else '❌'} |",
            "",
            f"> **Summary:** {sc.summary}",
            "",
            "## 2. Baseline Strategy Comparison",
            "",
            "| Strategy | Out-of-Sample Return | Sharpe Ratio | Max Drawdown | Win Rate |",
            "|---|---|---|---|---|",
        ]

        for b in result.baseline_comparisons:
            lines.append(
                f"| **{b.strategy_name}** | `{b.total_return_pct:+.2f}%` | `{b.sharpe_ratio if b.sharpe_ratio is not None else 'N/A'}` | `{b.max_drawdown_pct:.1f}%` | `{b.win_rate:.1f}%` |"
            )

        lines.extend([
            "",
            "## 3. Ablation Analysis",
            "",
            "| Pipeline Architecture | Return | Sharpe | Drawdown | Win Rate | Profit Factor |",
            "|---|---|---|---|---|---|",
        ])

        for a in result.ablation_results:
            lines.append(
                f"| **{a.pipeline_variant}** | `{a.total_return_pct:+.2f}%` | `{a.sharpe_ratio if a.sharpe_ratio is not None else 'N/A'}` | `{a.max_drawdown_pct:.1f}%` | `{a.win_rate:.1f}%` | `{a.profit_factor if a.profit_factor is not None else 'N/A'}` |"
            )

        lines.extend([
            "",
            "## 4. Market Regime Breakdown",
            "",
            "| Market Regime | Return | Win Rate | Max Drawdown | Trades |",
            "|---|---|---|---|---|",
        ])

        for r in result.regime_analysis:
            lines.append(
                f"| `{r.regime.value}` | `{r.total_return_pct:+.2f}%` | `{r.win_rate:.1f}%` | `{r.max_drawdown_pct:.1f}%` | {r.trade_count} |"
            )

        return "\n".join(lines)
