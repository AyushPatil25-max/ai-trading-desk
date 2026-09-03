"""
Phase 26 — Live Trading Readiness & Controlled Activation Domain Schemas

Strongly typed domain models and enums for deterministic live readiness verification,
broker account synchronization, market-session safety, and short-lived live arming.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


LIVE_READINESS_VERSION = "26.0.0"


class ReadinessStatus(str, Enum):
    """Categorical system readiness status for live order execution."""
    READY = "READY"
    NOT_READY = "NOT_READY"
    BLOCKED = "BLOCKED"
    DEGRADED = "DEGRADED"


class CheckSeverity(str, Enum):
    """Severity and gating behavior of a readiness check."""
    BLOCKING = "BLOCKING"
    WARNING = "WARNING"
    INFO = "INFO"


class ReadinessCheckCode(str, Enum):
    """Deterministic machine-readable codes for readiness checks."""
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
    KILL_SWITCH_CLEAR = "KILL_SWITCH_CLEAR"
    LIVE_EXECUTION_FLAG_DISABLED = "LIVE_EXECUTION_FLAG_DISABLED"
    LIVE_EXECUTION_FLAG_ENABLED = "LIVE_EXECUTION_FLAG_ENABLED"
    DHAN_DISABLED = "DHAN_DISABLED"
    DHAN_ENABLED = "DHAN_ENABLED"
    DHAN_CLIENT_ID_MISSING = "DHAN_CLIENT_ID_MISSING"
    DHAN_CLIENT_ID_CONFIGURED = "DHAN_CLIENT_ID_CONFIGURED"
    DHAN_ACCESS_TOKEN_MISSING = "DHAN_ACCESS_TOKEN_MISSING"
    DHAN_ACCESS_TOKEN_CONFIGURED = "DHAN_ACCESS_TOKEN_CONFIGURED"
    DHAN_AUTH_FAILED = "DHAN_AUTH_FAILED"
    DHAN_AUTH_VALID = "DHAN_AUTH_VALID"
    DHAN_UNAVAILABLE = "DHAN_UNAVAILABLE"
    DHAN_CONNECTED = "DHAN_CONNECTED"
    DHAN_DISCONNECTED = "DHAN_DISCONNECTED"
    ACCOUNT_UNAVAILABLE = "ACCOUNT_UNAVAILABLE"
    ACCOUNT_AVAILABLE = "ACCOUNT_AVAILABLE"
    BUYING_POWER_UNAVAILABLE = "BUYING_POWER_UNAVAILABLE"
    BUYING_POWER_AVAILABLE = "BUYING_POWER_AVAILABLE"
    MARKET_SESSION_CLOSED = "MARKET_SESSION_CLOSED"
    MARKET_SESSION_OPEN = "MARKET_SESSION_OPEN"
    MARKET_SESSION_PRE_OPEN = "MARKET_SESSION_PRE_OPEN"
    MARKET_SESSION_UNKNOWN = "MARKET_SESSION_UNKNOWN"
    MARKET_DATA_STALE = "MARKET_DATA_STALE"
    MARKET_DATA_FRESH = "MARKET_DATA_FRESH"
    SAFETY_ENGINE_UNAVAILABLE = "SAFETY_ENGINE_UNAVAILABLE"
    SAFETY_ENGINE_AVAILABLE = "SAFETY_ENGINE_AVAILABLE"
    CONFIRMATION_STORE_UNAVAILABLE = "CONFIRMATION_STORE_UNAVAILABLE"
    CONFIRMATION_STORE_AVAILABLE = "CONFIRMATION_STORE_AVAILABLE"
    AUDIT_CHAIN_UNAVAILABLE = "AUDIT_CHAIN_UNAVAILABLE"
    AUDIT_CHAIN_AVAILABLE = "AUDIT_CHAIN_AVAILABLE"
    BROKER_ADAPTER_UNAVAILABLE = "BROKER_ADAPTER_UNAVAILABLE"
    BROKER_ADAPTER_AVAILABLE = "BROKER_ADAPTER_AVAILABLE"
    CONFIG_INCONSISTENCY = "CONFIG_INCONSISTENCY"
    CONFIG_CONSISTENT = "CONFIG_CONSISTENT"
    MODE_AMBIGUITY = "MODE_AMBIGUITY"
    MODE_ISOLATED = "MODE_ISOLATED"
    ARMED_STATE_EXPIRED = "ARMED_STATE_EXPIRED"
    ARMED_STATE_INACTIVE = "ARMED_STATE_INACTIVE"
    ARMED_STATE_ACTIVE = "ARMED_STATE_ACTIVE"
    ALL_CHECKS_PASSED = "ALL_CHECKS_PASSED"


class ReadinessCheckItem(BaseModel):
    """An individual check evaluating a single subsystem or safety boundary."""
    code: ReadinessCheckCode
    name: str
    category: str = Field(description="Subsystem category: SAFETY, DHAN, MARKET, EXECUTION, SYSTEM")
    passed: bool
    severity: CheckSeverity
    is_blocking: bool
    message: str
    details: Optional[Dict[str, Any]] = None


class LiveReadinessReport(BaseModel):
    """Structured report returned by LiveTradingReadinessEngine."""
    overall_status: ReadinessStatus
    is_ready_for_arming: bool = False
    is_ready_for_order: bool = False
    is_live_enabled_in_env: bool = False
    is_currently_armed: bool = False
    blocking_failures: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    checks: List[ReadinessCheckItem] = Field(default_factory=list)
    market_session: str = "UNKNOWN"
    dhan_connection: str = "DISCONNECTED"
    buying_power: Optional[float] = None
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class LiveArmingStatus(BaseModel):
    """Current state of the short-lived live trading armed session."""
    is_armed: bool = False
    armed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    remaining_seconds: int = 0
    armed_by: str = "OPERATOR"
    session_id: Optional[str] = None
    reason: Optional[str] = None


class LiveArmRequest(BaseModel):
    """Explicit request payload to arm live trading."""
    acknowledgement: bool = Field(description="Must be explicitly True acknowledging real capital risk.")
    duration_seconds: int = Field(default=300, ge=30, le=900, description="Arming TTL in seconds (30s to 15m).")
    operator_notes: Optional[str] = None


class LiveDisarmRequest(BaseModel):
    """Request payload to disarm live trading."""
    reason: str = Field(default="Manual operator disarm")
