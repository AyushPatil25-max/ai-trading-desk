"""
Phase 13 — Broker Integration & Execution Adapter Domain Schemas

Strongly typed domain models for broker abstraction, capabilities, account states,
order requests, responses, and execution guard results.
Strictly paper-safe: live trading is permanently disabled in this foundation.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field

from backend.domain.preflight_schemas import (
    ExecutionAuthorizationSnapshot,
    PreflightOrderType,
    PreflightSide,
)
from backend.domain.paper_broker_schemas import (
    PaperAccount,
    PaperFill,
    PaperOrder,
    PaperOrderStatus,
    PaperPosition,
)


BROKER_INTEGRATION_VERSION = "13.0.0"


# ── Enums ───────────────────────────────────────────────────────────────────

class BrokerMode(str, Enum):
    """Operational mode for broker adapters."""
    PAPER = "PAPER"
    SIMULATED = "SIMULATED"
    MOCK = "MOCK"
    SANDBOX = "SANDBOX"
    LIVE = "LIVE"  # Present for typing, strictly disabled by ExecutionGuard
    DHAN = "DHAN"


class BrokerEnvironment(str, Enum):
    """Execution environment tier."""
    PAPER = "PAPER"        # Internal deterministic simulation
    SANDBOX = "SANDBOX"    # External broker paper/sandbox API
    LIVE = "LIVE"          # Live real-money trading (STRICTLY PROHIBITED)


class BrokerRoutingMode(str, Enum):
    """Deterministic routing destination."""
    INTERNAL_PAPER = "INTERNAL_PAPER"
    EXTERNAL_SANDBOX = "EXTERNAL_SANDBOX"
    LIVE = "LIVE"


class BrokerConnectionState(str, Enum):
    """Connection and readiness status of a broker adapter."""
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    SIMULATED_ACTIVE = "SIMULATED_ACTIVE"
    DISABLED = "DISABLED"
    ERROR = "ERROR"
    DHAN_DISABLED = "DHAN_DISABLED"
    DHAN_CONFIGURED = "DHAN_CONFIGURED"
    DHAN_AUTH_FAILED = "DHAN_AUTH_FAILED"
    DHAN_CONNECTED = "DHAN_CONNECTED"
    DHAN_UNAVAILABLE = "DHAN_UNAVAILABLE"


# ── Capability Model ────────────────────────────────────────────────────────

class BrokerCapabilities(BaseModel):
    """
    Explicit, deterministic capabilities matrix for a broker adapter.
    """
    broker_name: str
    mode: BrokerMode = BrokerMode.PAPER
    is_live: bool = False
    supports_paper: bool = True
    supports_market_orders: bool = True
    supports_limit_orders: bool = True
    supports_stop_orders: bool = True
    supports_order_cancellation: bool = True
    supports_order_modification: bool = False
    supports_fractional_shares: bool = False  # Strictly False for Indian equities
    supports_streaming_quotes: bool = False
    supports_account_polling: bool = True
    max_order_quantity_limit: int = 50000


# ── Account & Position Models ───────────────────────────────────────────────

class BrokerPosition(BaseModel):
    """
    Normalized position representation across broker adapters.
    """
    symbol: str
    quantity: int = 0
    average_entry_price: float = 0.0
    current_price: float = 0.0
    market_value: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_paper_position(cls, pos: PaperPosition) -> "BrokerPosition":
        return cls(
            symbol=pos.symbol,
            quantity=pos.quantity,
            average_entry_price=pos.average_entry_price,
            current_price=pos.current_price,
            market_value=pos.market_value,
            realized_pnl=pos.realized_pnl,
            unrealized_pnl=pos.unrealized_pnl,
            updated_at=pos.updated_at if pos.updated_at.tzinfo else pos.updated_at.replace(tzinfo=timezone.utc),
        )


class BrokerAccountState(BaseModel):
    """
    Normalized account and purchasing power state across broker adapters.
    """
    account_id: str
    broker_name: str
    mode: BrokerMode = BrokerMode.PAPER
    is_live: bool = False
    cash: float
    buying_power: float
    total_equity: float
    realized_pnl: float
    unrealized_pnl: float
    positions: Dict[str, BrokerPosition] = Field(default_factory=dict)
    open_positions_count: int = 0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_paper_account(cls, acct: PaperAccount, broker_name: str = "PaperBrokerAdapter") -> "BrokerAccountState":
        pos_map = {sym: BrokerPosition.from_paper_position(p) for sym, p in acct.positions.items()}
        return cls(
            account_id=acct.account_id,
            broker_name=broker_name,
            mode=BrokerMode.PAPER,
            is_live=False,
            cash=acct.cash,
            buying_power=acct.buying_power,
            total_equity=acct.total_equity,
            realized_pnl=acct.realized_pnl,
            unrealized_pnl=acct.unrealized_pnl,
            positions=pos_map,
            open_positions_count=len([p for p in pos_map.values() if p.quantity > 0]),
            updated_at=acct.updated_at if acct.updated_at.tzinfo else acct.updated_at.replace(tzinfo=timezone.utc),
        )


# ── Order Request & Response Models ─────────────────────────────────────────

# ── New Order Enums & Models ────────────────────────────────────────────────────────

class OrderSide(str, Enum):
    """Buy or Sell side of an order."""
    BUY = "BUY"
    SELL = "SELL"

class OrderType(str, Enum):
    """Market or Limit order type."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"

