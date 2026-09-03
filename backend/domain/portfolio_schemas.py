"""
Phase 6.6 — Portfolio Intelligence Foundation Domain Schemas

Strongly typed domain models for portfolio state representation, sector exposures,
concentration analysis (HHI), correlation analysis, marginal trade impact,
diversification evaluation, and configurable portfolio risk constraints.
"""

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field, model_validator

from backend.domain.regime_schemas import MarketRegime


PORTFOLIO_ENGINE_VERSION = "6.6.0"


# ── Data Quality ─────────────────────────────────────────────────────────────

class PortfolioDataQuality(str, Enum):
    """Freshness and completeness status of portfolio state."""
    FRESH = "FRESH"
    RECENT = "RECENT"
    STALE = "STALE"
    PARTIAL = "PARTIAL"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


# ── Position Model ───────────────────────────────────────────────────────────

class PortfolioPosition(BaseModel):
    """
    Detailed intelligence position record with valuation, sector metadata,
    and portfolio weighting.
    """
    symbol: str
    quantity: float = 0.0
    average_price: float = 0.0
    current_price: float = 0.0
    market_value: float = 0.0
    weight: float = Field(default=0.0, ge=0.0, le=1.0, description="Fraction of total equity")
    sector: str = "UNKNOWN"
    asset_class: str = "EQUITY"
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    volatility: Optional[float] = None
    beta: Optional[float] = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Sector & Concentration Models ────────────────────────────────────────────

class SectorExposure(BaseModel):
    """Aggregate sector exposure metrics within the active portfolio."""
    sector: str
    market_value: float = 0.0
    weight_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="Percentage of total equity (0-100)")
    position_count: int = 0
    symbols: List[str] = Field(default_factory=list)


class ConcentrationMetric(BaseModel):
    """
    Deterministic concentration analysis including Top holdings share and
    the Herfindahl-Hirschman Index (HHI).
    """
    top_position_weight: float = 0.0
    top_3_weight: float = 0.0
    top_5_weight: float = 0.0
    hhi_index: float = Field(default=0.0, description="Sum of squared weights (0 to 10,000)")
    concentration_risk_level: str = "LOW"  # LOW, MODERATE, HIGH, EXTREME
    max_position_limit: float = 0.10
    max_sector_limit: float = 0.30
    passed: bool = True
    warnings: List[str] = Field(default_factory=list)


# ── Correlation & Marginal Exposure ──────────────────────────────────────────

class CorrelationMetric(BaseModel):
    """
    Deterministic correlation analysis across portfolio holdings and candidate stock.
    Computed via pure Python Pearson math from historical return series.
    """
    candidate_symbol: str
    avg_correlation_to_portfolio: Optional[float] = None
    max_correlated_symbol: Optional[str] = None
    max_correlation: Optional[float] = None
    correlation_matrix: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    available: bool = True
    unavailable_reason: str = ""


class MarginalExposure(BaseModel):
    """
    Incremental portfolio impact analysis answering:
    'What changes in portfolio exposure and concentration if this candidate is added?'
    """
    candidate_symbol: str
    proposed_quantity: float = 0.0
    proposed_notional: float = 0.0
    current_portfolio_exposure_pct: float = 0.0
    proposed_portfolio_exposure_pct: float = 0.0
    incremental_exposure_pct: float = 0.0
    sector_exposure_before_pct: float = 0.0
    sector_exposure_after_pct: float = 0.0
    concentration_hhi_before: float = 0.0
    concentration_hhi_after: float = 0.0
    risk_impact_summary: str = ""


class DiversificationStatus(BaseModel):
    """
    Evaluation of diversification benefits or risks introduced by candidate.
    """
    increases_concentration: bool = False
    adds_new_sector: bool = False
    adds_correlated_exposure: bool = False
    diversification_score: float = Field(default=0.5, ge=0.0, le=1.0)
    summary: str = ""


# ── Portfolio Constraints ───────────────────────────────────────────────────

class PortfolioConstraintConfig(BaseModel):
    """
    Explicit, configurable limits for portfolio risk and concentration management.
    """
    max_position_weight: float = Field(default=0.10, gt=0.0, le=1.0)
    max_sector_weight: float = Field(default=0.30, gt=0.0, le=1.0)
    max_portfolio_exposure: float = Field(default=0.80, gt=0.0, le=1.0)
    max_correlated_exposure: float = Field(default=0.40, gt=0.0, le=1.0)
    max_positions: int = Field(default=20, gt=0)
    min_cash_reserve_pct: float = Field(default=0.10, ge=0.0, le=1.0)


class PortfolioConstraintEvaluation(BaseModel):
    """Evaluation trace of an individual portfolio constraint check."""
    constraint_name: str
    passed: bool
    limit_value: float
    actual_value: float
    description: str = ""
    action_suggested: str = "ALLOW"  # ALLOW, WARN, SIZE_DOWN, VETO


# ── Portfolio Intelligence Result ───────────────────────────────────────────

class PortfolioIntelligence(BaseModel):
    """
    Comprehensive portfolio intelligence evaluation produced by PortfolioIntelligenceEngine.
    Provides portfolio-level context and constraint evaluations to RiskEngine.
    Supports dual synchronous and awaitable invocation.
    """
    portfolio_id: str
    context_id: str
    total_equity: float = 0.0
    cash: float = 0.0
    available_cash: float = 0.0
    total_market_value: float = 0.0
    total_exposure_pct: float = 0.0
    position_count: int = 0

    positions: Dict[str, PortfolioPosition] = Field(default_factory=dict)
    sector_exposures: Dict[str, SectorExposure] = Field(default_factory=dict)
    concentration: ConcentrationMetric = Field(default_factory=ConcentrationMetric)
    correlation: CorrelationMetric = Field(default_factory=lambda: CorrelationMetric(candidate_symbol=""))
    marginal_exposure: Optional[MarginalExposure] = None
    diversification: Optional[DiversificationStatus] = None
    constraints_evaluated: List[PortfolioConstraintEvaluation] = Field(default_factory=list)

    data_quality: PortfolioDataQuality = PortfolioDataQuality.FRESH
    warnings: List[str] = Field(default_factory=list)
    provenance: List[Dict[str, Any]] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    engine_version: str = PORTFOLIO_ENGINE_VERSION

    def __await__(self):
        """Allows dual synchronous or awaitable invocation."""
        async def _passthrough():
            return self
        return _passthrough().__await__()


# ── Unified Market & Portfolio Intelligence Envelope ────────────────────────

class MarketPortfolioIntelligence(BaseModel):
    """
    Unified intelligence package combining MarketRegime and PortfolioIntelligence.
    Acts as the standard input boundary to RiskEngine and position sizing.
    Supports dual synchronous and awaitable invocation.
    """
    context_id: str
    symbol: str
    portfolio_id: Optional[str] = None
    market_regime: MarketRegime
    portfolio_intelligence: Optional[PortfolioIntelligence] = None
    contextual_summary: str = ""
    contextual_warnings: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def __await__(self):
        """Allows dual synchronous or awaitable invocation."""
        async def _passthrough():
            return self
        return _passthrough().__await__()
