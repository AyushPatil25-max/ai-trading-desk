"""
Phase 31 — Execution Orchestration & Control Plane Domain Schemas

Strongly-typed Pydantic domain models, enums, and deterministic state transitions
for the Execution Orchestration layer:
ExecutionDecision -> Orchestration State Machine -> Paper / Live Route -> Settlement & Audit.

Safety Invariants:
- STRICTLY DETERMINISTIC & FAIL-CLOSED: Invalid state transitions raise InvalidTransitionError.
- Pure Python numerical sanity: Rejects NaN/Inf on quantities, prices, values.
- Zero plaintext credentials, access tokens, or confirmation tokens serialized.
- TIER_4_LIVE_REAL_MONEY remains permanently locked, unroutable, and fail-closed.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid
from pydantic import BaseModel, Field, field_validator, model_validator

from backend.domain.execution_decision_schemas import (
    ExecutionMode,
    ExecutionPipelineDecision,
    ExecutionPipelineStatus,
)


EXECUTION_ORCHESTRATION_SCHEMA_VERSION = "31.0.0"


# ── Canonical Enums ───────────────────────────────────────────────────────────

class ExecutionLifecycleState(str, Enum):
    """
    Formal lifecycle states for an execution record.
    """
    RECEIVED = "RECEIVED"
    VALIDATING = "VALIDATING"
    APPROVED = "APPROVED"
    QUEUED = "QUEUED"
    PREPARING = "PREPARING"
    PAPER_EXECUTING = "PAPER_EXECUTING"
    LIVE_AWAITING_CONFIRMATION = "LIVE_AWAITING_CONFIRMATION"
    LIVE_EXECUTING = "LIVE_EXECUTING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    COMPLETED = "COMPLETED"


class ExecutionControlState(str, Enum):
    """
    Operational state of the Execution Orchestrator Control Plane.
    """
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    DRAINING = "DRAINING"
    HALTED = "HALTED"


class ExecutionStage(str, Enum):
    """
    High-level operational stages in execution orchestration.
    """
    INITIAL_SUBMISSION = "INITIAL_SUBMISSION"
    DECISION_VERIFICATION = "DECISION_VERIFICATION"
    ROUTING = "ROUTING"
    BROKER_DISPATCH = "BROKER_DISPATCH"
    SETTLEMENT = "SETTLEMENT"
    COMPLETED = "COMPLETED"


# ── Deterministic State Machine Transitions ───────────────────────────────────

VALID_ORCHESTRATION_TRANSITIONS: Dict[ExecutionLifecycleState, Set[ExecutionLifecycleState]] = {
    ExecutionLifecycleState.RECEIVED: {
        ExecutionLifecycleState.VALIDATING,
        ExecutionLifecycleState.REJECTED,
        ExecutionLifecycleState.FAILED,
    },
    ExecutionLifecycleState.VALIDATING: {
        ExecutionLifecycleState.APPROVED,
        ExecutionLifecycleState.REJECTED,
        ExecutionLifecycleState.FAILED,
    },
    ExecutionLifecycleState.APPROVED: {
        ExecutionLifecycleState.QUEUED,
        ExecutionLifecycleState.PREPARING,
        ExecutionLifecycleState.REJECTED,
        ExecutionLifecycleState.FAILED,
    },
    ExecutionLifecycleState.QUEUED: {
        ExecutionLifecycleState.PREPARING,
        ExecutionLifecycleState.CANCEL_PENDING,
        ExecutionLifecycleState.CANCELLED,
        ExecutionLifecycleState.FAILED,
    },
    ExecutionLifecycleState.PREPARING: {
        ExecutionLifecycleState.PAPER_EXECUTING,
        ExecutionLifecycleState.LIVE_AWAITING_CONFIRMATION,
        ExecutionLifecycleState.LIVE_EXECUTING,
        ExecutionLifecycleState.REJECTED,
        ExecutionLifecycleState.FAILED,
    },
    ExecutionLifecycleState.PAPER_EXECUTING: {
        ExecutionLifecycleState.SUBMITTED,
        ExecutionLifecycleState.FILLED,
        ExecutionLifecycleState.PARTIALLY_FILLED,
        ExecutionLifecycleState.REJECTED,
        ExecutionLifecycleState.FAILED,
        ExecutionLifecycleState.COMPLETED,
    },
    ExecutionLifecycleState.LIVE_AWAITING_CONFIRMATION: {
        ExecutionLifecycleState.LIVE_EXECUTING,
        ExecutionLifecycleState.REJECTED,
        ExecutionLifecycleState.CANCELLED,
        ExecutionLifecycleState.FAILED,
    },
    ExecutionLifecycleState.LIVE_EXECUTING: {
        ExecutionLifecycleState.SUBMITTED,
        ExecutionLifecycleState.REJECTED,
        ExecutionLifecycleState.FAILED,
        ExecutionLifecycleState.RECONCILIATION_REQUIRED,
        ExecutionLifecycleState.RECOVERY_REQUIRED,
    },
    ExecutionLifecycleState.SUBMITTED: {
        ExecutionLifecycleState.PARTIALLY_FILLED,
        ExecutionLifecycleState.FILLED,
        ExecutionLifecycleState.CANCEL_PENDING,
        ExecutionLifecycleState.CANCELLED,
        ExecutionLifecycleState.REJECTED,
        ExecutionLifecycleState.FAILED,
        ExecutionLifecycleState.RECONCILIATION_REQUIRED,
        ExecutionLifecycleState.COMPLETED,
    },
    ExecutionLifecycleState.PARTIALLY_FILLED: {
        ExecutionLifecycleState.FILLED,
        ExecutionLifecycleState.CANCEL_PENDING,
        ExecutionLifecycleState.CANCELLED,
        ExecutionLifecycleState.RECONCILIATION_REQUIRED,
        ExecutionLifecycleState.COMPLETED,
    },
    ExecutionLifecycleState.FILLED: {
        ExecutionLifecycleState.COMPLETED,
    },
    ExecutionLifecycleState.CANCEL_PENDING: {
        ExecutionLifecycleState.CANCELLED,
        ExecutionLifecycleState.FILLED,
        ExecutionLifecycleState.RECONCILIATION_REQUIRED,
        ExecutionLifecycleState.FAILED,
    },
    ExecutionLifecycleState.RECONCILIATION_REQUIRED: {
        ExecutionLifecycleState.SUBMITTED,
        ExecutionLifecycleState.PARTIALLY_FILLED,
        ExecutionLifecycleState.FILLED,
        ExecutionLifecycleState.CANCELLED,
        ExecutionLifecycleState.REJECTED,
        ExecutionLifecycleState.FAILED,
        ExecutionLifecycleState.RECOVERY_REQUIRED,
        ExecutionLifecycleState.COMPLETED,
    },
    ExecutionLifecycleState.RECOVERY_REQUIRED: {
        ExecutionLifecycleState.FAILED,
        ExecutionLifecycleState.RECONCILIATION_REQUIRED,
        ExecutionLifecycleState.CANCELLED,
    },
    # Terminal states
    ExecutionLifecycleState.COMPLETED: set(),
    ExecutionLifecycleState.CANCELLED: set(),
    ExecutionLifecycleState.REJECTED: set(),
    ExecutionLifecycleState.FAILED: set(),
}

TERMINAL_EXECUTION_STATES: Set[ExecutionLifecycleState] = {
    ExecutionLifecycleState.COMPLETED,
    ExecutionLifecycleState.CANCELLED,
    ExecutionLifecycleState.REJECTED,
    ExecutionLifecycleState.FAILED,
}


class InvalidTransitionError(Exception):
    """Raised when an illegal lifecycle state transition is attempted."""
    pass


# ── Execution Lifecycle Record ────────────────────────────────────────────────

class ExecutionRecord(BaseModel):
    """
    Authoritative, durable record tracking the full lifecycle of an execution.
    """
    execution_id: str = Field(default_factory=lambda: f"exec-rec-{uuid.uuid4().hex[:12]}")
    decision_id: str
    decision_fingerprint: str
    strategy_id: str
    strategy_version: str
    symbol: str
    exchange: str = "NSE"
    direction: str
    quantity: float = Field(ge=0.0)
    estimated_value: float = Field(ge=0.0)
    execution_mode: ExecutionMode = ExecutionMode.PAPER

    # Lifecycle State Tracking
    state: ExecutionLifecycleState = ExecutionLifecycleState.RECEIVED
    stage: ExecutionStage = ExecutionStage.INITIAL_SUBMISSION
    broker_order_id: Optional[str] = None
    filled_quantity: float = Field(default=0.0, ge=0.0)
    average_fill_price: Optional[float] = None
    rejection_reason: Optional[str] = None
    reconciliation_status: Optional[str] = None
    retry_count: int = Field(default=0, ge=0)

    # Timestamps & Tracking
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    audit_correlation_id: str = Field(default_factory=lambda: f"corr-{uuid.uuid4().hex[:8]}")
    state_history: List[Dict[str, Any]] = Field(default_factory=list)

    @field_validator("quantity", "estimated_value", "filled_quantity")
    @classmethod
    def validate_finite_numerical(cls, v: float) -> float:
        if math.isnan(v) or math.isinf(v) or v < 0.0:
            raise ValueError("Numerical quantities and values must be non-negative finite numbers.")
        return round(float(v), 4)

    @field_validator("average_fill_price")
    @classmethod
    def validate_fill_price(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            if math.isnan(v) or math.isinf(v) or v < 0.0:
                raise ValueError("Fill price must be a non-negative finite number.")
            return round(float(v), 4)
        return None

    def transition_to(
        self,
        new_state: ExecutionLifecycleState,
        reason: Optional[str] = None,
        stage: Optional[ExecutionStage] = None,
        now: Optional[datetime] = None,
    ) -> None:
        """
        Deterministically transition the execution record to a new lifecycle state.
        Raises InvalidTransitionError if the transition is disallowed.
        """
        current_state = self.state
        if new_state not in VALID_ORCHESTRATION_TRANSITIONS.get(current_state, set()):
            raise InvalidTransitionError(
                f"Illegal execution lifecycle transition: {current_state.value} -> {new_state.value} is not allowed."
            )

        ts = now or datetime.now(timezone.utc)
        self.state_history.append({
            "from_state": current_state.value,
            "to_state": new_state.value,
            "timestamp": ts.isoformat(),
            "reason": reason,
        })
        self.state = new_state
        if stage:
            self.stage = stage
        if reason and not self.rejection_reason and new_state in (ExecutionLifecycleState.REJECTED, ExecutionLifecycleState.FAILED):
            self.rejection_reason = reason
        self.updated_at = ts

    def is_terminal(self) -> bool:
        """Return True if this execution is in a terminal lifecycle state."""
        return self.state in TERMINAL_EXECUTION_STATES


# ── Request / Result DTOs ─────────────────────────────────────────────────────

class ExecutionOrchestrationRequest(BaseModel):
    """
    Request DTO to orchestrate an approved ExecutionPipelineDecision.
    """
    decision: ExecutionPipelineDecision
    confirmation_token: Optional[str] = None
    operator_notes: Optional[str] = None


class ExecutionOrchestrationResult(BaseModel):
    """
    Outcome DTO returned after execution orchestration.
    """
    execution_id: str
    decision_id: str
    state: ExecutionLifecycleState
    execution_mode: ExecutionMode
    symbol: str
    quantity: float
    filled_quantity: float = 0.0
    average_fill_price: Optional[float] = None
    broker_order_id: Optional[str] = None
    rejection_reason: Optional[str] = None
    reconciliation_status: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    audit_correlation_id: str


class ExecutionControlStatus(BaseModel):
    """
    Status DTO of the Execution Orchestration Control Plane.
    """
    control_state: ExecutionControlState = ExecutionControlState.RUNNING
    is_kill_switch_active: bool = False
    total_executions: int = 0
    active_executions: int = 0
    completed_executions: int = 0
    failed_executions: int = 0
    reconciliation_required_count: int = 0
    paper_executions_count: int = 0
    live_executions_count: int = 0
    last_execution_timestamp: Optional[datetime] = None
    last_failure_reason: Optional[str] = None
