"""
Phase 25 — Strategy Robustness, Regime Analysis & Monte Carlo Validation Domain Schemas

Strongly typed domain models for parameter sensitivity surfaces, market regime attributions,
Monte Carlo trade-sequence resampling, bootstrap confidence intervals, execution-friction stress tests,
market stress scenarios, symbol concentration, leave-one-out cross validation, overfitting detection,
and the Unified Robustness Scorecard.

Safety Invariant:
- STRICTLY RESEARCH / HISTORICAL / PAPER SIMULATION / VALIDATION.
- Zero live-money order submission authority.
- TIER_4_LIVE_REAL_MONEY remains permanently locked, unroutable, and fail-closed.
"""

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field, model_validator


ROBUSTNESS_SCHEMA_VERSION = "25.0.0"


# ── Enums ───────────────────────────────────────────────────────────────────

class RobustnessClassification(str, Enum):
    """Deterministic classification of strategy robustness based on measurable criteria."""
    ROBUST = "ROBUST"
    MODERATELY_ROBUST = "MODERATELY_ROBUST"
    FRAGILE = "FRAGILE"
    UNRELIABLE = "UNRELIABLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class FrictionStressLevel(str, Enum):
    """Stress testing tier for execution frictions (slippage, brokerage, taxes)."""
    BASELINE = "BASELINE"
    MILD_STRESS = "MILD_STRESS"
    MODERATE_STRESS = "MODERATE_STRESS"
    SEVERE_STRESS = "SEVERE_STRESS"


class MarketRegimeType(str, Enum):
    """Deterministic Point-in-Time market regime classification."""
    BULL_TRENDING = "BULL_TRENDING"
    BEAR_TRENDING = "BEAR_TRENDING"
    SIDEWAYS_RANGING = "SIDEWAYS_RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    UNKNOWN = "UNKNOWN"


class StressScenarioType(str, Enum):
    """Hypothetical stress scenario definition."""
    VOLATILITY_SHOCK = "VOLATILITY_SHOCK"
    GAP_DOWN = "GAP_DOWN"
    RAPID_REVERSAL = "RAPID_REVERSAL"
    LIQUIDITY_CONTRACTION = "LIQUIDITY_CONTRACTION"


# ── Parameter Sensitivity Models (Step 3) ───────────────────────────────────

class ParameterSensitivityPoint(BaseModel):
    """Individual evaluation point on a parameter variation curve."""
    parameter_name: str
    parameter_value: Any
    total_return_pct: float = 0.0
    sharpe_ratio: Optional[float] = None
    max_drawdown_pct: float = 0.0
    win_rate_pct: float = 0.0
    trade_count: int = 0


class ParameterSensitivitySurface(BaseModel):
    """Sensitivity evaluation across variations of a single strategy parameter."""
    parameter_name: str
    baseline_value: Any
    evaluated_points: List[ParameterSensitivityPoint] = Field(default_factory=list)
    performance_cliff_detected: bool = Field(
        default=False,
        description="True if small parameter shift causes >50% performance drop",
    )
    stable_region_span: str = Field(default="", description="Description of contiguous stable parameter band")
    stability_score: float = Field(default=0.0, ge=0.0, le=100.0, description="0 to 100 stability score")


# ── Market Regime Analysis Models (Step 4) ───────────────────────────────────

class RegimePerformanceAttribution(BaseModel):
    """Performance attribution for trades executing during a specific market regime."""
    regime_type: MarketRegimeType
    bars_count: int = 0
    trades_count: int = 0
    total_return_pct: float = 0.0
    win_rate_pct: float = 0.0
    profit_factor: Optional[float] = None
    max_drawdown_pct: float = 0.0
    sharpe_ratio: Optional[float] = None
    exposure_pct: float = 0.0
    is_failing_regime: bool = False


# ── Monte Carlo & Bootstrap Resampling Models (Step 5 & 6) ──────────────────

class MonteCarloPercentiles(BaseModel):
    """
    Deterministic percentiles from seeded Monte Carlo trade sequence resampling.
    Zero LLM numerical hallucination; pure-Python statistics.
    """
    iteration_count: int = 500
    seed: int = 42
    # Final equity percentiles
    equity_p5: float = 0.0
    equity_p25: float = 0.0
    equity_p50: float = 0.0
    equity_p75: float = 0.0
    equity_p95: float = 0.0
    # Return % percentiles
    return_p5: float = 0.0
    return_p25: float = 0.0
    return_p50: float = 0.0
    return_p75: float = 0.0
    return_p95: float = 0.0
    # Max drawdown % percentiles
    drawdown_p5: float = 0.0
    drawdown_p50: float = 0.0
    drawdown_p95: float = 0.0
    # Risk metrics
    longest_losing_streak_p95: int = 0
    worst_drawdown_pct: float = 0.0
    probability_of_net_loss: float = Field(default=0.0, ge=0.0, le=1.0)
    probability_of_drawdown_over_10pct: float = Field(default=0.0, ge=0.0, le=1.0)
    insufficient_data: bool = False


class BootstrapConfidenceInterval(BaseModel):
    """Bootstrap resampling 95% confidence intervals for a performance metric."""
    metric_name: str
    sample_size: int
    bootstrap_iterations: int = 500
    mean_estimate: float = 0.0
    std_error: float = 0.0
    ci_lower_95: float = 0.0
    ci_upper_95: float = 0.0
    confidence_level: float = 0.95
    insufficient_data: bool = False


