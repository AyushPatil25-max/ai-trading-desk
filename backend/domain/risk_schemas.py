"""
Phase 6.4 — Risk Management & Position Sizing Domain Schemas

Strongly typed domain models for deterministic risk assessment,
constraint evaluation, stop-loss determination, and position sizing.
"""

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator

from backend.domain.investment_committee_schemas import (
    CommitteeRecommendation,
    DataQualityStatus,
    CommitteeDecision,
)
from backend.domain.debate_schemas import EvidenceReference


# ── Enums ───────────────────────────────────────────────────────────────────

class PositionDirection(str, Enum):
    """Trading direction for position sizing."""
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class StopLossMethod(str, Enum):
    """Method used to derive the stop-loss price."""
    CONFIGURED_PERCENTAGE = "CONFIGURED_PERCENTAGE"
    TECHNICAL_INVALIDATION = "TECHNICAL_INVALIDATION"
    SUPPORT_RESISTANCE = "SUPPORT_RESISTANCE"
    EXPLICIT = "EXPLICIT"
    UNAVAILABLE = "UNAVAILABLE"


class RiskConstraintType(str, Enum):
    """Categories of deterministic risk constraints."""
    MAX_TRADE_RISK = "MAX_TRADE_RISK"
    MAX_POSITION_ALLOCATION = "MAX_POSITION_ALLOCATION"
    MAX_PORTFOLIO_EXPOSURE = "MAX_PORTFOLIO_EXPOSURE"
    MAX_SINGLE_ASSET = "MAX_SINGLE_ASSET"
    MAX_SECTOR_EXPOSURE = "MAX_SECTOR_EXPOSURE"
    MIN_RISK_REWARD = "MIN_RISK_REWARD"
    CONVICTION_THRESHOLD = "CONVICTION_THRESHOLD"
    DATA_QUALITY = "DATA_QUALITY"
    SHORT_POLICY = "SHORT_POLICY"
    PRICE_INTEGRITY = "PRICE_INTEGRITY"
    CAPITAL_INTEGRITY = "CAPITAL_INTEGRITY"
    COMMITTEE_APPROVAL = "COMMITTEE_APPROVAL"
    RISK_VETO = "RISK_VETO"


# ── Configuration & Constraints ─────────────────────────────────────────────

class RiskConstraintResult(BaseModel):
    """Detailed audit trace for a specific risk constraint evaluation."""
    constraint_type: RiskConstraintType
    passed: bool
    limit_value: Optional[float] = None
    actual_value: Optional[float] = None
    action_taken: str = Field(default="NONE", description="e.g. 'ALLOWED', 'SIZED_DOWN', 'VETOED'")
    description: str = ""


class RiskConfiguration(BaseModel):
    """
    Explicit, inspectable risk limits and sizing parameters.
    No silent defaults or invented numbers.
    """
    account_capital: float = Field(default=100000.0, gt=0.0, description="Available account equity/capital in base currency")
    max_portfolio_risk_pct: float = Field(default=0.05, gt=0.0, le=1.0, description="Max total portfolio risk fraction (e.g. 0.05 = 5%)")
    max_trade_risk_pct: float = Field(default=0.01, gt=0.0, le=1.0, description="Max risk budget per single trade (e.g. 0.01 = 1%)")
    max_position_pct: float = Field(default=0.10, gt=0.0, le=1.0, description="Max allocation to a single position (e.g. 0.10 = 10%)")
    max_single_asset_exposure_pct: float = Field(default=0.20, gt=0.0, le=1.0, description="Max aggregate exposure to one asset")
    max_sector_exposure_pct: float = Field(default=0.30, gt=0.0, le=1.0, description="Max exposure to a single industry/sector")
    default_stop_loss_pct: float = Field(default=0.05, gt=0.0, le=0.50, description="Default stop-loss distance fraction (e.g. 0.05 = 5%)")
    minimum_risk_reward_ratio: float = Field(default=1.5, gt=0.0, description="Minimum acceptable reward-to-risk ratio")
    minimum_conviction: float = Field(default=0.35, ge=0.0, le=1.0, description="Minimum conviction score required to size a position")
    max_allowed_risk_score: float = Field(default=0.75, ge=0.0, le=1.0, description="Risk score above which trade is vetoed")
    allow_short: bool = Field(default=False, description="Whether short selling is permitted")
    max_leverage: float = Field(default=1.0, ge=1.0, description="Maximum permitted gross leverage")

    @model_validator(mode="after")
    def validate_config(self) -> "RiskConfiguration":
        if math.isnan(self.account_capital) or math.isinf(self.account_capital) or self.account_capital <= 0:
            raise ValueError("account_capital must be a finite positive number.")
        if math.isnan(self.max_trade_risk_pct) or self.max_trade_risk_pct <= 0 or self.max_trade_risk_pct > self.max_position_pct:
            raise ValueError("max_trade_risk_pct must be positive and cannot exceed max_position_pct.")
        return self