class ProductType(str, Enum):
    """Product segment for Indian equities."""
    CNC = "CNC"
    MIS = "MIS"
    NRML = "NRML"

class ExchangeSegment(str, Enum):
    """Exchange segment where the order will be placed."""
    NSE = "NSE"
    BSE = "BSE"
    NSE_FNO = "NSE_FNO"
    BSE_FNO = "BSE_FNO"

class OrderRequest(BaseModel):
    """Domain model for a concrete order request sent to a broker.
    All fields map directly to the Dhan v2 order payload.
    """
    request_id: str = Field(default_factory=lambda: f"ord-{uuid.uuid4().hex[:8]}")
    symbol: str
    exchange_segment: ExchangeSegment
    product_type: ProductType
    side: OrderSide
    order_type: OrderType
    quantity: int = Field(..., gt=0)
    price: Optional[float] = None  # Required for LIMIT orders
    trigger_price: Optional[float] = None  # Optional, for stop orders
    validity: str = "DAY"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class OrderPreview(BaseModel):
    """A preview of the order after validation and Dhan payload generation."""
    request: OrderRequest
    dhan_payload: Dict[str, Any]
    is_valid: bool = True
    validation_errors: List[str] = Field(default_factory=list)

class NormalizedOrderStatus(str, Enum):
    """Normalized order execution status across brokers."""
    SUBMITTED = "SUBMITTED"
    PENDING = "PENDING"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"

class OrderResult(BaseModel):
    """Result of an order submission (either paper or live)."""
    order_id: Optional[str] = None
    request_id: Optional[str] = None
    broker_name: str = "DhanBroker"
    symbol: Optional[str] = None
    side: Optional[str] = None
    quantity: Optional[int] = None
    order_type: Optional[str] = None
    product_type: Optional[str] = None
    exchange_segment: Optional[str] = None
    status: str
    filled_quantity: int = 0
    remaining_quantity: int = 0
    average_fill_price: float = 0.0
    message: str = ""
    rejection_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SafetyReasonCode(str, Enum):
    """Deterministic reason codes for manual order safety gate evaluation."""
    VALID = "VALID"
    BROKER_NOT_CONFIGURED = "BROKER_NOT_CONFIGURED"
    LIVE_EXECUTION_DISABLED = "LIVE_EXECUTION_DISABLED"
    INVALID_SYMBOL = "INVALID_SYMBOL"
    INVALID_QUANTITY = "INVALID_QUANTITY"
    INVALID_ORDER_TYPE = "INVALID_ORDER_TYPE"
    INVALID_PRODUCT_TYPE = "INVALID_PRODUCT_TYPE"
    INVALID_EXCHANGE = "INVALID_EXCHANGE"
    INVALID_PRICE = "INVALID_PRICE"
    INVALID_TRIGGER_PRICE = "INVALID_TRIGGER_PRICE"
    ORDER_VALUE_LIMIT_EXCEEDED = "ORDER_VALUE_LIMIT_EXCEEDED"
    QUANTITY_LIMIT_EXCEEDED = "QUANTITY_LIMIT_EXCEEDED"
    INSUFFICIENT_BUYING_POWER = "INSUFFICIENT_BUYING_POWER"
    STALE_DATA = "STALE_DATA"
    SAFETY_CHECK_UNAVAILABLE = "SAFETY_CHECK_UNAVAILABLE"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
    ORDER_MISMATCH = "ORDER_MISMATCH"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TOKEN_REUSED = "TOKEN_REUSED"
    TOKEN_INVALID = "TOKEN_INVALID"

