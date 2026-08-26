"""
Empirical Validation Runner — Phase 5.4A

Executes real-data walk-forward validation runs, records empirical data trust audits,
measures specialist data sufficiency, and generates the final empirical scorecard.
"""

from datetime import datetime
import hashlib
import json
import math
from typing import Any, Dict, List, Optional, Tuple

from backend.scanner.universe import StockUniverse, UniverseType
from backend.simulation.simulation_state import PerformanceMetrics
from backend.validation.empirical_audit import (
    DataSufficiencyReport,
    DataTrustAuditor,
    EmpiricalScorecard,
    ProviderAvailabilityEntry,
    StrategyClassification,
)
from backend.validation.validation_config import WalkForwardConfig
from backend.validation.validation_state import WalkForwardResult
from backend.validation.walk_forward import WalkForwardEngine


class EmpiricalValidationRunner:
    """
    Executes empirical strategy validation runs against real verified market data.
    """

    def __init__(
        self,
        config: Optional[WalkForwardConfig] = None,
        universe: Optional[StockUniverse] = None,
    ) -> None:
        self.config = config or WalkForwardConfig()
        self.universe = universe or StockUniverse(self.config.universe_type)
        self.engine = WalkForwardEngine(config=self.config, universe=self.universe)

    async def run_empirical_validation(
        self,
        historical_datasets: Dict[str, Dict[str, Any]],
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Tuple[WalkForwardResult, EmpiricalScorecard]:
        s_date = start_date or datetime(2023, 1, 1)
        e_date = end_date or datetime(2024, 1, 1)

        # 1. Data Sufficiency & Provider Audit
        data_sufficiency = DataTrustAuditor.audit_data_sufficiency(historical_datasets)

        # 2. Run Full Walk-Forward Pipeline
        wf_result: WalkForwardResult = await self.engine.run_walk_forward(
            historical_datasets=historical_datasets,
            start_date=s_date,
            end_date=e_date,
        )

        metrics: PerformanceMetrics = wf_result.overall_out_of_sample_metrics
        is_clean_pit = wf_result.scorecard.data_quality_score == 100.0
        survivorship_risk = data_sufficiency.survivorship_bias_risk

        # 3. Deterministic Strategy Classification
        classification, class_reason = DataTrustAuditor.classify_strategy(
            metrics=metrics,
            data_sufficiency=data_sufficiency,
            is_clean_pit=is_clean_pit,
            survivorship_bias=survivorship_risk,
        )

        # 4. Compute CAGR & Calmar Ratio
        days_span = max(1, (e_date - s_date).days)
        final_cap = metrics.final_capital
        init_cap = metrics.initial_capital
        if final_cap > 0 and init_cap > 0 and days_span > 0:
            try:
                cagr_pct = (((final_cap / init_cap) ** (365.0 / days_span)) - 1.0) * 100.0
            except Exception:
                cagr_pct = metrics.total_return_pct
        else:
            cagr_pct = 0.0

        calmar_ratio = (
            round(cagr_pct / metrics.max_drawdown_pct, 2)
            if metrics.max_drawdown_pct > 0
            else None
        )

        # 5. Determine Break-even transaction cost bps
        turnover = max(1.0, metrics.turnover)
        # Break-even bps = (Total return % / (turnover * 100)) * 10000
        if turnover > 0 and metrics.total_return_pct > 0:
            break_even_bps = int((metrics.total_return_pct / turnover) * 100.0)
        else:
            break_even_bps = 0

        # 6. Reproducibility Hash
        hash_payload = f"{self.universe.universe_type}_{s_date.isoformat()}_{e_date.isoformat()}_{metrics.total_return_pct}_{metrics.total_trades}"
        rep_hash = hashlib.sha256(hash_payload.encode("utf-8")).hexdigest()[:16]

        scorecard = EmpiricalScorecard(
            classification=classification,
            classification_reason=class_reason,
            data_sufficiency=data_sufficiency,
            total_return_pct=metrics.total_return_pct,
            cagr_pct=round(cagr_pct, 2),
            annualized_volatility=metrics.annualized_volatility,
            sharpe_ratio=metrics.sharpe_ratio,
            sortino_ratio=metrics.sortino_ratio,
            max_drawdown_pct=metrics.max_drawdown_pct,
            calmar_ratio=calmar_ratio,
            win_rate=metrics.win_rate,
            profit_factor=metrics.profit_factor,
            total_trades=metrics.total_trades,
            turnover=metrics.turnover,
            break_even_cost_bps=break_even_bps,
            is_pit_clean=is_clean_pit,
            survivorship_bias_risk=survivorship_risk,
            reproducibility_hash=rep_hash,
        )

        return wf_result, scorecard

    @staticmethod
    def to_markdown(scorecard: EmpiricalScorecard, result: WalkForwardResult) -> str:
        s = scorecard
        m = result.overall_out_of_sample_metrics
        suff = s.data_sufficiency

        lines = [
            f"# Empirical Strategy Validation Report: {result.run_id}",
            "",
            f"**Historical Evaluation Window:** {result.start_date.strftime('%Y-%m-%d')} to {result.end_date.strftime('%Y-%m-%d')}",
            f"**Reproducibility Hash:** `{s.reproducibility_hash}` | **Data Label:** `REAL_MARKET_DATA`",
            f"**Final Classification:** `{s.classification.value}`",
            "",
            f"> **Assessment:** {s.classification_reason}",
            "",
            "## 1. Verified Empirical Performance",
            "",
            "| Metric | Full AI Strategy | Benchmark (^NSEI) | Improvement |",
            "|---|---|---|---|",
            f"| **Total Out-of-Sample Return** | `{s.total_return_pct:+.2f}%` | `{m.benchmark_return_pct if m.benchmark_return_pct is not None else 'N/A'}` | `{m.excess_return_pct if m.excess_return_pct is not None else 'N/A'}` |",
            f"| **CAGR (Annualized)** | `{s.cagr_pct:+.2f}%` | — | — |",
            f"| **Annualized Volatility** | `{s.annualized_volatility:.2f}%` | — | — |",
            f"| **Sharpe Ratio** | `{s.sharpe_ratio if s.sharpe_ratio is not None else 'N/A'}` | — | — |",
            f"| **Sortino Ratio** | `{s.sortino_ratio if s.sortino_ratio is not None else 'N/A'}` | — | — |",
            f"| **Max Drawdown** | `{s.max_drawdown_pct:.2f}%` | — | — |",
            f"| **Calmar Ratio** | `{s.calmar_ratio if s.calmar_ratio is not None else 'N/A'}` | — | — |",
            f"| **Win Rate** | `{s.win_rate:.1f}%` | — | — |",
            f"| **Profit Factor** | `{s.profit_factor if s.profit_factor is not None else 'N/A'}` | — | — |",
            f"| **Total OOS Trades** | {s.total_trades} | — | — |",
            f"| **Break-Even Cost Assumption** | `{s.break_even_cost_bps} bps` | — | — |",
            "",
            "## 2. Specialist Domain Data Sufficiency",
            "",
            "| Specialist Domain | Real Data Completeness (%) | Status |",
            "|---|---|---|",
        ]

        for domain, pct in suff.specialist_availability.items():
            lines.append(
                f"| **{domain} Specialist** | `{pct:.1f}%` | {'✅ Verified' if pct >= 70 else ('⚠️ Partial' if pct >= 30 else '❌ Sparse')} |"
            )

        lines.extend([
            "",
            f"**Overall Data Completeness:** `{suff.overall_data_completeness_pct:.1f}%` (`{suff.quality_segment}`)",
            f"**Survivorship Bias Risk:** `{'YES — ' + suff.survivorship_notes if suff.survivorship_bias_risk else 'NO'}`",
            f"**Point-in-Time Temporal Integrity:** `{'✅ 100% CLEAN' if s.is_pit_clean else '❌ LEAKAGE DETECTED'}`",
            "",
            "## 3. Baseline Strategy Rankings",
            "",
            "| Strategy | OOS Return | Sharpe | Max Drawdown | Win Rate | Profit Factor |",
            "|---|---|---|---|---|---|",
        ])

        for b in result.baseline_comparisons:
            lines.append(
                f"| **{b.strategy_name}** | `{b.total_return_pct:+.2f}%` | `{b.sharpe_ratio if b.sharpe_ratio is not None else 'N/A'}` | `{b.max_drawdown_pct:.1f}%` | `{b.win_rate:.1f}%` | `{b.profit_factor if b.profit_factor is not None else 'N/A'}` |"
            )

        return "\n".join(lines)
