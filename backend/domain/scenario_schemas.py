"""
Phase 6.7 — Scenario & Stress Testing Domain Schemas

Strongly typed domain models for hypothetical scenario definitions,
position impacts, portfolio stress impacts, stop-loss interactions,
conviction context, scenario severity, stress scores, resilience classification,
and scenario matrices.
"""

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field, model_validator

from backend.domain.regime_schemas import OverallMarketRegime


SCENARIO_ENGINE_VERSION = "6.7.0"


# ── Enums ───────────────────────────────────────────────────────────────────

class ScenarioType(str, Enum):
    """Categorization of supported hypothetical stress scenarios."""
    MARKET_CRASH = "MARKET_CRASH"
    MARKET_RALLY = "MARKET_RALLY"
    VOLATILITY_SPIKE = "VOLATILITY_SPIKE"
    SECTOR_SHOCK = "SECTOR_SHOCK"
    STOCK_SHOCK = "STOCK_SHOCK"
    GAP_DOWN = "GAP_DOWN"
    GAP_UP = "GAP_UP"
    REGIME_CHANGE = "REGIME_CHANGE"
    PORTFOLIO_DRAWDOWN = "PORTFOLIO_DRAWDOWN"
    LIQUIDITY_STRESS = "LIQUIDITY_STRESS"


class ScenarioSeverity(str, Enum):
    """Deterministic severity grading of the scenario condition."""
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    SEVERE = "SEVERE"
    EXTREME = "EXTREME"


class ScenarioResilience(str, Enum):
    """Assessment of how well the position and portfolio withstand stress."""
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    FRAGILE = "FRAGILE"
    UNKNOWN = "UNKNOWN"


class ScenarioDataQuality(str, Enum):
    """Quality and completeness of the data underlying scenario evaluation."""
    FRESH = "FRESH"
    STALE = "STALE"
    PARTIAL = "PARTIAL"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


# ── Scenario Definition ─────────────────────────────────────────────────────

class ScenarioDefinition(BaseModel):
    """
    Explicit, inspectable parameters defining a hypothetical stress scenario.
    No hidden assumptions or invented parameters.
    """
    scenario_type: ScenarioType
    name: str
    description: str = ""

    # Explicit Numerical Shock Parameters
    market_return_shock: Optional[float] = Field(
        default=None,
        description="Hypothetical broad market return shock fraction (e.g. -0.10 for -10%)"
    )
    stock_return_shock: Optional[float] = Field(
        default=None,
        description="Hypothetical candidate stock-specific shock fraction (e.g. -0.12 for -12%)"
    )
    opening_price_shock: Optional[float] = Field(
        default=None,
        description="Hypothetical overnight gap opening shock fraction (e.g. -0.08 for -8%)"
    )
    volatility_multiplier: Optional[float] = Field(
        default=None,
        description="Hypothetical volatility expansion factor (e.g. 1.5 for +50% volatility)"
    )
    sector_return_shock: Optional[float] = Field(
        default=None,
        description="Hypothetical sector-specific shock fraction (e.g. -0.15 for -15%)"
    )
    target_regime: Optional[OverallMarketRegime] = Field(
        default=None,
        description="Hypothetical market regime state"
    )
    liquidity_multiplier: Optional[float] = Field(
        default=None,
        description="Hypothetical volume/liquidity scale factor (e.g. 0.5 for 50% drop)"
    )
    assumptions: Dict[str, Any] = Field(
        default_factory=dict,
        description="Explicit metadata and correlation assumptions (OBSERVED vs ASSUMED)"
    )

    @model_validator(mode="after")
    def validate_parameters(self) -> "ScenarioDefinition":
        """Strict parameter validation against corrupted or impossible inputs."""
        for field_name in ("market_return_shock", "stock_return_shock", "opening_price_shock", "sector_return_shock"):
            val = getattr(self, field_name)
            if val is not None:
                if math.isnan(val) or math.isinf(val):
                    raise ValueError(f"{field_name} must be a finite number.")
                if val < -1.0:
                    raise ValueError(f"{field_name} cannot represent a loss greater than -100% (-1.0).")

        if self.volatility_multiplier is not None:
            if math.isnan(self.volatility_multiplier) or math.isinf(self.volatility_multiplier):
                raise ValueError("volatility_multiplier must be a finite number.")
            if self.volatility_multiplier <= 0.0:
                raise ValueError("volatility_multiplier must be strictly positive.")

        if self.liquidity_multiplier is not None:
            if math.isnan(self.liquidity_multiplier) or math.isinf(self.liquidity_multiplier):
                raise ValueError("liquidity_multiplier must be a finite number.")
            if self.liquidity_multiplier < 0.0:
                raise ValueError("liquidity_multiplier cannot be negative.")

        return self


# ── Impact Models ───────────────────────────────────────────────────────────

class PositionImpact(BaseModel):
    """Deterministic valuation and P&L impact on candidate position under stress."""
    symbol: str
    baseline_price: float = 0.0
    stressed_price: float = 0.0
    quantity: float = 0.0
    baseline_value: float = 0.0
    stressed_value: float = 0.0
    absolute_pnl_change: float = 0.0
    pct_change: float = 0.0
    exposure_after: float = 0.0


