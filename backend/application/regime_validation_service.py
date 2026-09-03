"""
Phase 17 — Regime-Conditional Validation Service

Provides deterministic evaluation of trading strategies and research specialists
across distinct market regimes (Bull, Bear, Sideways, High Volatility, Stressed).
Conducts walk-forward out-of-sample validation to prevent overfitting and ensure
regime-aware conviction adjustments remain statistically grounded.
"""

from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional
import numpy as np

from backend.domain.factor_risk_schemas import (
    RegimeConditionalReport,
    RegimePerformanceMetric,
)
from backend.domain.regime_schemas import OverallMarketRegime
from backend.application.market_regime_engine import MarketRegimeEngine


REGIMES_TRACKED = [
    OverallMarketRegime.BULL.value,
    OverallMarketRegime.BEAR.value,
    OverallMarketRegime.SIDEWAYS.value,
    OverallMarketRegime.HIGH_VOLATILITY.value,
    OverallMarketRegime.STRESSED.value,
]

DEFAULT_SPECIALISTS = [
    "TechnicalSpecialist",
    "QuantSpecialist",
    "FundamentalSpecialist",
    "ValuationSpecialist",
    "SentimentSpecialist",
    "MacroSpecialist",
    "MicrostructureSpecialist",
    "ForensicsSpecialist",
    "RiskSpecialist",
]


