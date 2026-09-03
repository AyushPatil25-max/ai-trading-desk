"""
Phase 23 — Production Observability, Audit Integrity & Operational Control Domain Schemas

Strongly-typed domain models for unified operational events, cryptographic audit chaining,
decision explainability records, SLO metrics, and lifecycle trace reconstruction.

Safety Invariant:
- All models are PURE DATA CONTAINERS with ZERO execution authority.
- Strictly observational and diagnostic.
- TIER_4_LIVE_REAL_MONEY remains permanently locked and fail-closed.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field

OBSERVABILITY_SCHEMA_VERSION = "23.0.0"

# Sensitive keys that must never appear in raw operational payloads or audit records
SENSITIVE_KEYS = frozenset({
    "api_key", "secret", "password", "token", "credential", "auth",
    "access_token", "auth_token", "private_key", "groq_api_key", "alpaca_secret",
    "authorization", "bearer", "cookie", "session_id", "broker_secret",
    "confirmation_token", "dhan_access_token", "client_secret",
})



def _sanitize_payload(data: Any) -> Any:
    """Recursively scrub any sensitive keys from operational payload dictionaries."""
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            key_lower = str(k).lower()
            if any(s in key_lower for s in SENSITIVE_KEYS):
                sanitized[k] = "***REDACTED***"
            else:
                sanitized[k] = _sanitize_payload(v)
        return sanitized
    elif isinstance(data, list):
        return [_sanitize_payload(item) for item in data]
    return data


# ── Canonical Enums ───────────────────────────────────────────────────────────

class EventCategory(str, Enum):
    """The 15 standardized functional categories for operational/audit events."""
    SYSTEM = "SYSTEM"
    MARKET_DATA = "MARKET_DATA"
    CONTEXT = "CONTEXT"
    SIGNAL = "SIGNAL"
    RISK = "RISK"
    EXECUTION = "EXECUTION"
    STREAMING = "STREAMING"
    FAILURE = "FAILURE"
    RECOVERY = "RECOVERY"
    WORKER = "WORKER"
    MODEL = "MODEL"
    SNAPSHOT = "SNAPSHOT"
    HEALTH = "HEALTH"
    SECURITY = "SECURITY"
    CONFIGURATION = "CONFIGURATION"


class EventSeverity(str, Enum):
    """Severity tier for operational events."""
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    EMERGENCY = "EMERGENCY"


class AuditVerificationStatus(str, Enum):
    """Integrity status determined by the tamper-evident audit verifier."""
    VALID = "VALID"
    INVALID = "INVALID"
    BROKEN_CHAIN = "BROKEN_CHAIN"
    INVALID_HASH = "INVALID_HASH"
    INVALID_SEQUENCE = "INVALID_SEQUENCE"
    MALFORMED_EVENT = "MALFORMED_EVENT"
    EMPTY_CHAIN = "EMPTY_CHAIN"


class OperationalHealthLevel(str, Enum):
    """Deterministic system health classification."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    RECOVERING = "RECOVERING"
    UNKNOWN = "UNKNOWN"


# ── Core Operational & Audit Event ────────────────────────────────────────────