class SafetyGateResult(BaseModel):
    """Structured deterministic outcome of evaluating an order against the safety gate."""
    is_approved: bool
    reason_code: SafetyReasonCode
    reason: str
    validated_order: Optional[OrderRequest] = None
    estimated_order_value: Optional[float] = None
    safety_checks_performed: List[str] = Field(default_factory=list)
    safety_checks_passed: List[str] = Field(default_factory=list)
    safety_checks_failed: List[str] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ConfirmationRecord(BaseModel):
    """Secure in-memory record associating a single-use token with a validated order."""
    confirmation_id: str
    order_request: OrderRequest
    order_fingerprint: str
    dhan_payload: Dict[str, Any] = Field(default_factory=dict)
    estimated_order_value: float = 0.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
    consumed: bool = False
    consumed_at: Optional[datetime] = None

class OrderPreviewResponse(BaseModel):
    """Response containing safety gate outcome, order preview, and confirmation token."""
    safety_result: SafetyGateResult
    preview: OrderPreview
    confirmation_token: Optional[str] = None
    expires_at: Optional[datetime] = None

class OrderConfirmRequest(BaseModel):
    """Request payload to confirm and submit a manual order."""
    confirmation_token: str
    order: OrderRequest



class BrokerOrderRequest(BaseModel):
    """
    Standardized order execution request for broker adapters.
    Requires an authoritative ExecutionAuthorizationSnapshot from Phase 6.9 Pre-Flight.
    """
    request_id: str = Field(default_factory=lambda: f"breq-{uuid.uuid4().hex[:8]}")
    authorization: ExecutionAuthorizationSnapshot
    idempotency_token: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BrokerOrderResponse(BaseModel):
    """
    Standardized order execution outcome returned by broker adapters.
    """
    order_id: str
    request_id: Optional[str] = None
    authorization_id: str
    symbol: str
    side: PreflightSide
    status: PaperOrderStatus
    requested_quantity: int
    filled_quantity: int = 0
    remaining_quantity: int = 0
    average_fill_price: float = 0.0
    broker_name: str
    mode: BrokerMode = BrokerMode.PAPER
    message: str = ""
    rejection_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Execution Guard Models ──────────────────────────────────────────────────

class GuardValidationOutcome(BaseModel):
    """
    Deterministic evaluation result from the ExecutionGuard.
    """
    is_authorized: bool
    rejection_reason: Optional[str] = None
    risk_cleared: bool = False
    preflight_cleared: bool = False
    sizing_cleared: bool = False
    idempotency_cleared: bool = False
    broker_mode_cleared: bool = False
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Broker Status & Configuration Summary ───────────────────────────────────

class BrokerStatusSummary(BaseModel):
    """
    Safe, read-only operational summary of active broker configuration and state.
    """
    version: str = BROKER_INTEGRATION_VERSION
    active_broker_name: str
    broker_mode: BrokerMode
    is_live_trading_enabled: bool = False  # Always False in Phase 13/15
    connection_state: BrokerConnectionState
    capabilities: BrokerCapabilities
    account_summary: BrokerAccountState
    safety_invariants: Dict[str, bool] = Field(
        default_factory=lambda: {
            "real_money_prohibited": True,
            "risk_bypass_prohibited": True,
            "sizing_bypass_prohibited": True,
            "preflight_bypass_prohibited": True,
            "paper_broker_authoritative": True,
            "live_broker_disabled": True,
        }
    )


# ── Phase 15 — Broker Configuration & Credential Safety ───────────────────────

PROHIBITED_PRODUCTION_DOMAINS = [
    "api.zerodha.com",
    "kite.zerodha.com",
    "api.alpaca.markets",
    "data.alpaca.markets",
    "api.upstox.com",
    "api.angelbroking.com",
    "smartapi.angelbroking.com",
    "api.dhan.co",
    "api.fyers.in",
    "interactivebrokers.com",
]