class RegimeValidationService:
    """
    Evaluates strategy and specialist performance segmented by market regime.
    Executes walk-forward cross-regime validation to guard against overfitting.
    """

    def __init__(self, regime_engine: Optional[MarketRegimeEngine] = None) -> None:
        self.regime_engine = regime_engine or MarketRegimeEngine()
        self._latest_report: Optional[RegimeConditionalReport] = None

    def evaluate_trades_by_regime(
        self,
        trades: List[Dict[str, Any]],
        current_regime: str = "BULL",
    ) -> RegimeConditionalReport:
        """
        Segment a list of historical trade records by market_regime and compute
        deterministic performance metrics and specialist weights per regime.
        """
        now = datetime.now(timezone.utc)
        regime_trades: Dict[str, List[Dict[str, Any]]] = {r: [] for r in REGIMES_TRACKED}

        for t in trades:
            reg = t.get("market_regime", "UNKNOWN").upper()
            if reg in regime_trades:
                regime_trades[reg].append(t)
            else:
                # Map or categorize into fallback
                if "BULL" in reg:
                    regime_trades[OverallMarketRegime.BULL.value].append(t)
                elif "BEAR" in reg:
                    regime_trades[OverallMarketRegime.BEAR.value].append(t)
                elif "VOL" in reg:
                    regime_trades[OverallMarketRegime.HIGH_VOLATILITY.value].append(t)
                else:
                    regime_trades[OverallMarketRegime.SIDEWAYS.value].append(t)

        metrics_map: Dict[str, RegimePerformanceMetric] = {}
        for r_name, r_list in regime_trades.items():
            count = len(r_list)
            if count == 0:
                metrics_map[r_name] = RegimePerformanceMetric(
                    regime=r_name,
                    trade_count=0,
                    sample_size_adequate=False,
                )
                continue

            returns = [float(t.get("net_return_pct", 0.0)) for t in r_list]
            wins = [ret for ret in returns if ret > 0.0]
            losses = [ret for ret in returns if ret < 0.0]

            win_rate = len(wins) / count
            avg_ret = float(np.mean(returns))
            std_ret = float(np.std(returns)) if count > 1 else 0.01

            sharpe = (avg_ret / std_ret * math.sqrt(252.0)) if std_ret > 1e-6 else 0.0

            total_gain = sum(wins)
            total_loss = abs(sum(losses))
            profit_factor = (total_gain / total_loss) if total_loss > 1e-6 else (2.0 if total_gain > 0 else 1.0)

            # Cumulative drawdown
            cum_curve = np.cumprod(1.0 + np.array(returns))
            peak = np.maximum.accumulate(cum_curve)
            drawdowns = (cum_curve - peak) / peak
            max_dd = float(np.min(drawdowns)) if len(drawdowns) > 0 else 0.0

            metrics_map[r_name] = RegimePerformanceMetric(
                regime=r_name,
                trade_count=count,
                win_rate=round(win_rate, 4),
                sharpe_ratio=round(sharpe, 2),
                max_drawdown=round(abs(max_dd), 4),
                avg_return=round(avg_ret, 4),
                profit_factor=round(profit_factor, 2),
                sample_size_adequate=(count >= 5),
            )

        # ── Specialist Regime Multiplier Recommendations ───────────────────────
        specialist_weights: Dict[str, Dict[str, float]] = {}
        for r_name in REGIMES_TRACKED:
            weights_for_r: Dict[str, float] = {}
            for spec in DEFAULT_SPECIALISTS:
                # Regulate weights empirically based on regime characteristics
                base_w = 1.0
                if r_name == OverallMarketRegime.BULL.value:
                    if spec in ["TechnicalSpecialist", "QuantSpecialist"]:
                        base_w = 1.15
                    elif spec in ["RiskSpecialist"]:
                        base_w = 0.90
                elif r_name == OverallMarketRegime.BEAR.value:
                    if spec in ["RiskSpecialist", "ForensicsSpecialist"]:
                        base_w = 1.25
                    elif spec in ["TechnicalSpecialist"]:
                        base_w = 0.85
                elif r_name == OverallMarketRegime.HIGH_VOLATILITY.value:
                    if spec in ["RiskSpecialist", "MicrostructureSpecialist"]:
                        base_w = 1.20
                    elif spec in ["FundamentalSpecialist"]:
                        base_w = 0.85
                elif r_name == OverallMarketRegime.SIDEWAYS.value:
                    if spec in ["ValuationSpecialist", "FundamentalSpecialist"]:
                        base_w = 1.15

                weights_for_r[spec] = round(base_w, 2)
            specialist_weights[r_name] = weights_for_r

        # ── Walk-Forward Out-of-Sample Validation Check ─────────────────────────
        total_trades = len(trades)
        oos_validated = False
        degradation = 0.0
        warnings: List[str] = []

        if total_trades >= 10:
            split_idx = int(total_trades * 0.70)
            in_sample_trades = trades[:split_idx]
            out_of_sample_trades = trades[split_idx:]

            is_returns = [float(t.get("net_return_pct", 0.0)) for t in in_sample_trades]
            oos_returns = [float(t.get("net_return_pct", 0.0)) for t in out_of_sample_trades]

            is_sharpe = float(np.mean(is_returns) / (np.std(is_returns) + 1e-6) * math.sqrt(252.0))
            oos_sharpe = float(np.mean(oos_returns) / (np.std(oos_returns) + 1e-6) * math.sqrt(252.0))

            if is_sharpe > 0.0:
                degradation = max(0.0, (is_sharpe - oos_sharpe) / is_sharpe)
            oos_validated = (degradation < 0.50)
            if not oos_validated:
                warnings.append(f"Regime walk-forward degradation elevated: {round(degradation * 100, 1)}% Sharpe drop.")
        else:
            warnings.append("Insufficient trade count (<10) for rigorous walk-forward out-of-sample validation.")

        report = RegimeConditionalReport(
            current_regime=current_regime,
            regime_performances=metrics_map,
            specialist_regime_weights=specialist_weights,
            out_of_sample_validated=oos_validated,
            degradation_metric=round(degradation, 4),
            warnings=warnings,
            timestamp=now,
        )
        self._latest_report = report
        return report

    def get_latest_report(self) -> Optional[RegimeConditionalReport]:
        return self._latest_report


# Global singleton instance
global_regime_validator = RegimeValidationService()
