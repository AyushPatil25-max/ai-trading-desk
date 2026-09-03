"""
Execution Schemas — Phase 5.1

Strongly typed domain models for execution safety, order validation, paper brokerage,
and portfolio state tracking.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class ExecutionDecision(str, Enum):
    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"
    REQUIRES_REVALIDATION = "REQUIRES_REVALIDATION"


class RejectionReason(str, Enum):
    KILL_SWITCH = "KILL_SWITCH"
    RISK_LIMIT = "RISK_LIMIT"
    POSITION_LIMIT = "POSITION_LIMIT"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    STALE_DATA = "STALE_DATA"
    MARKET_CLOSED = "MARKET_CLOSED"
    INVALID_PRICE = "INVALID_PRICE"
    INVALID_QUANTITY = "INVALID_QUANTITY"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    INSUFFICIENT_POSITION = "INSUFFICIENT_POSITION"
    DUPLICATE_ORDER = "DUPLICATE_ORDER"
    DATA_QUALITY = "DATA_QUALITY"
    RISK_VETO = "RISK_VETO"
    COMMITTEE_REJECT = "COMMITTEE_REJECT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNKNOWN = "UNKNOWN"


class RiskLimits(BaseModel):
    max_position_value: float = Field(default=50000.0, description="Max allowed value in any single stock position")
    max_order_value: float = Field(default=25000.0, description="Max allowed value for a single order")
    max_portfolio_exposure: float = Field(default=0.8, description="Max fraction of total equity invested (0.0 - 1.0)")
    max_daily_loss: float = Field(default=10000.0, description="Max acceptable daily loss before trading halted")
    max_single_symbol_exposure: float = Field(default=0.3, description="Max fraction of equity in a single symbol")
    max_orders_per_symbol: int = Field(default=5, description="Max open/active orders per symbol")
    minimum_confidence: float = Field(default=0.6, description="Minimum confidence threshold required to execute")
    maximum_context_age_seconds: float = Field(default=300.0, description="Maximum age of MarketContext before stale")


class OrderRequest(BaseModel):
    order_id: str
    symbol: str
    side: OrderSide
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)
    order_type: OrderType = OrderType.MARKET
    context_id: str
    run_id: Optional[str] = None
    decision_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    provenance: Dict[str, Any] = Field(default_factory=dict)


class OrderValidationResult(BaseModel):
    is_valid: bool
    decision: ExecutionDecision
    rejection_reasons: List[RejectionReason] = Field(default_factory=list)
    rejection_details: List[str] = Field(default_factory=list)
    checks_passed: List[str] = Field(default_factory=list)
    checks_failed: List[str] = Field(default_factory=list)
    validated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExecutionResult(BaseModel):
    execution_id: str
    order_id: str
    symbol: str
    side: OrderSide
    quantity_requested: float
    quantity_filled: float
    fill_price: float
    status: OrderStatus
    executed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_cost: float
    commission: float = 0.0
    context_id: str
    run_id: Optional[str] = None
    error_message: Optional[str] = None


class Position(BaseModel):
    symbol: str
    quantity: float = 0.0
    average_price: float = 0.0
    current_price: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PortfolioState(BaseModel):
    portfolio_id: str
    initial_cash: float
    cash: float
    available_cash: float
    positions: Dict[str, Position] = Field(default_factory=dict)
    total_market_value: float = 0.0
    total_equity: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_exposure: float = 0.0
    daily_realized_pnl: float = 0.0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExecutionAuditRecord(BaseModel):
    audit_id: str
    order_id: str
    context_id: str
    run_id: Optional[str] = None
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    decision: ExecutionDecision
    validation_result: OrderValidationResult
    execution_result: Optional[ExecutionResult] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    kill_switch_active: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)
