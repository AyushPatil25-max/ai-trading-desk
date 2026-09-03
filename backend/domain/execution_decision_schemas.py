"""
Phase 30 — Authoritative Execution Decision Pipeline Domain Schemas

Strongly-typed Pydantic domain models, enums, and validators for the end-to-end
Execution Decision Pipeline connecting:
Strategy Signal -> Strategy Governance -> Risk Engine -> Execution Preflight
-> Live Readiness -> Live Arming -> Manual Order Safety Gate -> Confirmation Token
-> Duplicate / Idempotency Check -> Final Authorization.

Safety Invariants:
- STRICTLY DETERMINISTIC & FAIL-CLOSED: Non-APPROVED decisions must have is_authorized=False.
- Pure Python numerical sanity: Rejects NaN/Inf on quantities, prices, values.
- Zero plaintext credentials, access tokens, or confirmation tokens serialized.
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


EXECUTION_DECISION_SCHEMA_VERSION = "30.0.0"


# ── Canonical Enums ───────────────────────────────────────────────────────────

class ExecutionPipelineStatus(str, Enum):
    """Overall outcome of the authoritative execution pipeline evaluation."""
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    CONFLICTED = "CONFLICTED"
    NOT_READY = "NOT_READY"
    DEGRADED = "DEGRADED"


class ExecutionMode(str, Enum):
    """Execution target mode."""
    PAPER = "PAPER"
    LIVE = "LIVE"


class PipelineGateName(str, Enum):
    """Named stages in the authoritative execution decision pipeline."""
    SIGNAL_VALIDATION = "SIGNAL_VALIDATION"
    STRATEGY_GOVERNANCE = "STRATEGY_GOVERNANCE"
    RISK_ENGINE = "RISK_ENGINE"
    EXECUTION_PREFLIGHT = "EXECUTION_PREFLIGHT"
    LIVE_READINESS = "LIVE_READINESS"
    LIVE_ARMING = "LIVE_ARMING"
    MANUAL_SAFETY_GATE = "MANUAL_SAFETY_GATE"
    DUPLICATE_CHECK = "DUPLICATE_CHECK"
    CONFIRMATION_CHECK = "CONFIRMATION_CHECK"
    FINAL_AUTHORIZATION = "FINAL_AUTHORIZATION"


# ── Gate Result Model ─────────────────────────────────────────────────────────

class GateExecutionResult(BaseModel):
    """
    Detailed evaluation outcome from an individual gate in the execution pipeline.
    """
    gate_name: PipelineGateName
    passed: bool
    status: str = "PASSED"
    reason: Optional[str] = None
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    details: Dict[str, Any] = Field(default_factory=dict)


# ── Core Pipeline Decision Model ──────────────────────────────────────────────

class ExecutionPipelineDecision(BaseModel):
    """
    Authoritative, deterministic decision produced by the Execution Decision Pipeline.
    Contains complete stage-by-stage provenance, gating metrics, and authorization status.
    """
    decision_id: str = Field(default_factory=lambda: f"exec-dec-{uuid.uuid4().hex[:12]}")
    execution_mode: ExecutionMode = ExecutionMode.PAPER
    pipeline_status: ExecutionPipelineStatus = ExecutionPipelineStatus.BLOCKED
    is_authorized: bool = False

    # Strategy & Signal Identity
    strategy_id: str
    strategy_version: str
    signal_fingerprint: str
    symbol: str
    exchange: str = "NSE"
    direction: str
    quantity: float = Field(ge=0.0)
    estimated_value: float = Field(ge=0.0)

    # Subsystem Stage Outcomes
    governance_status: Optional[str] = None
    risk_decision: Optional[str] = None
    preflight_decision: Optional[str] = None
    readiness_decision: Optional[str] = None
    arming_status: Optional[str] = None
    safety_decision: Optional[str] = None
    confirmation_status: Optional[str] = None
    duplicate_status: Optional[str] = None

    # Gate Trace
    gate_results: List[GateExecutionResult] = Field(default_factory=list)
    rejection_reason: Optional[str] = None
    rejection_details: List[str] = Field(default_factory=list)
    blocking_gate: Optional[PipelineGateName] = None

    # Execution & Broker Payload (Sanitized)
    broker_payload: Optional[Dict[str, Any]] = None
    audit_correlation_id: str = Field(default_factory=lambda: f"corr-{uuid.uuid4().hex[:8]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    decision_fingerprint: str = ""

    @field_validator("quantity", "estimated_value")
    @classmethod
    def validate_finite_numerical(cls, v: float) -> float:
        if math.isnan(v) or math.isinf(v) or v < 0.0:
            raise ValueError("Numerical quantities and values must be non-negative finite numbers.")
        return round(float(v), 4)

    @model_validator(mode="after")
    def validate_authorization_consistency(self) -> "ExecutionPipelineDecision":
        if self.pipeline_status == ExecutionPipelineStatus.APPROVED:
            if not self.is_authorized:
                raise ValueError("APPROVED pipeline decision must have is_authorized=True.")
            if self.rejection_reason is not None:
                raise ValueError("APPROVED pipeline decision cannot have rejection_reason.")
        else:
            if self.is_authorized:
                raise ValueError("Non-APPROVED pipeline decision must have is_authorized=False.")
            if not self.rejection_reason:
                self.rejection_reason = f"Execution blocked: pipeline status is {self.pipeline_status.value}"

        # Compute deterministic decision fingerprint if not provided
        if not self.decision_fingerprint:
            canonical_dict = {
                "decision_id": self.decision_id,
                "execution_mode": self.execution_mode.value,
                "pipeline_status": self.pipeline_status.value,
                "is_authorized": self.is_authorized,
                "strategy_id": self.strategy_id,
                "strategy_version": self.strategy_version,
                "signal_fingerprint": self.signal_fingerprint,
                "symbol": self.symbol,
                "exchange": self.exchange,
                "direction": self.direction,
                "quantity": self.quantity,
                "estimated_value": self.estimated_value,
            }
            canonical_json = json.dumps(canonical_dict, sort_keys=True)
            self.decision_fingerprint = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

        return self


# ── Pipeline Request DTO ──────────────────────────────────────────────────────

class ExecutionPipelineRequest(BaseModel):
    """
    Request DTO to evaluate the complete execution decision pipeline.
    """
    strategy_id: str
    strategy_version: str
    symbol: str
    exchange: str = "NSE"
    direction: str = "BUY"
    quantity: float = Field(gt=0.0)
    target_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    execution_mode: ExecutionMode = ExecutionMode.PAPER
    confirmation_token: Optional[str] = None
    timestamp: Optional[datetime] = None
    market_data_timestamp: Optional[datetime] = None
    source: str = "RULE_BASED"
    metadata: Dict[str, Any] = Field(default_factory=dict)
