"""
Phase 6.9 — Execution Safety & Order Routing Pre-Flight Domain Schemas

Strongly typed domain models for order pre-flight validation, exchange trading constraints,
pre-flight check results, and immutable execution authorization snapshots.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import math
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field, model_validator


PREFLIGHT_ENGINE_VERSION = "6.9.0"


# ── Enums ───────────────────────────────────────────────────────────────────

class PreflightStatus(str, Enum):
    """Categorical result of the pre-flight gatekeeper evaluation."""
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    INVALID = "INVALID"
    RISK_VETO = "RISK_VETO"
    INSUFFICIENT_MARGIN = "INSUFFICIENT_MARGIN"
    INVALID_QUANTITY = "INVALID_QUANTITY"
    INVALID_PRICE = "INVALID_PRICE"
    DUPLICATE = "DUPLICATE"
    CIRCUIT_LIMIT = "CIRCUIT_LIMIT"
    MARKET_CLOSED = "MARKET_CLOSED"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
    
    # Phase 39 statuses
    CAPITAL_REJECTED = "CAPITAL_REJECTED"
    EXPOSURE_REJECTED = "EXPOSURE_REJECTED"
    BROKER_CAPABILITY_REJECTED = "BROKER_CAPABILITY_REJECTED"
    SAFETY_GATE_BLOCKED = "SAFETY_GATE_BLOCKED"


class PreflightOrderType(str, Enum):
    """Supported order types for execution pre-flight."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class PreflightSide(str, Enum):
    """Order trade side."""
    BUY = "BUY"
    SELL = "SELL"


# ── Order Request & Constraint Models ───────────────────────────────────────

class PreflightOrderRequest(BaseModel):
    """
    Strongly typed order execution request bound to an approved trading decision.
    Must be fully validated before any future broker dispatch.
    """
    order_id: str = Field(default_factory=lambda: f"ord-{uuid.uuid4().hex[:8]}")
    decision_id: str
    symbol: str
    side: PreflightSide
    order_type: PreflightOrderType = PreflightOrderType.LIMIT
    quantity: float = Field(gt=0)
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    portfolio_id: Optional[str] = None
    strategy_id: Optional[str] = None
    conviction: Optional[float] = None
    risk_snapshot_id: Optional[str] = None
    sizing_snapshot_id: Optional[str] = None
    source: str = "TRADING_OS"
    idempotency_token: Optional[str] = None

    def generate_idempotency_token(self) -> str:
        """
        Generate a deterministic idempotency token based on stable execution identity.
        Zero randomness.
        """
        token_src = (
            f"{self.decision_id}|{self.symbol}|{self.side.value}|"
            f"{round(self.quantity, 4)}|{self.order_type.value}|"
            f"{self.portfolio_id or 'DEFAULT'}"
        )
        return hashlib.sha256(token_src.encode("utf-8")).hexdigest()


class ExchangeTradingConstraints(BaseModel):
    """
    Exchange and market microstructure constraints.
    """
    tick_size: float = Field(default=0.05, gt=0.0, description="Minimum price increment (e.g. 0.05 for NSE)")
    lot_size: int = Field(default=1, ge=1, description="Minimum traded quantity multiplier")
    min_quantity: int = Field(default=1, ge=1, description="Minimum order quantity")
    max_quantity: int = Field(default=50000, ge=1, description="Maximum single order quantity limit")
    circuit_lower_limit: Optional[float] = None
    circuit_upper_limit: Optional[float] = None
    max_price_deviation_pct: float = Field(default=0.05, ge=0.0, description="Max acceptable deviation from quote (5%)")
    market_hours_open: bool = True

    @model_validator(mode="after")
    def validate_constraints(self) -> "ExchangeTradingConstraints":
        """Validate exchange constraint bounds."""
        if math.isnan(self.tick_size) or math.isinf(self.tick_size) or self.tick_size <= 0:
            raise ValueError("tick_size must be a strictly positive finite number.")
        if self.lot_size <= 0:
            raise ValueError("lot_size must be a positive integer.")
        return self


# ── Audit & Authorization Models ────────────────────────────────────────────

class PreflightCheckResult(BaseModel):
    """Result of an individual pre-flight gatekeeper verification step."""
    check_name: str
    passed: bool
    message: str
    failure_status: Optional[PreflightStatus] = None


class ExecutionAuthorizationSnapshot(BaseModel):
    """
    Immutable, frozen execution authorization record produced only upon approval.
    This snapshot is the exact artifact consumed by a future broker adapter.
    """
    model_config = {"frozen": True}

    authorization_id: str
    decision_id: str
    order_id: str
    symbol: str
    side: PreflightSide
    approved_quantity: int
    normalized_limit_price: Optional[float] = None
    normalized_stop_price: Optional[float] = None
    normalized_target_price: Optional[float] = None
    risk_state: Dict[str, Any] = Field(default_factory=dict)
    validation_timestamp: datetime
    data_freshness: str = "FRESH"
    circuit_limit_checked: bool = True
    preflight_approved: bool = True
    idempotency_token: str
    engine_version: str = PREFLIGHT_ENGINE_VERSION


class ExecutionPreflightResult(BaseModel):
    """
    Complete outcome container of the pre-flight gatekeeper evaluation.
    Supports dual synchronous and awaitable invocation.
    """
    preflight_id: str = Field(default_factory=lambda: f"pre-{uuid.uuid4().hex[:8]}")
    status: PreflightStatus
    order_request: PreflightOrderRequest
    checks: List[PreflightCheckResult] = Field(default_factory=list)
    passed_checks: List[str] = Field(default_factory=list)
    failed_checks: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    authorization: Optional[ExecutionAuthorizationSnapshot] = None
    idempotency_token: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data_quality: str = "FRESH"
    
    # Phase 39 additions
    capital_summary: Dict[str, Any] = Field(default_factory=dict)
    risk_summary: Dict[str, Any] = Field(default_factory=dict)
    market_data_status: str = "UNKNOWN"
    broker_capability_result: Dict[str, Any] = Field(default_factory=dict)
    safety_state: str = "SECURE"
    reason_codes: List[str] = Field(default_factory=list)
    audit_correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    def __await__(self):
        """Allows dual synchronous or awaitable invocation."""
        async def _passthrough():
            return self
        return _passthrough().__await__()