class PortfolioImpact(BaseModel):
    """Deterministic valuation and drawdown impact on overall portfolio under stress."""
    baseline_equity: float = 0.0
    stressed_equity: float = 0.0
    absolute_loss_gain: float = 0.0
    pct_drawdown: float = 0.0
    affected_positions: List[str] = Field(default_factory=list)
    sector_impact: Dict[str, float] = Field(default_factory=dict)
    concentration_impact: Dict[str, float] = Field(default_factory=dict)


class StopLossInteraction(BaseModel):
    """
    Interaction analysis between hypothetical price and stop-loss levels.
    Distinguishes stop trigger level from actual execution price during gaps.
    """
    stop_loss_price: Optional[float] = None
    scenario_price: float = 0.0
    stop_triggered: bool = False
    gap_through: bool = False
    potential_slippage: float = 0.0
    execution_price_estimate: float = 0.0
    description: str = ""


class ConvictionScenarioContext(BaseModel):
    """
    Evaluates scenario impact on conviction without mutating the baseline score.
    """
    baseline_conviction: float = 0.0
    scenario_resilience: ScenarioResilience = ScenarioResilience.UNKNOWN
    scenario_adjusted_conviction: float = 0.0
    explanation: str = ""


# ── Scenario Result Model ───────────────────────────────────────────────────

class ScenarioResult(BaseModel):
    """
    Complete deterministic evaluation of a single hypothetical stress scenario.
    Preserves immutable baseline state while reporting hypothetical stressed state.
    Supports dual synchronous and awaitable invocation.
    """
    scenario_id: str = Field(default_factory=lambda: f"scen-{uuid.uuid4().hex[:8]}")
    scenario_type: ScenarioType
    scenario_version: str = SCENARIO_ENGINE_VERSION
    context_id: str
    portfolio_id: Optional[str] = None
    candidate_symbol: str

    # State Tracking (Strictly Separated)
    baseline_state: Dict[str, Any] = Field(default_factory=dict)
    stressed_state: Dict[str, Any] = Field(default_factory=dict)
    market_impact: Dict[str, Any] = Field(default_factory=dict)

    # Specific Impact Assessments
    position_impact: PositionImpact
    portfolio_impact: PortfolioImpact
    risk_limit_breaches: List[str] = Field(default_factory=list)
    stop_loss_interaction: StopLossInteraction
    conviction_context: ConvictionScenarioContext
    regime_context: Dict[str, Any] = Field(default_factory=dict)

    # High-level Stress & Resilience Metrics
    severity: ScenarioSeverity = ScenarioSeverity.MODERATE
    stress_score: float = Field(default=0.0, ge=0.0, le=1.0)
    resilience: ScenarioResilience = ScenarioResilience.UNKNOWN
    data_quality: ScenarioDataQuality = ScenarioDataQuality.FRESH

    # Audit & Provenance
    warnings: List[str] = Field(default_factory=list)
    provenance: List[Dict[str, Any]] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def __await__(self):
        """Allows dual synchronous or awaitable invocation."""
        async def _passthrough():
            return self
        return _passthrough().__await__()


# ── Scenario Comparison & Matrix Models ─────────────────────────────────────

class ScenarioComparison(BaseModel):
    """
    Structured comparison of candidate and portfolio behavior across multiple scenarios.
    Does not aggregate into probability-weighted expected values unless probabilities are provided.
    Supports dual synchronous and awaitable invocation.
    """
    comparison_id: str = Field(default_factory=lambda: f"comp-{uuid.uuid4().hex[:8]}")
    candidate_symbol: str
    context_id: str
    portfolio_id: Optional[str] = None
    scenarios: Dict[str, ScenarioResult] = Field(default_factory=dict)
    worst_case_scenario: Optional[str] = None
    most_resilient_scenario: Optional[str] = None
    overall_resilience: ScenarioResilience = ScenarioResilience.UNKNOWN
    summary: str = ""
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def __await__(self):
        """Allows dual synchronous or awaitable invocation."""
        async def _passthrough():
            return self
        return _passthrough().__await__()


class ScenarioMatrixRow(BaseModel):
    """Single row in a scenario stress matrix."""
    scenario_name: str
    scenario_type: ScenarioType
    candidate_pnl_pct: float
    portfolio_drawdown_pct: float
    stop_breached: bool
    risk_breaches: int
    severity: ScenarioSeverity
    resilience: ScenarioResilience


class ScenarioMatrix(BaseModel):
    """
    Tabular scenario impact matrix summarizing multi-scenario stress tests.
    Supports dual synchronous and awaitable invocation.
    """
    candidate_symbol: str
    context_id: str
    rows: List[ScenarioMatrixRow] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def __await__(self):
        """Allows dual synchronous or awaitable invocation."""
        async def _passthrough():
            return self
        return _passthrough().__await__()