class BrokerConfig(BaseModel):
    """
    Safe, provider-neutral broker configuration model.
    Enforces strict credential secrecy and rejects live production endpoints.
    """
    broker_provider: str = "mock_sandbox"
    broker_environment: BrokerEnvironment = BrokerEnvironment.PAPER
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    base_url: Optional[str] = None
    account_id: Optional[str] = None
    enabled: bool = True
    live_execution_enabled: bool = False
    timeout_seconds: float = 5.0
    max_retries: int = 0

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        # Safety Check 1: LIVE environment strictly rejected
        if self.broker_environment == BrokerEnvironment.LIVE:
            raise ValueError(
                "LIVE_BROKER_PROHIBITED: Real-money live trading environment is strictly disabled by safety policy."
            )

        # Safety Check 2: Production URLs strictly rejected
        if self.base_url:
            lower_url = self.base_url.lower()
            for domain in PROHIBITED_PRODUCTION_DOMAINS:
                if domain in lower_url:
                    raise ValueError(
                        f"PRODUCTION_ENDPOINT_PROHIBITED: Production URL '{self.base_url}' matches blacklisted domain '{domain}'. "
                        "Only verified sandbox/paper endpoints are permitted."
                    )

        # Safety Check 3: Missing credentials for external sandbox
        if self.broker_environment == BrokerEnvironment.SANDBOX and self.broker_provider not in ("mock_sandbox", "generic_sandbox"):
            if not self.api_key or not self.api_secret:
                raise ValueError(
                    f"MISSING_CREDENTIALS: External sandbox provider '{self.broker_provider}' requires api_key and api_secret."
                )

    def __repr__(self) -> str:
        masked_key = "***REDACTED***" if self.api_key else None
        masked_secret = "***REDACTED***" if self.api_secret else None
        return (
            f"BrokerConfig(broker_provider='{self.broker_provider}', "
            f"broker_environment={self.broker_environment}, "
            f"api_key={masked_key}, api_secret={masked_secret}, "
            f"base_url='{self.base_url}', account_id='{self.account_id}', "
            f"enabled={self.enabled}, live_execution_enabled={self.live_execution_enabled})"
        )

    def to_safe_dict(self) -> Dict[str, Any]:
        """Serialize configuration without revealing secrets or private credentials."""
        d = self.model_dump()
        d["api_key"] = "***REDACTED***" if self.api_key else None
        d["api_secret"] = "***REDACTED***" if self.api_secret else None
        return d


# ── Phase 15 — Broker Reconciliation Schemas ─────────────────────────────────

class DiscrepancyType(str, Enum):
    """Categorization of audit discrepancies between Trading OS and sandbox."""
    MISSING_ORDER_IN_BROKER = "MISSING_ORDER_IN_BROKER"
    UNEXPECTED_ORDER_IN_BROKER = "UNEXPECTED_ORDER_IN_BROKER"
    QUANTITY_MISMATCH = "QUANTITY_MISMATCH"
    PRICE_MISMATCH = "PRICE_MISMATCH"
    UNEXPECTED_FILL = "UNEXPECTED_FILL"
    MISSING_FILL = "MISSING_FILL"
    STALE_ORDER = "STALE_ORDER"
    POSITION_MISMATCH = "POSITION_MISMATCH"
    EQUITY_MISMATCH = "EQUITY_MISMATCH"
    CASH_MISMATCH = "CASH_MISMATCH"


class ReconciliationDiscrepancy(BaseModel):
    """Specific discrepancy detected between Trading OS and sandbox broker state."""
    discrepancy_type: DiscrepancyType
    symbol: Optional[str] = None
    order_id: Optional[str] = None
    expected_value: Any = None
    actual_value: Any = None
    severity: str = "WARNING"
    details: str = ""


class ReconciliationReport(BaseModel):
    """Comprehensive two-way reconciliation report between Trading OS and sandbox broker."""
    reconciliation_id: str = Field(default_factory=lambda: f"rec-{uuid.uuid4().hex[:8]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_reconciled: bool = True
    discrepancy_count: int = 0
    discrepancies: List[ReconciliationDiscrepancy] = Field(default_factory=list)
    trading_os_orders_count: int = 0
    broker_orders_count: int = 0
    positions_evaluated: int = 0
    execution_environment: BrokerEnvironment = BrokerEnvironment.PAPER
    broker_provider: str = "PaperBroker"
    summary_message: str = "All states matched."


# ── Phase 15 — Unified Broker Manager Status ─────────────────────────────────

class BrokerManagerStatus(BaseModel):
    """Unified operational status emitted by BrokerManager."""
    version: str = "15.0.0"
    active_environment: BrokerEnvironment
    routing_mode: BrokerRoutingMode
    active_adapter_name: str
    broker_provider: str
    connection_state: BrokerConnectionState
    is_live_blocked: bool = True
    capabilities: BrokerCapabilities
    account_summary: BrokerAccountState
    last_reconciliation: Optional[ReconciliationReport] = None
    safety_invariants: Dict[str, bool] = Field(
        default_factory=lambda: {
            "real_money_prohibited": True,
            "live_mode_blocked": True,
            "risk_bypass_prohibited": True,
            "preflight_mandatory": True,
            "reconciliation_active": True,
            "credentials_redacted": True,
        }
    )