class OperationalEvent(BaseModel):
    """
    Strongly typed, deterministic operational and audit event.
    Forms an immutable, cryptographically chained sequence in the audit trail.
    """
    event_id: str = Field(default_factory=lambda: f"evt-{uuid.uuid4().hex[:12]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: str = Field(..., description="Machine-readable event identifier")
    category: EventCategory = Field(..., description="Functional domain category")
    severity: EventSeverity = Field(default=EventSeverity.INFO, description="Operational severity")
    component: str = Field(..., description="Subsystem or engine emitting the event")
    correlation_id: str = Field(..., description="Trace correlation ID spanning the entire lifecycle")
    causation_id: Optional[str] = Field(default=None, description="Event ID of the direct parent cause")
    run_id: Optional[str] = Field(default=None, description="Pipeline run ID if applicable")
    worker_id: Optional[str] = Field(default=None, description="Worker ID if emitted by paper worker")
    symbol: Optional[str] = Field(default=None, description="Target financial symbol")
    lifecycle_state: Optional[str] = Field(default=None, description="Lifecycle progression state")
    status: Optional[str] = Field(default=None, description="Outcome status (e.g. ACCEPTED, REJECTED)")
    reason: Optional[str] = Field(default=None, description="Operational reason or error description")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Sanitized structured payload")
    schema_version: str = Field(default=OBSERVABILITY_SCHEMA_VERSION)
    sequence_number: int = Field(default=0, ge=0, description="Strictly monotonic sequence number")
    prev_event_hash: Optional[str] = Field(default=None, description="SHA-256 hash of previous event in chain")
    event_hash: Optional[str] = Field(default=None, description="SHA-256 hash of this event's canonical representation")

    def to_canonical_dict(self) -> Dict[str, Any]:
        """
        Generate a normalized dictionary representation suitable for deterministic hashing.
        Excludes the event_hash itself to prevent recursive dependencies.
        """
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "category": self.category.value,
            "severity": self.severity.value,
            "component": self.component,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "run_id": self.run_id,
            "worker_id": self.worker_id,
            "symbol": self.symbol,
            "lifecycle_state": self.lifecycle_state,
            "status": self.status,
            "reason": self.reason,
            "payload": _sanitize_payload(self.payload),
            "schema_version": self.schema_version,
            "sequence_number": self.sequence_number,
            "prev_event_hash": self.prev_event_hash,
        }

    def compute_canonical_hash(self) -> str:
        """Compute the deterministic SHA-256 hash of this event."""
        canonical_json = json.dumps(
            self.to_canonical_dict(),
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# ── Decision Explainability Record ────────────────────────────────────────────

class DecisionExplainabilityRecord(BaseModel):
    """
    Structured explainability record capturing the exact system state, factor scores,
    and risk parameters that produced a trading or risk decision.
    Zero hallucination: strictly populated from actual engine state.
    """
    decision_id: str = Field(default_factory=lambda: f"dec-{uuid.uuid4().hex[:10]}")
    correlation_id: str = Field(..., description="Correlation ID matching the operational event")
    run_id: Optional[str] = Field(default=None)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    symbol: str
    decision_type: str = Field(..., description="BUY, SELL, HOLD, REJECTED, VETOED, FLATTEN")
    direction: str = Field(default="NEUTRAL", description="LONG, SHORT, NEUTRAL")
    conviction: float = Field(default=0.0, ge=0.0, le=1.0)
    factor_scores: Dict[str, float] = Field(default_factory=dict)
    risk_constraints: Dict[str, Any] = Field(default_factory=dict)
    position_sizing_inputs: Dict[str, Any] = Field(default_factory=dict)
    stop_loss_inputs: Dict[str, Any] = Field(default_factory=dict)
    conviction_inputs: Dict[str, Any] = Field(default_factory=dict)
    rejected_constraints: List[str] = Field(default_factory=list)
    final_decision: str
    decision_reason: str
    snapshot_reference: Optional[str] = Field(default=None)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ── Audit Integrity Report ────────────────────────────────────────────────────

class AuditIntegrityReport(BaseModel):
    """Comprehensive report output by the pure-Python audit chain integrity verifier."""
    verified_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: AuditVerificationStatus
    total_events_verified: int = 0
    valid_events_count: int = 0
    invalid_events_count: int = 0
    first_violation_index: Optional[int] = None
    violation_details: Optional[str] = None
    chain_head_hash: Optional[str] = None
    chain_genesis_hash: Optional[str] = None
    summary_message: str = ""


# ── System Health & SLO Telemetry Snapshot ────────────────────────────────────

class SLOMetricsSnapshot(BaseModel):
    """Aggregated operational metrics and latency percentiles (pure Python math)."""
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    overall_health: OperationalHealthLevel = OperationalHealthLevel.HEALTHY
    throughput_events_per_sec: float = 0.0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    latency_p99_ms: float = 0.0
    avg_latency_ms: float = 0.0
    queue_depth: int = 0
    queue_utilization_pct: float = 0.0
    dropped_events: int = 0
    rejected_events: int = 0
    stale_events: int = 0
    duplicate_events: int = 0
    out_of_order_events: int = 0
    worker_failures: int = 0
    recovery_success_rate: float = 1.0
    degraded_duration_ms: float = 0.0
    audit_verification_status: AuditVerificationStatus = AuditVerificationStatus.VALID
    active_workers_count: int = 0
    total_workers_count: int = 0
    live_trading_permanently_locked: bool = True


# ── End-to-End Lifecycle Trace ────────────────────────────────────────────────

class LifecycleTrace(BaseModel):
    """
    End-to-end reconstructed operational lifecycle for a simulation/paper trading run,
    spanning context input -> model -> risk -> preflight -> execution -> accounting.
    """
    correlation_id: str
    run_id: Optional[str] = None
    symbol: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    total_duration_ms: float = 0.0
    events_count: int = 0
    events: List[OperationalEvent] = Field(default_factory=list)
    stages_traversed: List[str] = Field(default_factory=list)
    final_status: str = "UNKNOWN"
    explainability: Optional[DecisionExplainabilityRecord] = None
    risk_assessment: Optional[Dict[str, Any]] = None
    audit_chain_verified: bool = True