# ── Stress Testing Models (Step 7 & 8) ───────────────────────────────────────

class FrictionStressResult(BaseModel):
    """Outcome of stress testing under adverse transaction friction assumptions."""
    stress_level: FrictionStressLevel
    slippage_pct: float
    brokerage_pct: float
    stt_tax_pct: float
    total_roundtrip_cost_pct: float
    total_return_pct: float
    return_degradation_pct: float = 0.0
    sharpe_ratio: Optional[float] = None
    sharpe_degradation_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    is_profitable: bool = True
    break_even_slippage_pct: Optional[float] = None


class MarketStressResult(BaseModel):
    """Outcome of applying deterministic historical stress scenarios."""
    scenario_type: StressScenarioType
    description: str
    baseline_return_pct: float
    stressed_return_pct: float
    performance_degradation_pct: float
    max_drawdown_pct: float
    passed: bool = True


# ── Universe & Symbol Robustness (Step 9) ───────────────────────────────────

class SymbolContribution(BaseModel):
    """Performance and risk contribution of an individual symbol in the universe."""
    symbol: str
    trades_count: int = 0
    realized_pnl: float = 0.0
    contribution_to_total_return_pct: float = 0.0
    win_rate_pct: float = 0.0
    max_drawdown_pct: float = 0.0


class LeaveOneOutResult(BaseModel):
    """Evaluation when one symbol is omitted from the multi-symbol universe."""
    omitted_symbol: str
    remaining_symbols: List[str]
    total_return_pct: float
    return_delta_from_baseline_pct: float
    is_viable: bool = True


# ── Overfitting & Scorecard Models (Step 11 & 12) ───────────────────────────

class OverfittingAssessment(BaseModel):
    """Transparent deterministic multi-factor overfitting assessment."""
    classification: RobustnessClassification
    out_of_sample_to_in_sample_return_ratio: Optional[float] = None
    out_of_sample_to_in_sample_sharpe_ratio: Optional[float] = None
    parameter_cliff_detected: bool = False
    symbol_concentration_detected: bool = False
    dominant_symbol_share_pct: float = 0.0
    regime_dependency_detected: bool = False
    tail_risk_acceptable: bool = True
    insufficient_sample_size: bool = False
    primary_risks: List[str] = Field(default_factory=list)


class ScorecardCategory(BaseModel):
    """Evaluation score and evidence for one of the 12 robustness dimensions."""
    category_name: str
    score: float = Field(ge=0.0, le=100.0)
    weight: float = Field(default=1.0, ge=0.1)
    passed: bool = True
    evidence: str = ""
    key_metrics: Dict[str, Any] = Field(default_factory=dict)
    insufficient_data: bool = False


class RobustnessScorecard(BaseModel):
    """
    Unified 12-Category Strategy Robustness Scorecard.
    Translates empirical empirical evidence into an auditable 0–100 score.
    """
    overall_score: float = Field(default=0.0, ge=0.0, le=100.0)
    classification: RobustnessClassification
    categories: List[ScorecardCategory] = Field(default_factory=list)
    primary_weaknesses: List[str] = Field(default_factory=list)
    strongest_evidence: List[str] = Field(default_factory=list)
    explicit_limitations: List[str] = Field(default_factory=list)


# ── Master Request & Report Containers ──────────────────────────────────────

class RobustnessAnalysisRequest(BaseModel):
    """Payload for triggering a full strategy robustness analysis."""
    symbols: List[str] = Field(default_factory=lambda: ["TCS.NS", "RELIANCE.NS", "INFY.NS"])
    bars_per_symbol: int = Field(default=40, ge=15, le=500)
    dataset: Optional[Dict[str, List[Dict[str, Any]]]] = None
    monte_carlo_iterations: int = Field(default=500, ge=50, le=2000)
    seed: int = 42


class RobustnessAnalysisReport(BaseModel):
    """
    Master report container for Phase 25 strategy robustness analysis.
    Fully serializable, deterministic, and auditable.
    """
    analysis_id: str = Field(default_factory=lambda: f"rob-{uuid.uuid4().hex[:8]}")
    run_id: str
    dataset_fingerprint: str
    config_fingerprint: str
    seed: int
    symbols: List[str]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Detailed Sub-Reports
    sensitivity: List[ParameterSensitivitySurface] = Field(default_factory=list)
    regimes: List[RegimePerformanceAttribution] = Field(default_factory=list)
    monte_carlo: MonteCarloPercentiles = Field(default_factory=MonteCarloPercentiles)
    bootstrap: List[BootstrapConfidenceInterval] = Field(default_factory=list)
    friction_stress: List[FrictionStressResult] = Field(default_factory=list)
    market_stress: List[MarketStressResult] = Field(default_factory=list)
    symbol_contributions: List[SymbolContribution] = Field(default_factory=list)
    leave_one_out: List[LeaveOneOutResult] = Field(default_factory=list)
    overfitting: OverfittingAssessment = Field(default_factory=lambda: OverfittingAssessment(classification=RobustnessClassification.INSUFFICIENT_DATA))
    scorecard: RobustnessScorecard = Field(default_factory=lambda: RobustnessScorecard(overall_score=0.0, classification=RobustnessClassification.INSUFFICIENT_DATA))

    audit_status: str = "VALID"
    mode: str = "RESEARCH_VALIDATION_SIMULATION"
    tier_4_live_real_money_locked: bool = True
