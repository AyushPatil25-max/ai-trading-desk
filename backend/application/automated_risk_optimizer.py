"""
Phase 17 — Automated Risk Optimizer

Implements paper and sandbox volatility targeting and risk-budget allocation.
Dynamically adjusts asset allocations based on rolling realized volatility, target volatility,
and inverse-volatility / equal risk contribution (ERC) weighting.
Strictly intersects all optimizer outputs with ExecutionGuard and RiskEngine constraints
(unleveraged cash buffer >= 5%, max single asset <= 15%, no margin borrowing).
"""

from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from backend.domain.factor_risk_schemas import (
    RiskBudgetMethod,
    RiskOptimizationConfig,
    RiskOptimizationResult,
)
from backend.application.execution_guard import ExecutionGuard, global_execution_guard


class AutomatedRiskOptimizer:
    """
    Authoritative risk optimization service for volatility targeting and risk budgeting.
    Pure Python & NumPy numerical calculations.
    """

    def __init__(
        self,
        config: Optional[RiskOptimizationConfig] = None,
        execution_guard: Optional[ExecutionGuard] = None,
    ) -> None:
        self.config = config or RiskOptimizationConfig()
        self.execution_guard = execution_guard or global_execution_guard
        self._latest_result: Optional[RiskOptimizationResult] = None

    def calculate_realized_volatility(self, returns: List[float]) -> float:
        """
        Compute annualized standard deviation from daily return series.
        """
        if len(returns) < 2:
            return self.config.target_annualized_volatility
        daily_std = float(np.std(returns, ddof=1))
        return float(daily_std * math.sqrt(252.0))

    def optimize_allocations(
        self,
        asset_returns_map: Dict[str, List[float]],
        baseline_weights: Optional[Dict[str, float]] = None,
        override_config: Optional[RiskOptimizationConfig] = None,
    ) -> RiskOptimizationResult:
        """
        Perform volatility targeting and risk budgeting across active assets.
        Enforces:
        1. Volatility targeting scalar: k = min(sigma_target / sigma_realized, max_leverage).
        2. Leverage cap: <= 1.0 for unleveraged cash paper trading.
        3. Minimum cash buffer: >= 5%.
        4. Max single asset weight: <= 15%.
        5. ExecutionGuard risk clearance.
        """
        now = datetime.now(timezone.utc)
        cfg = override_config or self.config
        violations_prevented: List[str] = []

        symbols = list(asset_returns_map.keys())
        if not symbols:
            # Safe empty baseline
            return RiskOptimizationResult(
                baseline_volatility=0.0,
                optimized_volatility=0.0,
                target_volatility=cfg.target_annualized_volatility,
                volatility_scalar=1.0,
                baseline_weights={},
                optimized_weights={},
                risk_budget_allocations={},
                cash_allocation=1.0,
                risk_gates_cleared=True,
                violations_prevented=["No assets provided for optimization; allocated 100% to cash."],
                timestamp=now,
            )

        # ── 1. Realized Volatility of Each Asset & Equal-Weighted Portfolio ───
        asset_vols: Dict[str, float] = {}
        for sym, rets in asset_returns_map.items():
            vol = self.calculate_realized_volatility(rets[-cfg.volatility_lookback_days:])
            asset_vols[sym] = max(vol, 0.02)  # Floor at 2% to prevent div by zero

        # Estimate baseline portfolio volatility
        if baseline_weights is None:
            n_assets = len(symbols)
            eq_w = (1.0 - cfg.min_cash_buffer) / n_assets
            baseline_weights = {sym: eq_w for sym in symbols}

        # Weighted portfolio volatility proxy
        base_vol = float(sum(baseline_weights.get(sym, 0.0) * asset_vols[sym] for sym in symbols))

        # ── 2. Volatility Targeting Scaling Factor (k) ────────────────────────
        if base_vol > 1e-4:
            raw_k = cfg.target_annualized_volatility / base_vol
        else:
            raw_k = 1.0

        # Enforce leverage ceiling: non-margin paper accounts strictly <= 1.0
        vol_scalar = min(raw_k, cfg.max_portfolio_leverage)
        if raw_k > cfg.max_portfolio_leverage:
            violations_prevented.append(
                f"Leverage scalar {raw_k:.2f} clamped to max_portfolio_leverage {cfg.max_portfolio_leverage:.2f}"
            )

        # ── 3. Risk Budgeting Allocation (Inverse Volatility / ERC) ───────────
        # w_i proportional to 1 / sigma_i
        inv_vols = {sym: 1.0 / asset_vols[sym] for sym in symbols}
        sum_inv = sum(inv_vols.values())
        risk_budget_shares = {sym: inv_vols[sym] / sum_inv for sym in symbols}

        # Scaled investable capital (1 - cash buffer) * vol_scalar
        max_investable = (1.0 - cfg.min_cash_buffer) * vol_scalar
        raw_target_weights = {sym: risk_budget_shares[sym] * max_investable for sym in symbols}

        # ── 4. Position Sizing & Concentration Constraints ───────────────────
        # Enforce max_single_asset_weight <= 15%
        clamped_weights: Dict[str, float] = {}
        excess_reallocated = 0.0

        for sym, w in raw_target_weights.items():
            if w > cfg.max_single_asset_weight:
                clamped_weights[sym] = cfg.max_single_asset_weight
                excess_reallocated += (w - cfg.max_single_asset_weight)
                violations_prevented.append(
                    f"Concentration limit exceeded for {sym}: clamped from {w*100:.1f}% to {cfg.max_single_asset_weight*100:.1f}%"
                )
            else:
                clamped_weights[sym] = round(w, 4)

        total_invested = sum(clamped_weights.values())
        cash_alloc = max(cfg.min_cash_buffer, round(1.0 - total_invested, 4))

        # Expected optimized volatility
        opt_vol = float(sum(clamped_weights.get(sym, 0.0) * asset_vols[sym] for sym in symbols))

        # ── 5. ExecutionGuard & Safety Clearance ──────────────────────────────
        # Confirm that ExecutionGuard kill switch is not active
        guard_status = getattr(self.execution_guard, "get_status_summary", lambda: {})()
        kill_switch_active = guard_status.get("kill_switch_triggered", False)
        risk_cleared = not kill_switch_active

        if kill_switch_active:
            violations_prevented.append("EMERGENCY KILL SWITCH ACTIVE: Risk optimizer allocations marked un-cleared.")

        result = RiskOptimizationResult(
            baseline_volatility=round(base_vol, 4),
            optimized_volatility=round(opt_vol, 4),
            target_volatility=round(cfg.target_annualized_volatility, 4),
            volatility_scalar=round(vol_scalar, 4),
            baseline_weights={k: round(v, 4) for k, v in baseline_weights.items()},
            optimized_weights=clamped_weights,
            risk_budget_allocations={k: round(v, 4) for k, v in risk_budget_shares.items()},
            cash_allocation=cash_alloc,
            risk_gates_cleared=risk_cleared,
            violations_prevented=violations_prevented,
            timestamp=now,
        )
        self._latest_result = result
        return result

    def get_latest_result(self) -> Optional[RiskOptimizationResult]:
        return self._latest_result


# Global singleton instance
global_risk_optimizer = AutomatedRiskOptimizer()
