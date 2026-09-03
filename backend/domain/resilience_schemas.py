"""
Phase 22 — System Resilience, Failure Domain & Recovery Schemas

Strongly typed domain models for failure classification, component health supervision,
automated recovery state tracking, and empirical resilience scorecard evaluation.
Pure data containers with zero execution authority.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, Field


RESILIENCE_SCHEMA_VERSION = "22.0.0"


# ── Failure Domain Enums (Step 2) ─────────────────────────────────────────────

class FailureDomainType(str, Enum):
    """
    Standardized failure domain categories covering all subsystems of the Trading OS.
    Must handle individual component outages, slowdowns, corruptions, and disconnects.
    """
    MARKET_DATA_FAILURE = "MARKET_DATA_FAILURE"
    MARKET_DATA_STALE = "MARKET_DATA_STALE"
    STREAM_DISCONNECT = "STREAM_DISCONNECT"
    STREAM_BACKPRESSURE = "STREAM_BACKPRESSURE"
    WEBSOCKET_FAILURE = "WEBSOCKET_FAILURE"
    WORKER_FAILURE = "WORKER_FAILURE"
    WORKER_TIMEOUT = "WORKER_TIMEOUT"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    MODEL_FAILURE = "MODEL_FAILURE"
    MODEL_INVALID_RESPONSE = "MODEL_INVALID_RESPONSE"
    CACHE_FAILURE = "CACHE_FAILURE"
    SNAPSHOT_INTEGRITY_FAILURE = "SNAPSHOT_INTEGRITY_FAILURE"
    DATABASE_FAILURE = "DATABASE_FAILURE"
    BROKER_SANDBOX_FAILURE = "BROKER_SANDBOX_FAILURE"
    BROKER_TIMEOUT = "BROKER_TIMEOUT"
    TELEMETRY_FAILURE = "TELEMETRY_FAILURE"
    API_FAILURE = "API_FAILURE"
    RESOURCE_EXHAUSTION = "RESOURCE_EXHAUSTION"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


class FailureSeverity(str, Enum):
    """Severity rating for operational and safety failures."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RecoveryState(str, Enum):
    """Lifecycle state of an identified failure and its recovery effort."""
    DETECTED = "DETECTED"
    IN_PROGRESS = "IN_PROGRESS"
    RECOVERED = "RECOVERED"
    FAILED_SAFE = "FAILED_SAFE"
    UNRECOVERABLE = "UNRECOVERABLE"


class ResilienceComponent(str, Enum):
    """Core subsystems actively supervised by the Resilience Engine."""
    MARKET_DATA = "MARKET_DATA"
    STREAMING_LAYER = "STREAMING_LAYER"
    PAPER_WORKERS = "PAPER_WORKERS"
    MODEL_SERVICES = "MODEL_SERVICES"
    CONTEXT_CACHE = "CONTEXT_CACHE"
    SNAPSHOT_SUBSYSTEM = "SNAPSHOT_SUBSYSTEM"
    TELEMETRY_PIPELINE = "TELEMETRY_PIPELINE"
    BROKER_SANDBOX = "BROKER_SANDBOX"
    API_SUBSYSTEM = "API_SUBSYSTEM"
    ALERTING_ENGINE = "ALERTING_ENGINE"


