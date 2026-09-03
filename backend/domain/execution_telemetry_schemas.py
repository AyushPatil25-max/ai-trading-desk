"""
Phase 32 — Real-Time Execution Telemetry, Latency Profiling & Drift Domain Schemas

Strongly-typed Pydantic domain models for:
- Nanosecond monotonic latency span measurements
- End-to-end execution lifecycle timing profiles (p50, p90, p95, p99)
- Real-time health metrics (success rate, error rate, timeout rate, retry rate)
- Operational drift detection reports (latency drift, broker drift, rejection drift)

Safety Invariants:
- STRICTLY OBSERVATIONAL: Telemetry metrics NEVER modify execution decisions or safety logic.
- Numerical sanity: Rejects NaN/Inf on latency durations and rates.
- Zero plaintext credentials, access tokens, or confirmation tokens serialized.
- Monotonic timing: Durations calculated from monotonic clock nanoseconds.
"""

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field, field_validator, model_validator

from backend.domain.execution_decision_schemas import ExecutionMode


EXECUTION_TELEMETRY_SCHEMA_VERSION = "32.0.0"


# ── Canonical Enums ───────────────────────────────────────────────────────────

class ObservabilityHealthState(str, Enum):
    """Operational health classification based on telemetry and drift metrics."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    UNAVAILABLE = "UNAVAILABLE"


class TelemetryLifecycleStage(str, Enum):
    """Lifecycle stages measured by execution telemetry."""
    SIGNAL_RECEIVED = "SIGNAL_RECEIVED"
    GOVERNANCE_EVALUATED = "GOVERNANCE_EVALUATED"
    DECISION_CREATED = "DECISION_CREATED"
    DECISION_VALIDATED = "DECISION_VALIDATED"
    ORCHESTRATION_STARTED = "ORCHESTRATION_STARTED"
    RISK_CHECK = "RISK_CHECK"
    PREFLIGHT_CHECK = "PREFLIGHT_CHECK"
    READINESS_CHECK = "READINESS_CHECK"
    ARMING_CHECK = "ARMING_CHECK"
    SAFETY_CHECK = "SAFETY_CHECK"
    BROKER_SUBMISSION_STARTED = "BROKER_SUBMISSION_STARTED"
    BROKER_RESPONSE_RECEIVED = "BROKER_RESPONSE_RECEIVED"
    RECONCILIATION = "RECONCILIATION"
    EXECUTION_COMPLETED = "EXECUTION_COMPLETED"


# ── Timing & Span Models ──────────────────────────────────────────────────────

class ExecutionTimingSpan(BaseModel):
    """
    Monotonic timing span for an individual pipeline stage or operation.
    """
    span_name: str
    start_ns: int = Field(description="Start time from monotonic clock in nanoseconds")
    end_ns: Optional[int] = Field(default=None, description="End time in nanoseconds")
    duration_ms: Optional[float] = Field(default=None, ge=0.0, description="Calculated duration in milliseconds")
    status: str = "COMPLETED"

    @model_validator(mode="after")
    def compute_duration(self) -> "ExecutionTimingSpan":
        if self.end_ns is not None and self.duration_ms is None:
            delta_ns = max(0, self.end_ns - self.start_ns)
            self.duration_ms = round(delta_ns / 1_000_000.0, 4)
        return self


class ExecutionTelemetrySample(BaseModel):
    """
    Individual execution measurement sample capturing all lifecycle spans and latencies.
    """
    sample_id: str = Field(default_factory=lambda: f"tel-smp-{uuid.uuid4().hex[:12]}")
    execution_id: str
    decision_id: str
    strategy_id: str
    strategy_version: str
    symbol: str
    execution_mode: ExecutionMode = ExecutionMode.PAPER
    outcome: str = "SUCCESS"

    # Stage Spans
    stage_spans: List[ExecutionTimingSpan] = Field(default_factory=list)

    # Key Granular Latencies (in milliseconds)
    signal_to_governance_ms: float = Field(default=0.0, ge=0.0)
    signal_received_to_governance_ms: float = Field(default=0.0, ge=0.0)
    governance_to_risk_ms: float = Field(default=0.0, ge=0.0)
    risk_to_preflight_ms: float = Field(default=0.0, ge=0.0)
    preflight_to_live_readiness_ms: float = Field(default=0.0, ge=0.0)
    readiness_to_broker_submission_ms: float = Field(default=0.0, ge=0.0)
    broker_latency_ms: Optional[float] = Field(default=None, ge=0.0)
    broker_response_latency_ms: Optional[float] = Field(default=None, ge=0.0)
    total_execution_decision_latency_ms: float = Field(default=0.0, ge=0.0)
    ai_advisory_latency_ms: Optional[float] = Field(default=None, ge=0.0)
    retry_reconciliation_latency_ms: Optional[float] = Field(default=None, ge=0.0)
    governance_to_decision_ms: float = Field(default=0.0, ge=0.0)
    decision_to_orchestration_ms: float = Field(default=0.0, ge=0.0)
    orchestration_to_risk_ms: float = Field(default=0.0, ge=0.0)
    safety_to_broker_ms: float = Field(default=0.0, ge=0.0)
    total_decision_latency_ms: float = Field(default=0.0, ge=0.0)
    total_orchestration_latency_ms: float = Field(default=0.0, ge=0.0)
    total_end_to_end_latency_ms: float = Field(default=0.0, ge=0.0)

    # Metadata & Tracking
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    audit_correlation_id: str = Field(default_factory=lambda: f"corr-{uuid.uuid4().hex[:8]}")
    failure_category: Optional[str] = None
    retry_count: int = Field(default=0, ge=0)
    reconciliation_status: Optional[str] = None

    @field_validator(
        "signal_to_governance_ms",
        "signal_received_to_governance_ms",
        "governance_to_risk_ms",
        "risk_to_preflight_ms",
        "preflight_to_live_readiness_ms",
        "readiness_to_broker_submission_ms",
        "total_execution_decision_latency_ms",
        "governance_to_decision_ms",
        "decision_to_orchestration_ms",
        "orchestration_to_risk_ms",
        "safety_to_broker_ms",
        "total_decision_latency_ms",
        "total_orchestration_latency_ms",
        "total_end_to_end_latency_ms",
    )
    @classmethod
    def validate_finite_latency(cls, v: float) -> float:
        if math.isnan(v) or math.isinf(v) or v < 0.0:
            raise ValueError("Latency measurements must be non-negative finite numbers.")
        return round(float(v), 4)


# ── Latency Profile & Statistics ──────────────────────────────────────────────

class LatencyPercentiles(BaseModel):
    """
    Standard statistical distribution for latency measurements.
    """
    count: int = Field(ge=0)
    min_ms: float = Field(ge=0.0)
    max_ms: float = Field(ge=0.0)
    mean_ms: float = Field(ge=0.0)
    median_ms: float = Field(ge=0.0)
    p50_ms: float = Field(ge=0.0)
    p90_ms: float = Field(ge=0.0)
    p95_ms: float = Field(ge=0.0)
    p99_ms: float = Field(ge=0.0)
    std_dev_ms: float = Field(ge=0.0)


class ExecutionLatencyProfile(BaseModel):
    """
    Aggregated latency profile broken down by execution mode and stage.
    """
    total_samples: int = Field(ge=0)
    execution_mode: Optional[ExecutionMode] = None
    signal_received_to_governance: Optional[LatencyPercentiles] = None
    governance_to_risk: Optional[LatencyPercentiles] = None
    risk_to_preflight: Optional[LatencyPercentiles] = None
    preflight_to_live_readiness: Optional[LatencyPercentiles] = None
    readiness_to_broker_submission: Optional[LatencyPercentiles] = None
    broker_response_latency: Optional[LatencyPercentiles] = None
    total_execution_decision_latency: Optional[LatencyPercentiles] = None
    ai_advisory_latency: Optional[LatencyPercentiles] = None
    retry_reconciliation_latency: Optional[LatencyPercentiles] = None
    decision_pipeline_latency: LatencyPercentiles
    orchestration_latency: LatencyPercentiles
    broker_latency: Optional[LatencyPercentiles] = None
    end_to_end_latency: LatencyPercentiles
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Real-Time Health & Drift Models ───────────────────────────────────────────

class ExecutionHealthMetrics(BaseModel):
    """
    Real-time execution health statistics and rates.
    """
    total_executions: int = Field(ge=0)
    success_count: int = Field(ge=0)
    rejection_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    timeout_count: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    reconciliation_count: int = Field(ge=0)
    kill_switch_interventions: int = Field(ge=0)
    stale_signal_rejections_count: int = Field(default=0, ge=0)
    duplicate_order_rejections_count: int = Field(default=0, ge=0)
    retry_reconciliation_count: int = Field(default=0, ge=0)

    # Computed Rates
    success_rate: float = Field(ge=0.0, le=1.0)
    rejection_rate: float = Field(ge=0.0, le=1.0)
    failure_rate: float = Field(ge=0.0, le=1.0)
    retry_rate: float = Field(ge=0.0, le=1.0)
    timeout_rate: float = Field(ge=0.0, le=1.0)

    health_state: ObservabilityHealthState = ObservabilityHealthState.HEALTHY
    last_sample_timestamp: Optional[datetime] = None


class DriftDetectionReport(BaseModel):
    """
    Deterministic operational drift report comparing recent performance against baseline.
    """
    is_drift_detected: bool = False
    drift_category: Optional[str] = None
    baseline_samples_count: int = 0
    recent_samples_count: int = 0
    baseline_mean_latency_ms: float = 0.0
    recent_mean_latency_ms: float = 0.0
    latency_drift_ratio: float = 1.0
    broker_error_rate_drift: float = 0.0
    rejection_rate_drift: float = 0.0
    health_state: ObservabilityHealthState = ObservabilityHealthState.HEALTHY
    summary: str = "Operational performance within expected tolerances."
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
