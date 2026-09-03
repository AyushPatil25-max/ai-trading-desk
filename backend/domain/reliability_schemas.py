"""
Phase 19 — System-Wide Reliability, Stress Testing & Operational Readiness Schemas

Defines strongly typed models for:
- Centralized operational states (HEALTHY, DEGRADED, UNAVAILABLE, FAILED, RECOVERING, SAFE_MODE).
- Subsystem health and dependency monitoring.
- Deterministic failure modes for controlled testing.
- Empirical stress benchmark metrics (measured throughput, latencies p50/p95/p99, queues).
- 14-category Operational Readiness Scorecard (Categories A through N).
- Strict non-negotiable safety invariant: TIER_4_LIVE_REAL_MONEY permanently locked.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


RELIABILITY_ENGINE_VERSION = "19.0.0"


# ── Operational States & Failure Modes ────────────────────────────────────────

class OperationalState(str, Enum):
    """Explicit operational state across the Trading OS and its subsystems."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"
    RECOVERING = "RECOVERING"
    SAFE_MODE = "SAFE_MODE"


class FailureMode(str, Enum):
    """Simulated failure modes for controlled testing and resilience validation."""
    MARKET_DATA_UNAVAILABLE = "MARKET_DATA_UNAVAILABLE"
    WEBSOCKET_DISCONNECT = "WEBSOCKET_DISCONNECT"
    WEBSOCKET_RECONNECT = "WEBSOCKET_RECONNECT"
    STALE_MARKET_DATA = "STALE_MARKET_DATA"
    MALFORMED_MARKET_EVENT = "MALFORMED_MARKET_EVENT"
    DUPLICATE_EVENT = "DUPLICATE_EVENT"
    OUT_OF_ORDER_EVENT = "OUT_OF_ORDER_EVENT"
    QUEUE_OVERFLOW = "QUEUE_OVERFLOW"
    SLOW_CONSUMER = "SLOW_CONSUMER"
    WORKER_FAILURE = "WORKER_FAILURE"
    MULTIPLE_WORKER_FAILURES = "MULTIPLE_WORKER_FAILURES"
    TELEMETRY_FAILURE = "TELEMETRY_FAILURE"
    API_TIMEOUT = "API_TIMEOUT"
    BROKER_SANDBOX_UNAVAILABLE = "BROKER_SANDBOX_UNAVAILABLE"
    BROKER_ACK_DELAY = "BROKER_ACK_DELAY"
    RECONCILIATION_MISMATCH = "RECONCILIATION_MISMATCH"
    RISK_ENGINE_REJECTION = "RISK_ENGINE_REJECTION"
    PREFLIGHT_REJECTION = "PREFLIGHT_REJECTION"
    EXECUTION_GUARD_REJECTION = "EXECUTION_GUARD_REJECTION"
    EVALUATION_FAILURE = "EVALUATION_FAILURE"
    DATABASE_STATE_FAILURE = "DATABASE_STATE_FAILURE"


# ── Subsystem Health Models ───────────────────────────────────────────────────

class SubsystemHealthStatus(BaseModel):
    """Operational status of a monitored subsystem or dependency."""
    subsystem_id: str
    name: str
    state: OperationalState = OperationalState.HEALTHY
    is_safety_critical: bool = False
    last_success_at: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    latency_ms: float = 0.0
    error_count: int = 0
    details: Dict[str, Any] = Field(default_factory=dict)


# ── Operational Readiness Scorecard (Categories A–N) ──────────────────────────

class ReadinessCategory(str, Enum):
    """The 14 explicit operational readiness categories defined in Phase 19."""
    A_DATA_INGESTION = "A_DATA_INGESTION"
    B_STREAMING = "B_STREAMING"
    C_AGENT_PROCESSING = "C_AGENT_PROCESSING"
    D_DECISION_ENGINE = "D_DECISION_ENGINE"
    E_RISK = "E_RISK"
    F_EXECUTION = "F_EXECUTION"
    G_RECONCILIATION = "G_RECONCILIATION"
    H_EVALUATION = "H_EVALUATION"
    I_WORKERS = "I_WORKERS"
    J_TELEMETRY = "J_TELEMETRY"
    K_DASHBOARD = "K_DASHBOARD"
    L_RECOVERY = "L_RECOVERY"
    M_SECURITY = "M_SECURITY"
    N_SAFETY = "N_SAFETY"


class ReadinessStatus(str, Enum):
    """Auditable readiness verdict for an individual category."""
    PASS = "PASS"
    FAIL = "FAIL"
    DEGRADED = "DEGRADED"
    NOT_TESTED = "NOT_TESTED"


class CategoryScore(BaseModel):
    """Evidence and evaluation for a single readiness category."""
    category: ReadinessCategory
    name: str
    status: ReadinessStatus
    evidence: str
    last_audited_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class OperationalReadinessScorecard(BaseModel):
    """Comprehensive readiness scorecard covering categories A through N."""
    scorecard_id: str = Field(default_factory=lambda: f"sc-{uuid.uuid4().hex[:8]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    overall_verdict: str = "OPERATIONAL_READINESS_AUDITED"
    tier4_live_real_money_locked: bool = True
    total_categories: int = 14
    passed_count: int = 0
    degraded_count: int = 0
    failed_count: int = 0
    not_tested_count: int = 0
    categories: Dict[str, CategoryScore] = Field(default_factory=dict)


# ── Performance & Stress Benchmark Models ─────────────────────────────────────

class StressBenchmarkResult(BaseModel):
    """Empirical measurements from high-frequency or stress test runs."""
    benchmark_id: str = Field(default_factory=lambda: f"bm-{uuid.uuid4().hex[:8]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    events_tested: int = 0
    elapsed_seconds: float = 0.0
    events_per_second: float = 0.0
    latency_avg_ms: float = 0.0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    latency_p99_ms: float = 0.0
    queue_utilization_pct: float = 0.0
    dropped_events: int = 0
    error_count: int = 0
    measurement_type: str = Field(default="MEASURED", description="MEASURED vs ESTIMATED vs NOT_TESTED")


# ── Central Master Operational Snapshot ───────────────────────────────────────

class OperationalHealthSnapshot(BaseModel):
    """Consolidated, dashboard-ready snapshot of complete Trading OS operational state."""
    engine_version: str = RELIABILITY_ENGINE_VERSION
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    system_state: OperationalState = OperationalState.HEALTHY
    safe_mode_active: bool = False
    safe_mode_reason: Optional[str] = None
    tier4_live_locked: bool = True
    subsystems: Dict[str, SubsystemHealthStatus] = Field(default_factory=dict)
    active_failure_injections: List[str] = Field(default_factory=list)
    latest_benchmark: Optional[StressBenchmarkResult] = None
    scorecard_summary: Optional[Dict[str, Any]] = None