class ComponentSupervisorState(str, Enum):
    """Standardized operational state of a supervised subsystem."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    RECOVERING = "RECOVERING"
    FAILED_SAFE = "FAILED_SAFE"


class CircuitState(str, Enum):
    """State of an operational circuit breaker."""
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class ResilienceReadinessClassification(str, Enum):
    """Overall operational resilience and recovery readiness certification."""
    NOT_READY = "NOT_READY"
    DEGRADED = "DEGRADED"
    RESILIENT = "RESILIENT"
    HIGHLY_RESILIENT = "HIGHLY_RESILIENT"


# ── Structured Failure Event Container (Step 2) ───────────────────────────────

class FailureEvent(BaseModel):
    """
    Standardized, strongly typed failure event container with full correlation tracking.
    Never exposes secrets, passwords, or broker credentials.
    """
    failure_id: str = Field(default_factory=lambda: f"fail-{uuid.uuid4().hex[:10]}")
    correlation_id: str = Field(default_factory=lambda: f"corr-{uuid.uuid4().hex[:12]}")
    component: ResilienceComponent = Field(..., description="Supervised subsystem")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Detection UTC timestamp"
    )
    severity: FailureSeverity = Field(default=FailureSeverity.MEDIUM)
    failure_type: FailureDomainType = Field(..., description="Categorized failure domain")
    description: str = Field(..., description="Sanitized human-readable description")
    recovery_state: RecoveryState = Field(default=RecoveryState.DETECTED)
    retry_count: int = Field(default=0, ge=0)
    safe_fallback: str = Field(default="NONE", description="Active safe degradation policy")
    trading_halted: bool = Field(default=False, description="Whether simulated trading was halted")
    audit_metadata: Dict[str, Any] = Field(default_factory=dict)


# ── Supervised Component Health Model (Step 4) ────────────────────────────────

class ComponentHealthRecord(BaseModel):
    """Supervised operational telemetry for an individual subsystem."""
    component: ResilienceComponent
    name: str
    state: ComponentSupervisorState = ComponentSupervisorState.HEALTHY
    is_safety_critical: bool = False
    last_heartbeat: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    consecutive_failures: int = 0
    latency_ms: float = 0.0
    timeout_count: int = 0
    recovery_attempts: int = 0
    circuit_state: CircuitState = CircuitState.CLOSED
    active_fallback: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


# ── Recovery Action & History (Step 7) ────────────────────────────────────────

class RecoveryAction(BaseModel):
    """Detailed record of an automated or manual recovery workflow execution."""
    action_id: str = Field(default_factory=lambda: f"rec-{uuid.uuid4().hex[:10]}")
    correlation_id: str = Field(..., description="Matches origin FailureEvent correlation_id")
    component: ResilienceComponent
    failure_type: FailureDomainType
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    duration_ms: float = 0.0
    success: bool = False
    action_taken: str = Field(..., description="Automated recovery strategy executed")
    result_message: str = Field(..., description="Outcome summary")
    audit_metadata: Dict[str, Any] = Field(default_factory=dict)


# ── Resilience Scorecard (Step 9) ─────────────────────────────────────────────

class ResilienceScorecard(BaseModel):
    """
    Automated empirical scorecard evaluating system-wide fault tolerance,
    safe degradation fidelity, and recovery effectiveness across all failure modes.
    """
    scorecard_id: str = Field(default_factory=lambda: f"sc-{uuid.uuid4().hex[:10]}")
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_scenarios_tested: int = Field(default=0, ge=0)
    passed_scenarios: int = Field(default=0, ge=0)
    failed_scenarios: int = Field(default=0, ge=0)
    recovery_success_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    mean_time_to_recover_ms: float = Field(default=0.0, ge=0.0)
    timeout_count: int = Field(default=0, ge=0)
    retry_exhaustion_count: int = Field(default=0, ge=0)
    circuit_breaker_activations: int = Field(default=0, ge=0)
    degraded_mode_activations: int = Field(default=0, ge=0)
    unsafe_state_blocks: int = Field(default=0, ge=0)
    worker_isolation_events: int = Field(default=0, ge=0)
    data_integrity_violations: int = Field(default=0, ge=0)
    telemetry_delivery_health: float = Field(default=1.0, ge=0.0, le=1.0)
    readiness_classification: ResilienceReadinessClassification = (
        ResilienceReadinessClassification.RESILIENT
    )
    summary_message: str = Field(default="")


# ── Resilience Status Summary (Step 10 / 11) ──────────────────────────────────

class ResilienceStatusSummary(BaseModel):
    """High-level operational snapshot for APIs, health dashboards, and alert feeds."""
    overall_resilience_state: ComponentSupervisorState = ComponentSupervisorState.HEALTHY
    active_failures_count: int = 0
    recovering_components_count: int = 0
    open_circuits_count: int = 0
    total_recoveries_executed: int = 0
    mean_recovery_time_ms: float = 0.0
    safe_mode_active: bool = False
    live_trading_permanently_locked: bool = True
    last_audit_timestamp: Optional[datetime] = None
    components: Dict[str, ComponentHealthRecord] = Field(default_factory=dict)