# ── Position Sizing Plan ───────────────────────────────────────────────────

class PositionSizingPlan(BaseModel):
    """
    Validated, auditable position sizing plan produced deterministically by RiskEngine.
    Advisory and planning-only — not an active broker order.
    """
    plan_id: str = Field(description="Unique plan identifier")
    context_id: str = Field(description="Market context ID this plan belongs to")
    symbol: str = Field(description="Ticker symbol")
    run_id: Optional[str] = None
    decision_id: Optional[str] = None

    # Trade Direction & Price Levels
    direction: PositionDirection = Field(default=PositionDirection.FLAT)
    entry_price: float = Field(default=0.0, ge=0.0)
    stop_loss_price: float = Field(default=0.0, ge=0.0)
    take_profit_price: Optional[float] = Field(default=None)

    # Risk Metrics (Pure Python Calculation)
    risk_per_share: float = Field(default=0.0, ge=0.0, description="Absolute risk distance per share |entry - stop|")
    risk_budget: float = Field(default=0.0, ge=0.0, description="Total capital risked on this position")
    risk_per_trade_pct: float = Field(default=0.0, ge=0.0, le=1.0, description="Effective trade risk percentage of capital")

    # Sizing Metrics (Deterministic Flooring)
    position_quantity: int = Field(default=0, ge=0, description="Discrete whole number of shares/units to trade")
    position_notional: float = Field(default=0.0, ge=0.0, description="Notional value = quantity * entry_price")
    exposure_pct: float = Field(default=0.0, ge=0.0, description="Notional value as fraction of account capital")
    risk_reward_ratio: Optional[float] = Field(default=None, description="Calculated reward-to-risk ratio")

    # Methodology & Source Tracking
    sizing_method: str = Field(default="DETERMINISTIC_RISK_BUDGET", description="Formula applied")
    stop_loss_source: str = Field(default="CONFIGURED_PERCENTAGE", description="Level origin description")
    stop_loss_method: StopLossMethod = Field(default=StopLossMethod.CONFIGURED_PERCENTAGE)

    # Audit & Veto
    constraints_applied: List[RiskConstraintResult] = Field(default_factory=list)
    veto_applied: bool = Field(default=False)
    veto_reasons: List[str] = Field(default_factory=list)

    # Upstream Context
    data_quality: DataQualityStatus = Field(default=DataQualityStatus.AVAILABLE)
    conviction_score: float = Field(default=0.0, ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    provenance: List[Dict[str, Any]] = Field(default_factory=list)
    notes: str = Field(default="")

    def __await__(self):
        async def _identity():
            return self
        return _identity().__await__()


class RiskAssessmentResult(BaseModel):
    """
    Top-level container uniting risk evaluation with the executable sizing plan.
    """
    symbol: str
    context_id: str
    decision_id: Optional[str] = None
    is_approved: bool = Field(default=False, description="True if position sizing resulted in actionable quantity > 0")
    plan: PositionSizingPlan
    rejection_summary: Optional[str] = None

    def __await__(self):
        async def _identity():
            return self
        return _identity().__await__()

