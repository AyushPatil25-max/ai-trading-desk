"""
Phase 6.6 — Market Regime Detection Domain Schemas

Strongly typed domain models for multi-dimensional market regime classification,
deterministic metric provenance, regime transition tracking, relative strength,
and stock-vs-market alignment.
"""

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field, model_validator


REGIME_ENGINE_VERSION = "6.6.0"


# ── Regime Enums ─────────────────────────────────────────────────────────────

class MarketTrendRegime(str, Enum):
    """Directional trend of the broader market / benchmark."""
    BULL = "BULL"
    BEAR = "BEAR"
    SIDEWAYS = "SIDEWAYS"
    UNKNOWN = "UNKNOWN"


class MarketVolatilityRegime(str, Enum):
    """Realized and percentile volatility state of the market."""
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    EXTREME = "EXTREME"
    UNKNOWN = "UNKNOWN"


class MarketBreadthRegime(str, Enum):
    """Market breadth participation (advance/decline, sector breadth)."""
    STRONG = "STRONG"
    NEUTRAL = "NEUTRAL"
    WEAK = "WEAK"
    UNKNOWN = "UNKNOWN"


class MarketMomentumRegime(str, Enum):
    """Velocity and rate of change of the broader market."""
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"
    UNKNOWN = "UNKNOWN"


class MarketLiquidityRegime(str, Enum):
    """Market liquidity / volume regime."""
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class MarketStressLevel(str, Enum):
    """Degree of systemic market stress (tail drawdowns, volatility spikes)."""
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    SEVERE = "SEVERE"
    UNKNOWN = "UNKNOWN"


class OverallMarketRegime(str, Enum):
    """Synthesized overall market regime state."""
    BULL = "BULL"
    BEAR = "BEAR"
    SIDEWAYS = "SIDEWAYS"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    TRANSITION = "TRANSITION"
    STRESSED = "STRESSED"
    UNKNOWN = "UNKNOWN"


class RegimeAlignment(str, Enum):
    """Relationship between the individual candidate stock and the market regime."""
    ALIGNED_BULL = "ALIGNED_BULL"
    ALIGNED_BEAR = "ALIGNED_BEAR"
    DIVERGENT = "DIVERGENT"
    RELATIVE_STRENGTH_EXCEPTION = "RELATIVE_STRENGTH_EXCEPTION"
    ELEVATED_VOLATILITY_RISK = "ELEVATED_VOLATILITY_RISK"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


class RelativeStrengthStatus(str, Enum):
    """Relative performance classification against benchmark."""
    OUTPERFORMING = "OUTPERFORMING"
    IN_LINE = "IN_LINE"
    UNDERPERFORMING = "UNDERPERFORMING"
    UNKNOWN = "UNKNOWN"


# ── Provenance & Metric Models ───────────────────────────────────────────────

class RegimeMetric(BaseModel):
    """
    Individual deterministic regime metric with full audit provenance.
    Values originate exclusively from Python calculations; never from LLMs.
    """
    metric_name: str
    value: Optional[float] = None
    unit: str = "%"
    period: str = "RECENT"
    source: str = "BENCHMARK"
    calculation_method: str = "DETERMINISTIC"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    available: bool = True
    unavailable_reason: str = ""
    context_id: str = ""


class RegimeTransition(BaseModel):
    """
    Auditable record of a detected regime transition between market states.
    """
    transition_detected: bool = False
    previous_regime: Optional[OverallMarketRegime] = None
    current_regime: OverallMarketRegime = OverallMarketRegime.UNKNOWN
    transition_direction: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Market Regime Assessment ─────────────────────────────────────────────────

class MarketRegime(BaseModel):
    """
    Multi-dimensional market regime evaluation produced deterministically by MarketRegimeEngine.
    Provides broader market context to the Trading OS without overriding hard risk vetoes.
    Supports dual synchronous and awaitable invocation.
    """
    regime_id: str = Field(default_factory=lambda: f"reg-{uuid.uuid4().hex[:8]}")
    context_id: str
    symbol: str
    benchmark_symbol: str = "^NSEI"
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Multi-dimensional regime classification
    trend: MarketTrendRegime = MarketTrendRegime.UNKNOWN
    volatility: MarketVolatilityRegime = MarketVolatilityRegime.UNKNOWN
    breadth: MarketBreadthRegime = MarketBreadthRegime.UNKNOWN
    momentum: MarketMomentumRegime = MarketMomentumRegime.UNKNOWN
    liquidity: MarketLiquidityRegime = MarketLiquidityRegime.UNKNOWN
    stress_level: MarketStressLevel = MarketStressLevel.UNKNOWN
    overall_regime: OverallMarketRegime = OverallMarketRegime.UNKNOWN

    # Distinct regime confidence (NOT investment conviction or risk score)
    market_regime_confidence: float = Field(default=0.50, ge=0.0, le=1.0)

    # Transition tracking
    regime_transition: RegimeTransition = Field(default_factory=RegimeTransition)

    # Stock vs Market contextual comparison
    stock_alignment: RegimeAlignment = RegimeAlignment.UNKNOWN
    relative_strength_status: RelativeStrengthStatus = RelativeStrengthStatus.UNKNOWN
    relative_return: Optional[float] = None
    benchmark_return: Optional[float] = None
    candidate_return: Optional[float] = None

    # Audit & Provenance
    metrics: List[RegimeMetric] = Field(default_factory=list)
    provenance: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    engine_version: str = REGIME_ENGINE_VERSION

    def __await__(self):
        """Allows dual synchronous or awaitable invocation."""
        async def _passthrough():
            return self
        return _passthrough().__await__()
