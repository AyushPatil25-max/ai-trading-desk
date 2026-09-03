"""
Phase 7 — Paper Brokerage Adapter & Simulated Order Lifecycle Domain Schemas

Strongly typed domain models for simulated paper orders, fills, positions, accounts,
and deterministic lifecycle transitions.
"""

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Set
import uuid
from pydantic import BaseModel, Field, model_validator

from backend.domain.preflight_schemas import PreflightOrderType, PreflightSide


PAPER_BROKER_ENGINE_VERSION = "7.0.0"


# ── Enums & Transition Rules ────────────────────────────────────────────────

class PaperOrderStatus(str, Enum):
    """Lifecycle states of a simulated paper broker order."""
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


VALID_PAPER_ORDER_TRANSITIONS: Dict[PaperOrderStatus, Set[PaperOrderStatus]] = {
    PaperOrderStatus.CREATED: {PaperOrderStatus.SUBMITTED, PaperOrderStatus.REJECTED},
    PaperOrderStatus.SUBMITTED: {PaperOrderStatus.ACKNOWLEDGED, PaperOrderStatus.CANCEL_REQUESTED, PaperOrderStatus.REJECTED},
    PaperOrderStatus.ACKNOWLEDGED: {PaperOrderStatus.PARTIALLY_FILLED, PaperOrderStatus.FILLED, PaperOrderStatus.CANCEL_REQUESTED},
    PaperOrderStatus.PARTIALLY_FILLED: {PaperOrderStatus.PARTIALLY_FILLED, PaperOrderStatus.FILLED, PaperOrderStatus.CANCEL_REQUESTED},
    PaperOrderStatus.CANCEL_REQUESTED: {PaperOrderStatus.CANCELLED},
    PaperOrderStatus.FILLED: set(),            # Terminal state
    PaperOrderStatus.CANCELLED: set(),         # Terminal state
    PaperOrderStatus.REJECTED: set(),          # Terminal state
}


# ── Models ──────────────────────────────────────────────────────────────────

class PaperFill(BaseModel):
    """
    Record of an individual fill execution event for a simulated order.
    """
    fill_id: str = Field(default_factory=lambda: f"fill-{uuid.uuid4().hex[:8]}")
    execution_id: str
    order_id: str
    symbol: str
    side: PreflightSide
    quantity: int = Field(gt=0)
    price: float = Field(gt=0.0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    slippage_amount: float = 0.0
    commission: float = 0.0
    remaining_quantity: int = 0


class PaperOrder(BaseModel):
    """
    Simulated order managed by the paper broker lifecycle engine.
    """
    order_id: str = Field(default_factory=lambda: f"pord-{uuid.uuid4().hex[:8]}")
    authorization_id: str
    decision_id: str
    symbol: str
    side: PreflightSide
    order_type: PreflightOrderType = PreflightOrderType.LIMIT
    requested_quantity: int = Field(default=1, ge=0)
    filled_quantity: int = 0
    remaining_quantity: int
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    average_fill_price: float = 0.0
    status: PaperOrderStatus = PaperOrderStatus.CREATED
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    idempotency_token: str
    fills: List[PaperFill] = Field(default_factory=list)
    rejection_reason: Optional[str] = None

    def can_transition_to(self, target_status: PaperOrderStatus) -> bool:
        """Verify whether the proposed transition is legally permissible."""
        allowed = VALID_PAPER_ORDER_TRANSITIONS.get(self.status, set())
        return target_status in allowed


class PaperPosition(BaseModel):
    """
    Simulated open stock position within the paper account.
    """
    symbol: str
    quantity: int = 0
    average_entry_price: float = 0.0
    current_price: float = 0.0
    market_value: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PaperAccount(BaseModel):
    """
    Simulated paper broker account state and ledger tracking.
    """
    account_id: str = "paper-acct-001"
    initial_cash: float = 100000.0
    cash: float = 100000.0
    buying_power: float = 100000.0
    total_equity: float = 100000.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    positions: Dict[str, PaperPosition] = Field(default_factory=dict)
    orders: Dict[str, PaperOrder] = Field(default_factory=dict)
    fills: List[PaperFill] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PaperExecutionResult(BaseModel):
    """
    Result container returned by paper broker adapter operations.
    Supports dual synchronous and awaitable invocation.
    """
    paper_execution_id: str = Field(default_factory=lambda: f"pex-{uuid.uuid4().hex[:8]}")
    order: PaperOrder
    status: PaperOrderStatus
    new_fills: List[PaperFill] = Field(default_factory=list)
    account_snapshot: Dict[str, Any] = Field(default_factory=dict)
    message: str = ""

    def __await__(self):
        """Allows dual synchronous or awaitable invocation."""
        async def _passthrough():
            return self
        return _passthrough().__await__()
