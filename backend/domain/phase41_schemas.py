"""
Phase 41 — Live Readiness, Safety Certification & Pre-Live Validation
Global Certification Schema Definitions

Strongly-typed schemas for the final deterministic pre-live certification system.

Safety Invariants:
- CERTIFICATION != AUTHORIZATION != EXECUTION
- Certification engine NEVER arms trading or places orders.
- Unknown/missing/stale state NEVER certifies as safe.
- No credentials or secrets are included in any schema.
- LIVE_EXECUTION_ENABLED remains strictly controlled by configuration.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, Field


# ============================================================
# GATE STATUS ENUMS
# ============================================================

class GlobalCertificationStatus(str, Enum):
    """
    Unambiguous, strongly-typed status for global pre-live certification.
    NO ambiguous 'ready' pseudo-states are permitted.
    """
    CERTIFIED = "CERTIFIED"            # All 28 gates passed, system ready for Phase 42 controlled activation
    NOT_CERTIFIED = "NOT_CERTIFIED"    # One or more mandatory gates failed deterministically
    BLOCKED = "BLOCKED"                # Emergency condition (kill switch, emergency disarm) prevents certification
    DEGRADED = "DEGRADED"             # Non-blocking gates warned, full function not guaranteed
    EXPIRED = "EXPIRED"               # Previously valid certification is beyond expiry window


class GateCategory(str, Enum):
    """Category grouping for a certification gate."""
    CONFIGURATION = "CONFIGURATION"
    BROKER = "BROKER"
    MARKET_DATA = "MARKET_DATA"
    STRATEGY = "STRATEGY"
    RISK = "RISK"
    PREFLIGHT = "PREFLIGHT"
    FAILURE_RECOVERY = "FAILURE_RECOVERY"
    PERSISTENCE = "PERSISTENCE"
    AUDIT = "AUDIT"
    SAFETY = "SAFETY"
    AI_BOUNDARY = "AI_BOUNDARY"
    EXECUTION_PATH = "EXECUTION_PATH"


class GateSeverity(str, Enum):
    """
    Impact level of a certification gate failure.
    BLOCKING: Must pass. Failure unconditionally prevents CERTIFIED status.
    WARNING:  Non-blocking. Failure degrades but does not block certification.
    INFO:     Informational audit record only.
    """
    BLOCKING = "BLOCKING"
    WARNING = "WARNING"
    INFO = "INFO"


class GateStatus(str, Enum):
    """Individual gate evaluation result."""
    PASSED = "PASSED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"      # Unknown = NOT safe
    DEGRADED = "DEGRADED"
    SKIPPED = "SKIPPED"      # Only for INFO-only checks


# ============================================================
# GATE RESULT
# ============================================================

class CertificationGateResult(BaseModel):
    """Result of a single deterministic certification gate evaluation."""
    gate_id: str
    gate_name: str
    category: GateCategory
    severity: GateSeverity
    status: GateStatus
    passed: bool
    is_blocking: bool
    message: str
    details: Optional[str] = None
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================
# DEPENDENCY STATUS
# ============================================================

class DependencyHealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"


class DependencyStatus(BaseModel):
    """Status of a system dependency evaluated during certification."""
    name: str
    status: DependencyHealthStatus
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    notes: Optional[str] = None


# ============================================================
# SAFETY INVARIANT RECORD
# ============================================================

class SafetyInvariant(BaseModel):
    """A documented safety invariant and its verification result."""
    invariant_id: str
    description: str
    verified: bool
    verification_method: str
    notes: Optional[str] = None


# ============================================================
# GLOBAL CERTIFICATION REPORT
# ============================================================

class GlobalCertificationReport(BaseModel):
    """
    Comprehensive, machine-readable and human-readable pre-live certification report.

    Contains:
    - Overall certification status
    - Timestamp and expiry
    - Software/configuration fingerprint (no secrets)
    - Per-gate results (28 gates)
    - Blocking failures and warnings
    - Degraded components
    - Safety invariants verification
    - Dependency health
    - Audit-chain verification
    - Persistence verification
    - Live execution and arming state at evaluation time
    - Kill-switch state
    - Certification expiry window

    NEVER contains credentials, tokens, or live authorization.
    CERTIFICATION != AUTHORIZATION != EXECUTION.
    """

    # Certification identity
    report_id: str = Field(default_factory=lambda: "cert41-" + uuid.uuid4().hex[:12])
    system_phase: str = "Phase 41"
    system_version: str = "41.0.0"

    # Overall verdict
    overall_status: GlobalCertificationStatus

    # Timestamps
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    certification_valid_seconds: int = 300  # Default 5-min validity window

    # Configuration fingerprint (no secrets)
    configuration_fingerprint: str = ""
    live_execution_enabled: bool = False  # MUST be False during Phase 41

    # Safety state snapshot (at evaluation time — not persistent authorization)
    kill_switch_active: bool = False
    live_armed: bool = False  # Armed state at evaluation — NOT authorization
    failure_recovery_in_reset: bool = False

    # Gate results (all 28)
    gates: List[CertificationGateResult] = Field(default_factory=list)

    # Summary counts
    total_gates: int = 0
    passed_gates: int = 0
    failed_gates: int = 0
    blocking_failures_count: int = 0
    warning_count: int = 0

    # Narratives
    blocking_failures: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    degraded_components: List[str] = Field(default_factory=list)

    # Audit and persistence
    audit_chain_status: str = "UNKNOWN"
    audit_total_events: int = 0
    persistence_status: str = "UNKNOWN"
    persistence_revision: int = 0
    journal_status: str = "UNKNOWN"
    journal_sequence: int = 0

    # Dependency health
    dependency_health: List[DependencyStatus] = Field(default_factory=list)

    # Safety invariants
    safety_invariants: List[SafetyInvariant] = Field(default_factory=list)
    safety_invariants_verified: bool = False

    # Hidden execution path audit
    hidden_execution_paths_detected: int = 0
    execution_path_audit_clean: bool = True

    # AI boundary
    ai_boundary_enforced: bool = True
    ai_boundary_notes: str = ""

    # Final lock statement
    real_money_execution_locked: bool = True  # ALWAYS True during Phase 41

    def to_summary_dict(self) -> Dict[str, Any]:
        """Return a compact, human-readable summary dictionary (no secrets)."""
        return {
            "report_id": self.report_id,
            "overall_status": self.overall_status.value,
            "evaluated_at": self.evaluated_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "total_gates": self.total_gates,
            "passed_gates": self.passed_gates,
            "failed_gates": self.failed_gates,
            "blocking_failures_count": self.blocking_failures_count,
            "warning_count": self.warning_count,
            "live_execution_enabled": self.live_execution_enabled,
            "kill_switch_active": self.kill_switch_active,
            "live_armed": self.live_armed,
            "audit_chain_status": self.audit_chain_status,
            "persistence_status": self.persistence_status,
            "safety_invariants_verified": self.safety_invariants_verified,
            "execution_path_audit_clean": self.execution_path_audit_clean,
            "ai_boundary_enforced": self.ai_boundary_enforced,
            "real_money_execution_locked": self.real_money_execution_locked,
            "blocking_failures": self.blocking_failures,
            "warnings": self.warnings,
            "degraded_components": self.degraded_components,
        }
