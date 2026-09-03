"""
Phase 17 — Advanced Statistical Factor Validation & Automated Risk Optimization Schemas

Strongly typed domain models for Fama-French 5-factor + Carhart momentum attribution,
regime-conditional performance decomposition, automated volatility targeting,
risk budgeting, and statistical walk-forward validation.
"""

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


FACTOR_RISK_VERSION = "17.0.0"


# ── Factor Enums & Status ───────────────────────────────────────────────────

class FactorType(str, Enum):
    """Standard asset pricing factor identifiers."""
    MARKET_RF = "MARKET_RF"      # Excess market benchmark return (Rm - Rf)
    SMB = "SMB"                  # Small Minus Big (Size factor)
    HML = "HML"                  # High Minus Low (Value factor)
    RMW = "RMW"                  # Robust Minus Weak (Profitability factor)
    CMA = "CMA"                  # Conservative Minus Aggressive (Investment factor)
    MOM = "MOM"                  # Up Minus Down (Momentum factor / Carhart WML)


class FactorDataStatus(str, Enum):
    """Provenance and availability state of factor observations."""
    AVAILABLE = "AVAILABLE"                      # Full observed factor time series
    ESTIMATED = "ESTIMATED"                      # Synthesized from equity universe proxies
    UNAVAILABLE = "UNAVAILABLE"                  # Data source missing or disabled
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"  # History length < required observations


class RiskBudgetMethod(str, Enum):
    """Allocation method for risk budgeting."""
    EQUAL_RISK_CONTRIBUTION = "EQUAL_RISK_CONTRIBUTION"
    INVERSE_VOLATILITY = "INVERSE_VOLATILITY"


# ── Single & Multi-Factor Attribution Models ────────────────────────────────

class SingleFactorAttribution(BaseModel):
    """
    Empirical attribution metrics for an individual risk factor.
    """
    factor_name: str
    factor_type: FactorType
    beta: float = 0.0
    t_statistic: float = 0.0
    p_value: float = 1.0
    is_significant: bool = False
    factor_return: float = 0.0
    return_contribution: float = 0.0
    status: FactorDataStatus = FactorDataStatus.AVAILABLE


class MultiFactorAttributionResult(BaseModel):
    """
    Complete multivariate OLS decomposition of returns against 6 factor benchmarks.
    Strictly deterministic Python / NumPy calculations.
    """
    attribution_id: str = Field(default_factory=lambda: f"mfa-{uuid.uuid4().hex[:8]}")
    symbol_or_portfolio: str
    start_date: datetime
    end_date: datetime
    observation_count: int = 0
    alpha: float = 0.0                     # Annualized Jensen's alpha
    alpha_t_stat: float = 0.0
    alpha_p_value: float = 1.0
    r_squared: float = 0.0
    adjusted_r_squared: float = 0.0
    residual_standard_error: float = 0.0
    factors: Dict[str, SingleFactorAttribution] = Field(default_factory=dict)
    systematic_risk_pct: float = 0.0       # Proportion of variance explained by factors
    specific_risk_pct: float = 100.0       # Proportion of idiosyncratic variance
    insufficient_sample: bool = False
    data_status: FactorDataStatus = FactorDataStatus.AVAILABLE
    warnings: List[str] = Field(default_factory=list)
    calculated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Regime-Conditional Validation Models ────────────────────────────────────

class RegimePerformanceMetric(BaseModel):
    """
    Performance profile of strategy or agent within a distinct market regime.
    """
    regime: str
    trade_count: int = 0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    avg_return: float = 0.0
    profit_factor: float = 0.0
    sample_size_adequate: bool = False


class RegimeConditionalReport(BaseModel):
    """
    Multi-regime validation summary and specialist sensitivity attribution.
    """
    report_id: str = Field(default_factory=lambda: f"rcr-{uuid.uuid4().hex[:8]}")
    current_regime: str = "UNKNOWN"
    regime_performances: Dict[str, RegimePerformanceMetric] = Field(default_factory=dict)
    specialist_regime_weights: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    out_of_sample_validated: bool = False
    degradation_metric: float = 0.0        # Performance drop in OOS partitions
    warnings: List[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Automated Risk Optimization Models ──────────────────────────────────────

class RiskOptimizationConfig(BaseModel):
    """
    Deterministic configuration parameters for volatility targeting and risk budgeting.
    """
    target_annualized_volatility: float = Field(default=0.15, ge=0.01, le=1.0, description="Target vol (e.g. 15%)")
    max_portfolio_leverage: float = Field(default=1.0, ge=0.1, le=1.25, description="Max leverage scalar (<= 1.0 for cash-only)")
    min_cash_buffer: float = Field(default=0.05, ge=0.0, le=0.50, description="Minimum uninvested cash buffer (5%)")
    max_single_asset_weight: float = Field(default=0.15, ge=0.01, le=1.0, description="Max single position weight (15%)")
    volatility_lookback_days: int = Field(default=20, ge=5, le=252, description="Rolling volatility window")
    risk_budget_method: RiskBudgetMethod = RiskBudgetMethod.EQUAL_RISK_CONTRIBUTION


class RiskOptimizationResult(BaseModel):
    """
    Audit trace of an automated volatility-targeted and risk-budgeted rebalance.
    """
    optimization_id: str = Field(default_factory=lambda: f"opt-{uuid.uuid4().hex[:8]}")
    baseline_volatility: float = 0.0
    optimized_volatility: float = 0.0
    target_volatility: float = 0.15
    volatility_scalar: float = 1.0
    baseline_weights: Dict[str, float] = Field(default_factory=dict)
    optimized_weights: Dict[str, float] = Field(default_factory=dict)
    risk_budget_allocations: Dict[str, float] = Field(default_factory=dict)
    cash_allocation: float = 0.05
    risk_gates_cleared: bool = True
    violations_prevented: List[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Statistical Walk-Forward Validation Models ──────────────────────────────

class WalkForwardOptimizationReport(BaseModel):
    """
    Rigorous out-of-sample comparison of baseline vs risk-optimized allocations.
    """
    report_id: str = Field(default_factory=lambda: f"wfr-{uuid.uuid4().hex[:8]}")
    splits_count: int = 0
    baseline_sharpe: float = 0.0
    optimized_sharpe: float = 0.0
    sharpe_delta: float = 0.0
    baseline_max_drawdown: float = 0.0
    optimized_max_drawdown: float = 0.0
    drawdown_reduction: float = 0.0
    information_ratio: float = 0.0
    tracking_error: float = 0.0
    t_statistic: float = 0.0
    p_value: float = 1.0
    is_statistically_improved: bool = False
    validation_passed: bool = True
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
