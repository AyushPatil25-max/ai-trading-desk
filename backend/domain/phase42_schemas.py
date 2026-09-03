"""
Phase 42 — Final Production Activation, Controlled Live Execution & Final Certification
Domain Schema Definitions

Strongly-typed schemas for:
1. Environment separation (DEVELOPMENT, PAPER_TRADING, LIVE_CONTROLLED)
2. Operator Authorization Tokens (time-bound, single-use, human-only)
3. First Live Trade Safety Limits (below AI/strategy layer)
4. Live Execution Gate Results and Rejection Reasons
5. Live Order Lifecycle States
6. Final Production Certification Report

Safety Invariants:
- AI components are strictly prohibited from generating or modifying operator authorization.
- LIVE_EXECUTION_ENABLED is False by default.
- First live trade enforces strict hard limits: Qty=1, MaxValue=₹5,000, Cash Equity CNC only, No derivatives/leverage.
- Zero plaintext credentials or access tokens are ever logged or serialized.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, Field


# ============================================================
# ENVIRONMENT & EXECUTION MODES
# ============================================================

class AppEnvironment(str, Enum):
    """
    Explicit separation of operating environments.
    No ambiguity or implicit activation.
    """
    DEVELOPMENT = "DEVELOPMENT"
    PAPER_TRADING = "PAPER_TRADING"
    LIVE_CONTROLLED = "LIVE_CONTROLLED"


class OperatorAuthorizationSource(str, Enum):
    """
    Origin of the operator authorization.
    AI components are explicitly rejected if they attempt authorization.
    """
    HUMAN_OPERATOR = "HUMAN_OPERATOR"
    AI_ADVISORY_REJECTED = "AI_ADVISORY_REJECTED"
    SYSTEM_AUTOMATION_REJECTED = "SYSTEM_AUTOMATION_REJECTED"


# ============================================================
# OPERATOR AUTHORIZATION TOKEN
# ============================================================

class OperatorAuthorizationToken(BaseModel):
    """
    Time-bound, cryptographically single-use token authorizing a specific order request.
    Bound strictly to the SHA-256 fingerprint of the order.
    """
    token_id: str = Field(default_factory=lambda: f"opauth-{uuid.uuid4().hex[:16]}")
    order_fingerprint: str
    operator_id: str
    source: OperatorAuthorizationSource = OperatorAuthorizationSource.HUMAN_OPERATOR
    issued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
    consumed: bool = False
    consumed_at: Optional[datetime] = None
    operator_notes: Optional[str] = None

    def is_valid(self, expected_fingerprint: str, current_time: Optional[datetime] = None) -> bool:
        """Evaluate whether token is valid for the provided fingerprint and unexpired."""
        now = current_time or datetime.now(timezone.utc)
        if self.consumed:
            return False
        if self.source != OperatorAuthorizationSource.HUMAN_OPERATOR:
            return False
        if now > self.expires_at:
            return False
        if self.order_fingerprint != expected_fingerprint:
            return False
        return True


# ============================================================
# FIRST LIVE TRADE HARD LIMITS
# ============================================================

class FirstLiveTradeConfig(BaseModel):
    """
    Strict hard safety limits for the first live real-money trade.
    Enforced below the AI and strategy layers in pure Python.
    """
    max_quantity: int = 1                          # Exactly 1 share for first live test
    max_order_value: float = 5000.0                # ₹5,000 INR maximum notional
    max_daily_loss: float = 1000.0                 # ₹1,000 INR daily loss threshold
    max_orders_per_day: int = 1                    # Exactly 1 live order per day during initial activation
    max_consecutive_failures: int = 2              # 2 consecutive broker failures halts live mode
    allowed_asset_classes: List[str] = Field(
        default_factory=lambda: ["EQUITY"]
    )
    allowed_segments: List[str] = Field(
        default_factory=lambda: ["NSE_EQ", "BSE_EQ"]
    )
    allowed_product_types: List[str] = Field(
        default_factory=lambda: ["CNC"]
    )
    disallowed_instruments: List[str] = Field(
        default_factory=lambda: ["FUTURES", "OPTIONS", "DERIVATIVES", "LEVERAGE", "MARGIN_SHORT", "BASKET"]
    )


# ============================================================
# LIVE EXECUTION GATE REASON CODES & RESULTS
# ============================================================

class LiveExecutionGateReasonCode(str, Enum):
    """Deterministic typed reason codes for live execution gate decisions."""
    VALID = "VALID"
    LIVE_MODE_DISABLED = "LIVE_MODE_DISABLED"
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
    EMERGENCY_DISARMED = "EMERGENCY_DISARMED"
    MARKET_DATA_STALE = "MARKET_DATA_STALE"
    MARKET_DATA_INVALID = "MARKET_DATA_INVALID"
    STRATEGY_NOT_ACTIVE = "STRATEGY_NOT_ACTIVE"
    STRATEGY_VERSION_MISMATCH = "STRATEGY_VERSION_MISMATCH"
    STRATEGY_QUARANTINED = "STRATEGY_QUARANTINED"
    RISK_LIMIT_EXCEEDED = "RISK_LIMIT_EXCEEDED"
    FIRST_TRADE_QUANTITY_EXCEEDED = "FIRST_TRADE_QUANTITY_EXCEEDED"
    FIRST_TRADE_VALUE_EXCEEDED = "FIRST_TRADE_VALUE_EXCEEDED"
    FIRST_TRADE_DAILY_LOSS_EXCEEDED = "FIRST_TRADE_DAILY_LOSS_EXCEEDED"
    FIRST_TRADE_ORDER_COUNT_EXCEEDED = "FIRST_TRADE_ORDER_COUNT_EXCEEDED"
    FIRST_TRADE_DISALLOWED_ASSET_CLASS = "FIRST_TRADE_DISALLOWED_ASSET_CLASS"
    FIRST_TRADE_DISALLOWED_PRODUCT_TYPE = "FIRST_TRADE_DISALLOWED_PRODUCT_TYPE"
    PREFLIGHT_FAILED = "PREFLIGHT_FAILED"
    CERTIFICATION_FAILED = "CERTIFICATION_FAILED"
    OPERATOR_AUTH_MISSING = "OPERATOR_AUTH_MISSING"
    OPERATOR_AUTH_EXPIRED = "OPERATOR_AUTH_EXPIRED"
    OPERATOR_AUTH_MISMATCH = "OPERATOR_AUTH_MISMATCH"
    OPERATOR_AUTH_AI_REJECTED = "OPERATOR_AUTH_AI_REJECTED"
    OPERATOR_AUTH_REUSED = "OPERATOR_AUTH_REUSED"
    CONFIRMATION_TOKEN_INVALID = "CONFIRMATION_TOKEN_INVALID"
    DUPLICATE_ORDER_DETECTED = "DUPLICATE_ORDER_DETECTED"
    BROKER_UNAVAILABLE = "BROKER_UNAVAILABLE"
    BROKER_CONFIG_INVALID = "BROKER_CONFIG_INVALID"
    EXECUTION_FAILED = "EXECUTION_FAILED"


class LiveExecutionGateResult(BaseModel):
    """Complete evaluation result from the final LiveExecutionGate."""
    is_approved: bool
    reason_code: LiveExecutionGateReasonCode
    reason: str
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    checks_performed: List[str] = Field(default_factory=list)
    checks_passed: List[str] = Field(default_factory=list)
    checks_failed: List[str] = Field(default_factory=list)
    order_fingerprint: Optional[str] = None
    operator_token_id: Optional[str] = None
    first_trade_checks_passed: bool = False
    audit_correlation_id: str = Field(default_factory=lambda: f"livegate-{uuid.uuid4().hex[:12]}")


# ============================================================
# LIVE ORDER LIFECYCLE STATE
# ============================================================

class LiveOrderLifecycleState(str, Enum):
    """
    Complete order lifecycle state machine for live orders.
    """
    CREATED = "CREATED"
    AUTHORIZED = "AUTHORIZED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    OPEN = "OPEN"
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    RECONCILED = "RECONCILED"
    FAILED = "FAILED"


class LiveOrderRecord(BaseModel):
    """Durable record tracking the lifecycle of a live order."""
    order_id: str
    broker_order_id: Optional[str] = None
    request_id: str
    symbol: str
    side: str
    quantity: int
    price: Optional[float] = None
    exchange_segment: str
    product_type: str
    order_type: str
    state: LiveOrderLifecycleState = LiveOrderLifecycleState.CREATED
    order_fingerprint: str
    operator_token_id: str
    confirmation_token_masked: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    submitted_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    reconciled_at: Optional[datetime] = None
    filled_quantity: int = 0
    average_fill_price: float = 0.0
    broker_response: Dict[str, Any] = Field(default_factory=dict)
    rejection_reason: Optional[str] = None
    audit_correlation_id: str

    def transition_to(self, new_state: LiveOrderLifecycleState, now: Optional[datetime] = None) -> None:
        """Transition order to new state with timestamp tracking."""
        current_time = now or datetime.now(timezone.utc)
        self.state = new_state
        if new_state == LiveOrderLifecycleState.SUBMITTED:
            self.submitted_at = current_time
        elif new_state == LiveOrderLifecycleState.ACKNOWLEDGED:
            self.acknowledged_at = current_time
        elif new_state == LiveOrderLifecycleState.FILLED:
            self.filled_at = current_time
        elif new_state == LiveOrderLifecycleState.RECONCILED:
            self.reconciled_at = current_time


# ============================================================
# FINAL PRODUCTION CERTIFICATION SCHEMAS
# ============================================================

class ProductionCertificationStatus(str, Enum):
    """
    Strongly-typed final production certification status.
    Distinguishes Development, Paper, and Controlled Live readiness.
    """
    DEVELOPMENT_READY = "DEVELOPMENT_READY"
    PAPER_TRADING_READY = "PAPER_TRADING_READY"
    LIVE_TRADING_READY = "LIVE_TRADING_READY"
    BLOCKED = "BLOCKED"
    NOT_CERTIFIED = "NOT_CERTIFIED"


class ProductionCertificationReport(BaseModel):
    """
    Final comprehensive production readiness certification report.
    Guarantees zero credentials, deterministic reproducibility, and explicit status classification.
    """
    report_id: str = Field(default_factory=lambda: f"prodcert-{uuid.uuid4().hex[:12]}")
    phase: str = "Phase 42 — Final Production Certification"
    version: str = "42.0.0"
    environment: AppEnvironment
    overall_status: ProductionCertificationStatus
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime

    # Invariants & Safety
    live_execution_enabled: bool
    kill_switch_active: bool
    live_armed: bool
    ai_boundary_enforced: bool = True
    hidden_execution_paths_detected: int = 0
    real_money_orders_submitted_in_tests: int = 0

    # Gates & Checks
    global_certification_status: str
    market_data_integrity_status: str
    operator_authorization_ready: bool
    first_live_trade_limits_active: bool
    broker_connection_state: str
    audit_chain_verified: bool
    persistent_state_verified: bool

    # Configurations (Secret Scrubbed)
    configuration_fingerprint: str
    first_live_limits: FirstLiveTradeConfig

    # Details
    passed_checks: List[str] = Field(default_factory=list)
    failed_checks: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)

    def to_summary_dict(self) -> Dict[str, Any]:
        """Return a secret-free summary dictionary."""
        return {
            "report_id": self.report_id,
            "environment": self.environment.value,
            "overall_status": self.overall_status.value,
            "evaluated_at": self.evaluated_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "live_execution_enabled": self.live_execution_enabled,
            "kill_switch_active": self.kill_switch_active,
            "live_armed": self.live_armed,
            "ai_boundary_enforced": self.ai_boundary_enforced,
            "hidden_execution_paths_detected": self.hidden_execution_paths_detected,
            "real_money_orders_submitted_in_tests": self.real_money_orders_submitted_in_tests,
            "global_certification_status": self.global_certification_status,
            "market_data_integrity_status": self.market_data_integrity_status,
            "operator_authorization_ready": self.operator_authorization_ready,
            "first_live_trade_limits_active": self.first_live_trade_limits_active,
            "broker_connection_state": self.broker_connection_state,
            "audit_chain_verified": self.audit_chain_verified,
            "persistent_state_verified": self.persistent_state_verified,
            "passed_checks_count": len(self.passed_checks),
            "failed_checks_count": len(self.failed_checks),
            "warnings_count": len(self.warnings),
        }
