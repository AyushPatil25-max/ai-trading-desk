"""
Phase 29 — Strategy Governance Domain Schemas

Strongly-typed Pydantic domain models, enums, and validators for strategy registration,
lifecycle status tracking, signal representation, deterministic deduplication fingerprints,
conflict detection, and governance decisions.

Safety Invariants:
- STRICTLY ADVISORY & GOVERNANCE BOUNDARY: Zero authority to place broker orders.
- Pure Python deterministic validation: Zero LLM math.
- All confidence values must be finite floats within [0.0, 1.0] (no NaN/Inf).
- Signal timestamps and market data timestamps must be fresh.
- TIER_4_LIVE_REAL_MONEY remains permanently locked, unroutable, and fail-closed.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field, field_validator, model_validator


STRATEGY_SCHEMA_VERSION = "29.0.0"


# ── Canonical Enums ───────────────────────────────────────────────────────────

class StrategyStatus(str, Enum):
    """Lifecycle status of a trading strategy."""
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DISABLED = "DISABLED"
    QUARANTINED = "QUARANTINED"


class SignalDirection(str, Enum):
    """Trading signal recommendation direction."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class SignalSource(str, Enum):
    """Provenance/originator of the trading signal."""
    RULE_BASED = "RULE_BASED"
    TECHNICAL = "TECHNICAL"
    FUNDAMENTAL = "FUNDAMENTAL"
    AI_ADVISORY = "AI_ADVISORY"
    MANUAL = "MANUAL"


class GovernanceStatus(str, Enum):
    """Evaluation outcome of a strategy signal by the governance layer."""
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CONFLICTED = "CONFLICTED"
    DUPLICATE = "DUPLICATE"
    QUARANTINED = "QUARANTINED"


# ── Core Domain Models ────────────────────────────────────────────────────────

class StrategySignal(BaseModel):
    """
    Standardized trading signal emitted by an analysis or strategy module.
    Subject to strict deterministic validation before entering the governance gate.
    """
    signal_id: str = Field(default_factory=lambda: f"sig-{uuid.uuid4().hex[:10]}")
    strategy_id: str
    strategy_version: str
    symbol: str
    exchange: str = "NSE"
    direction: SignalDirection
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0")
    source: SignalSource = SignalSource.RULE_BASED
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    market_data_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    quantity: Optional[float] = None
    target_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    rationale: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("confidence")
    @classmethod
    def validate_finite_confidence(cls, v: float) -> float:
        if math.isnan(v) or math.isinf(v):
            raise ValueError("Confidence must be a finite numerical value, cannot be NaN or Inf.")
        if v < 0.0 or v > 1.0:
            raise ValueError("Confidence must be strictly within [0.0, 1.0].")
        return round(float(v), 4)

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        s = v.strip().upper()
        if not s or len(s) < 2:
            raise ValueError("Symbol must be a valid, non-empty ticker string.")
        return s

    @field_validator("exchange")
    @classmethod
    def validate_exchange(cls, v: str) -> str:
        e = v.strip().upper()
        if e not in ("NSE", "BSE", "MCX", "NSE_FNO", "BSE_FNO"):
            raise ValueError(f"Unsupported exchange '{v}'. Must be NSE, BSE, or MCX.")
        return e

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            if math.isnan(v) or math.isinf(v) or v <= 0.0:
                raise ValueError("Quantity must be a positive finite number.")
        return v

    def compute_fingerprint(self) -> str:
        """
        Compute deterministic SHA-256 canonical hash of the signal parameters
        for idempotency and duplicate detection.
        """
        canonical_dict = {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "direction": self.direction.value,
            "quantity": float(self.quantity) if self.quantity is not None else None,
            "market_data_timestamp": self.market_data_timestamp.isoformat(),
        }
        canonical_str = json.dumps(canonical_dict, sort_keys=True)
        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()


class StrategyDefinition(BaseModel):
    """
    Formal configuration and permission boundary for a registered strategy.
    """
    strategy_id: str
    name: str
    version: str = "1.0.0"
    status: StrategyStatus = StrategyStatus.DRAFT
    allowed_instruments: List[str] = Field(default_factory=lambda: ["*"])
    allowed_exchanges: List[str] = Field(default_factory=lambda: ["NSE"])
    max_position_size: float = Field(default=100.0, gt=0.0)
    max_order_value: float = Field(default=100000.0, gt=0.0)
    risk_constraints: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    quarantine_reason: Optional[str] = None
    quarantined_at: Optional[datetime] = None

    @field_validator("strategy_id")
    @classmethod
    def validate_strategy_id(cls, v: str) -> str:
        s = v.strip().lower()
        if not s or len(s) < 2:
            raise ValueError("strategy_id must be a non-empty alphanumeric identifier.")
        return s

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        v_str = v.strip()
        if not v_str:
            raise ValueError("version cannot be empty.")
        return v_str


class StrategyDecision(BaseModel):
    """
    Deterministic governance evaluation outcome for an input StrategySignal.
    Contains decision provenance, admissibility status, rejection details, and risk metadata.
    """
    decision_id: str = Field(default_factory=lambda: f"dec-{uuid.uuid4().hex[:12]}")
    signal: StrategySignal
    governance_status: GovernanceStatus
    is_admissible: bool = False
    rejection_reason: Optional[str] = None
    rejection_details: List[str] = Field(default_factory=list)
    risk_metadata: Dict[str, Any] = Field(default_factory=dict)
    strategy_version: str
    decision_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    fingerprint: str
    conflict_metadata: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def validate_decision_consistency(self) -> "StrategyDecision":
        if self.governance_status == GovernanceStatus.APPROVED:
            if not self.is_admissible:
                raise ValueError("APPROVED decision must have is_admissible=True.")
            if self.rejection_reason is not None:
                raise ValueError("APPROVED decision cannot have rejection_reason.")
        else:
            if self.is_admissible:
                raise ValueError("Non-APPROVED decision must have is_admissible=False.")
            if not self.rejection_reason:
                self.rejection_reason = f"Decision status is {self.governance_status.value}"
        return self


class StrategyConflictRecord(BaseModel):
    """
    Record of a detected conflict between two or more opposing strategy signals.
    """
    conflict_id: str = Field(default_factory=lambda: f"conf-{uuid.uuid4().hex[:8]}")
    symbol: str
    exchange: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    conflicting_signals: List[Dict[str, Any]] = Field(default_factory=list)
    conflict_reason: str


class StrategyHealthMetrics(BaseModel):
    """
    Sanitized operational and health metrics for a registered strategy.
    Tracks signal counts and governance throughput without fabricating P&L.
    """
    strategy_id: str
    status: StrategyStatus
    total_signals: int = 0
    accepted_signals: int = 0
    rejected_signals: int = 0
    duplicate_signals: int = 0
    conflicted_signals: int = 0
    quarantine_count: int = 0
    last_signal_time: Optional[datetime] = None
    last_accepted_time: Optional[datetime] = None
    last_rejection_reason: Optional[str] = None
    quarantined_at: Optional[datetime] = None
    quarantine_reason: Optional[str] = None
