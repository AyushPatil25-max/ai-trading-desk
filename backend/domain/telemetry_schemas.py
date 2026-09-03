"""
Phase 8 — Execution Monitoring & Live Telemetry Domain Schemas

Strongly typed domain models for execution events, order timelines, latency telemetry,
slippage tracking, system health, and dashboard snapshots.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


TELEMETRY_ENGINE_VERSION = "8.0.0"


# ── Enums ───────────────────────────────────────────────────────────────────

class ExecutionEventType(str, Enum):
    """Categorical event types for order lifecycle and telemetry audit."""
    ORDER_CREATED = "ORDER_CREATED"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_ACKNOWLEDGED = "ORDER_ACKNOWLEDGED"
    ORDER_PARTIALLY_FILLED = "ORDER_PARTIALLY_FILLED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_CANCEL_REQUESTED = "ORDER_CANCEL_REQUESTED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_EXPIRED = "ORDER_EXPIRED"
    FILL_CREATED = "FILL_CREATED"
    RISK_VETO = "RISK_VETO"
    PREFLIGHT_REJECTED = "PREFLIGHT_REJECTED"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    ORDER_ACCEPTED = "ORDER_ACCEPTED"
    POSITION_OPENED = "POSITION_OPENED"
    POSITION_CLOSED = "POSITION_CLOSED"
    PNL_UPDATED = "PNL_UPDATED"
    EQUITY_UPDATED = "EQUITY_UPDATED"
    # Phase 15 — Broker Integration & Sandbox Connectivity Events
    BROKER_CONNECTION_ATTEMPT = "BROKER_CONNECTION_ATTEMPT"
    BROKER_CONNECTED = "BROKER_CONNECTED"
    BROKER_DISCONNECTED = "BROKER_DISCONNECTED"
    BROKER_HEALTH_CHANGED = "BROKER_HEALTH_CHANGED"
    BROKER_REQUEST = "BROKER_REQUEST"
    BROKER_RESPONSE = "BROKER_RESPONSE"
    BROKER_REQUEST_FAILED = "BROKER_REQUEST_FAILED"
    SANDBOX_ORDER_SUBMITTED = "SANDBOX_ORDER_SUBMITTED"
    SANDBOX_ORDER_ACCEPTED = "SANDBOX_ORDER_ACCEPTED"
    SANDBOX_ORDER_REJECTED = "SANDBOX_ORDER_REJECTED"
    SANDBOX_ORDER_FILLED = "SANDBOX_ORDER_FILLED"
    SANDBOX_ORDER_CANCELLED = "SANDBOX_ORDER_CANCELLED"
    SANDBOX_RECONCILIATION_STARTED = "SANDBOX_RECONCILIATION_STARTED"
    SANDBOX_RECONCILIATION_COMPLETED = "SANDBOX_RECONCILIATION_COMPLETED"
    SANDBOX_RECONCILIATION_MISMATCH = "SANDBOX_RECONCILIATION_MISMATCH"
    LIVE_EXECUTION_BLOCKED = "LIVE_EXECUTION_BLOCKED"


class EventSeverity(str, Enum):
    """Severity tier for audit logging and monitoring alerts."""
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class KillSwitchState(str, Enum):
    """State of the operator paper trading emergency kill switch."""
    ARMED = "ARMED"
    TRIGGERED = "TRIGGERED"


# ── Models ──────────────────────────────────────────────────────────────────

class ExecutionEvent(BaseModel):
    """
    Immutable, append-only execution event emitted across the paper trading lifecycle.
    """
    model_config = {"frozen": True}

    event_id: str = Field(default_factory=lambda: f"evt-{uuid.uuid4().hex[:8]}")
    event_type: ExecutionEventType
    execution_id: str
    order_id: Optional[str] = None
    decision_id: Optional[str] = None
    symbol: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: Optional[str] = None
    quantity: Optional[int] = None
    price: Optional[float] = None
    latency_ms: Optional[float] = None
    reason: Optional[str] = None
    severity: EventSeverity = EventSeverity.INFO
    metadata: Dict[str, Any] = Field(default_factory=dict)


class OrderTimelineStep(BaseModel):
    """
    A single chronological step in an order's lifecycle with transition latency.
    """
    status: str
    timestamp: datetime
    latency_from_prev_ms: float = 0.0
    details: str = ""


class OrderTimeline(BaseModel):
    """
    Complete chronological timeline of an order from creation to terminal state.
    """
    order_id: str
    symbol: str
    steps: List[OrderTimelineStep] = Field(default_factory=list)
    total_lifecycle_ms: float = 0.0


class ExecutionMetrics(BaseModel):
    """
    Aggregated operational performance and quality metrics for paper executions.
    """
    total_orders: int = 0
    active_orders: int = 0
    filled_orders: int = 0
    partially_filled_orders: int = 0
    cancelled_orders: int = 0
    rejected_orders: int = 0
    fill_rate_pct: float = 0.0
    rejection_rate_pct: float = 0.0
    cancellation_rate_pct: float = 0.0
    partial_fill_rate_pct: float = 0.0
    avg_execution_latency_ms: float = 0.0
    avg_slippage_pct: float = 0.0
    total_slippage_cost: float = 0.0
    total_simulated_commissions: float = 0.0


class SystemHealthStatus(BaseModel):
    """
    Operational health checks and freshness telemetry for the Trading OS.
    """
    api_status: str = "HEALTHY"
    paper_broker_status: str = "HEALTHY"
    preflight_status: str = "HEALTHY"
    portfolio_ledger_status: str = "HEALTHY"
    telemetry_status: str = "HEALTHY"
    kill_switch_state: KillSwitchState = KillSwitchState.ARMED
    data_freshness: str = "FRESH"
    last_event_timestamp: Optional[datetime] = None
    error_count: int = 0
    healthy: bool = True


class TelemetryDashboardSnapshot(BaseModel):
    """
    Complete operational dashboard snapshot combining telemetry, account, metrics, and health.
    """
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    system_health: SystemHealthStatus
    account_summary: Dict[str, Any]
    metrics: ExecutionMetrics
    active_orders: List[Dict[str, Any]] = Field(default_factory=list)
    recent_fills: List[Dict[str, Any]] = Field(default_factory=list)
    positions: List[Dict[str, Any]] = Field(default_factory=list)
    recent_events: List[Dict[str, Any]] = Field(default_factory=list)
    risk_alerts: List[Dict[str, Any]] = Field(default_factory=list)
