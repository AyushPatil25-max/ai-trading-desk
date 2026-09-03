"""
Phase 15 — External Broker Sandbox Adapter

Implements the provider-neutral BrokerAdapter interface for external sandbox/paper
broker environments. Guarantees deterministic order routing, idempotency,
connection monitoring, robust failure handling, and fail-closed live execution prevention.
"""

from datetime import datetime, timezone
import logging
import threading
from typing import Any, Dict, List, Optional
import uuid

from backend.domain.broker_schemas import (
    BrokerAccountState,
    BrokerCapabilities,
    BrokerConnectionState,
    BrokerMode,
    BrokerPosition,
)
from backend.domain.paper_broker_schemas import (
    PaperAccount,
    PaperExecutionResult,
    PaperFill,
    PaperOrder,
    PaperOrderStatus,
    PaperPosition,
)
from backend.domain.preflight_schemas import (
    ExecutionAuthorizationSnapshot,
    PreflightOrderType,
    PreflightSide,
)
from backend.domain.schemas import MarketContext
from backend.domain.telemetry_schemas import EventSeverity, ExecutionEventType
from backend.application.broker_interface import BrokerAdapter
from backend.application.sandbox_client import (
    MockSandboxClient,
    SandboxAuthenticationError,
    SandboxBrokerUnavailableError,
    SandboxClientProtocol,
    SandboxError,
    SandboxMalformedResponseError,
    SandboxRateLimitError,
    SandboxTimeoutError,
    SandboxUnknownSubmissionStateError,
)

logger = logging.getLogger(__name__)


class SandboxBrokerAdapter(BrokerAdapter):
    """
    Broker adapter connecting to an external broker sandbox/paper trading API.
    Enforces the BrokerAdapter protocol while maintaining complete isolation from live trading.
    """

    def __init__(
        self,
        client: Optional[SandboxClientProtocol] = None,
        provider_name: str = "SandboxBrokerAdapter",
        telemetry_engine: Optional[Any] = None,
    ) -> None:
        self.provider_name = provider_name
        self.client: SandboxClientProtocol = client or MockSandboxClient(provider_name=provider_name)
        self.telemetry_engine = telemetry_engine

        self._lock = threading.Lock()
        self._orders: Dict[str, PaperOrder] = {}
        self._idempotency_map: Dict[str, str] = {}  # idempotency_token -> order_id
        self._reconciliation_needed: bool = False
        self._last_sync_timestamp: Optional[datetime] = None

    # ── Capabilities ──────────────────────────────────────────────────────────

    def get_capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities(
            broker_name=self.provider_name,
            mode=BrokerMode.SANDBOX,
            is_live=False,  # Never live
            supports_paper=True,
            supports_market_orders=True,
            supports_limit_orders=True,
            supports_stop_orders=True,
            supports_order_cancellation=True,
            supports_order_modification=False,
            supports_fractional_shares=False,  # Strictly False
            supports_streaming_quotes=False,
            supports_account_polling=True,
            max_order_quantity_limit=50000,
        )

    # ── Connection State ──────────────────────────────────────────────────────

    def get_connection_state(self) -> BrokerConnectionState:
        try:
            connected = self.client.test_connection()
            return BrokerConnectionState.CONNECTED if connected else BrokerConnectionState.DISCONNECTED
        except SandboxAuthenticationError:
            return BrokerConnectionState.ERROR
        except (SandboxBrokerUnavailableError, SandboxTimeoutError):
            return BrokerConnectionState.DISCONNECTED
        except Exception:
            return BrokerConnectionState.ERROR

    # ── Account State & Positions ─────────────────────────────────────────────

    def get_account_state(self) -> BrokerAccountState:
        now = datetime.now(timezone.utc)
        try:
            raw = self.client.fetch_account()
            positions_map = self.get_positions()

            return BrokerAccountState(
                account_id=raw.get("account_id", f"sbx-{self.provider_name.lower()}"),
                broker_name=self.provider_name,
                mode=BrokerMode.SANDBOX,
                is_live=False,
                cash=float(raw.get("cash", 0.0)),
                buying_power=float(raw.get("buying_power", 0.0)),
                total_equity=float(raw.get("total_equity", 0.0)),
                realized_pnl=float(raw.get("realized_pnl", 0.0)),
                unrealized_pnl=float(raw.get("unrealized_pnl", 0.0)),
                positions=positions_map,
                open_positions_count=len(positions_map),
                updated_at=now,
            )
        except Exception as ex:
            logger.warning(f"[{self.provider_name}] Failed to fetch account state: {ex}")
            return BrokerAccountState(
                account_id=f"sbx-err-{self.provider_name.lower()}",
                broker_name=self.provider_name,
                mode=BrokerMode.SANDBOX,
                is_live=False,
                cash=0.0,
                buying_power=0.0,
                total_equity=0.0,
                realized_pnl=0.0,
                unrealized_pnl=0.0,
                positions={},
                open_positions_count=0,
                updated_at=now,
            )

    def get_positions(self) -> Dict[str, BrokerPosition]:
        now = datetime.now(timezone.utc)
        try:
            raw_list = self.client.fetch_positions()
            res = {}
            for r in raw_list:
                sym = r.get("symbol", "UNKNOWN").upper()
                res[sym] = BrokerPosition(
                    symbol=sym,
                    quantity=int(r.get("quantity", 0)),
                    average_entry_price=float(r.get("average_entry_price", 0.0)),
                    current_price=float(r.get("current_price", 0.0)),
                    market_value=float(r.get("market_value", 0.0)),
                    realized_pnl=float(r.get("realized_pnl", 0.0)),
                    unrealized_pnl=float(r.get("unrealized_pnl", 0.0)),
                    updated_at=now,
                )
            return res
        except Exception as ex:
            logger.warning(f"[{self.provider_name}] Failed to fetch positions: {ex}")
            return {}

    # ── Order Submission & Lifecycle ──────────────────────────────────────────

    def submit_order(
        self,
        authorization: ExecutionAuthorizationSnapshot,
        market_context: Optional[MarketContext] = None,
        evaluation_timestamp: Optional[datetime] = None,
    ) -> PaperExecutionResult:
        now = evaluation_timestamp or datetime.now(timezone.utc)
        token = authorization.idempotency_token

        with self._lock:
            # 1. Idempotency Check: Return existing order if token was already submitted
            if token and token in self._idempotency_map:
                existing_id = self._idempotency_map[token]
                existing_order = self._orders.get(existing_id)
                if existing_order:
                    logger.info(f"[{self.provider_name}] Idempotent duplicate intercepted: {token} -> {existing_id}")
                    return PaperExecutionResult(
                        order=existing_order,
                        status=existing_order.status,
                        new_fills=existing_order.fills,
                        account_snapshot={},
                        message="Idempotent duplicate submission. Returned existing order.",
                    )

            # 2. Discrete Whole Shares Check
            qty = authorization.approved_quantity
            if qty <= 0 or not isinstance(qty, int) or isinstance(qty, bool):
                rej_order = self._create_rejected_order(authorization, "Quantity must be a positive integer.", now)
                return PaperExecutionResult(
                    order=rej_order,
                    status=PaperOrderStatus.REJECTED,
                    new_fills=[],
                    account_snapshot={},
                    message="Fractional or non-positive shares rejected.",
                )

            # 3. Telemetry: Attempt Event
            if self.telemetry_engine:
                self.telemetry_engine.record_event(
                    event_type=ExecutionEventType.SANDBOX_ORDER_SUBMITTED,
                    execution_id=authorization.decision_id,
                    symbol=authorization.symbol,
                    reason="Submitting order to sandbox adapter.",
                    metadata={"provider": self.provider_name, "quantity": qty},
                )

            # 4. Dispatch to Sandbox Client
            client_order_id = f"sbx-{token or uuid.uuid4().hex[:8]}"
            limit_val = getattr(authorization, "normalized_limit_price", None) or getattr(authorization, "limit_price", None)
            order_type_str = "LIMIT" if limit_val is not None else "MARKET"

            try:
                sbx_resp = self.client.place_order(
                    client_order_id=client_order_id,
                    symbol=authorization.symbol,
                    side=authorization.side.value if hasattr(authorization.side, "value") else str(authorization.side),
                    quantity=qty,
                    order_type=order_type_str,
                    limit_price=limit_val,
                )
            except SandboxUnknownSubmissionStateError as ex:
                # Uncertain submission: must NOT retry blindly, trigger reconciliation
                self._reconciliation_needed = True
                logger.error(f"[{self.provider_name}] Unknown submission state: {ex}. Triggering reconciliation.")
                if self.telemetry_engine:
                    self.telemetry_engine.record_event(
                        event_type=ExecutionEventType.BROKER_REQUEST_FAILED,
                        execution_id=authorization.decision_id,
                        symbol=authorization.symbol,
                        reason="UNKNOWN_SUBMISSION_STATE: Order submission state uncertain; reconciliation required.",
                        severity=EventSeverity.CRITICAL,
                    )
                rej_order = self._create_rejected_order(authorization, str(ex), now)
                rej_order.rejection_reason = "UNKNOWN_SUBMISSION_STATE"
                return PaperExecutionResult(
                    order=rej_order,
                    status=PaperOrderStatus.REJECTED,
                    new_fills=[],
                    account_snapshot={},
                    message=str(ex),
                )
            except SandboxTimeoutError as ex:
                rej_order = self._create_rejected_order(authorization, f"TIMEOUT: {ex}", now)
                return PaperExecutionResult(
                    order=rej_order,
                    status=PaperOrderStatus.REJECTED,
                    new_fills=[],
                    account_snapshot={},
                    message=f"Sandbox request timed out: {ex}",
                )
            except SandboxAuthenticationError as ex:
                rej_order = self._create_rejected_order(authorization, f"AUTH_FAILURE: {ex}", now)
                return PaperExecutionResult(
                    order=rej_order,
                    status=PaperOrderStatus.REJECTED,
                    new_fills=[],
                    account_snapshot={},
                    message=f"Sandbox authentication failed: {ex}",
                )
            except SandboxRateLimitError as ex:
                rej_order = self._create_rejected_order(authorization, f"RATE_LIMITED: {ex}", now)
                return PaperExecutionResult(
                    order=rej_order,
                    status=PaperOrderStatus.REJECTED,
                    new_fills=[],
                    account_snapshot={},
                    message=f"Sandbox rate limit exceeded: {ex}",
                )
            except SandboxBrokerUnavailableError as ex:
                rej_order = self._create_rejected_order(authorization, f"BROKER_UNAVAILABLE: {ex}", now)
                return PaperExecutionResult(
                    order=rej_order,
                    status=PaperOrderStatus.REJECTED,
                    new_fills=[],
                    account_snapshot={},
                    message=f"Sandbox broker unavailable: {ex}",
                )
            except Exception as ex:
                rej_order = self._create_rejected_order(authorization, f"EXECUTION_ERROR: {ex}", now)
                return PaperExecutionResult(
                    order=rej_order,
                    status=PaperOrderStatus.REJECTED,
                    new_fills=[],
                    account_snapshot={},
                    message=f"Order execution error: {ex}",
                )

            # 5. Parse Sandbox Response into normalized PaperOrder
            order_id = sbx_resp.get("order_id", f"sbx-ord-{uuid.uuid4().hex[:8]}")
            raw_status = sbx_resp.get("status", "ACKNOWLEDGED").upper()
            status_enum = PaperOrderStatus.FILLED if raw_status == "FILLED" else (
                PaperOrderStatus.REJECTED if raw_status == "REJECTED" else PaperOrderStatus.ACKNOWLEDGED
            )

            fills_list: List[PaperFill] = []
            filled_qty = int(sbx_resp.get("filled_quantity", 0))
            avg_fill_px = float(sbx_resp.get("average_fill_price", 0.0))

            if filled_qty > 0 and avg_fill_px > 0.0:
                fill_obj = PaperFill(
                    fill_id=f"sbx-fill-{uuid.uuid4().hex[:8]}",
                    execution_id=authorization.decision_id,
                    order_id=order_id,
                    symbol=authorization.symbol,
                    side=authorization.side,
                    quantity=filled_qty,
                    price=avg_fill_px,
                    commission=0.0,
                    slippage=0.0,
                    timestamp=now,
                )
                fills_list.append(fill_obj)

            order_obj = PaperOrder(
                order_id=order_id,
                authorization_id=authorization.authorization_id,
                decision_id=authorization.decision_id,
                symbol=authorization.symbol,
                side=authorization.side,
                requested_quantity=qty,
                filled_quantity=filled_qty,
                remaining_quantity=max(0, qty - filled_qty),
                average_fill_price=avg_fill_px,
                status=status_enum,
                created_at=now,
                updated_at=now,
                idempotency_token=token,
                rejection_reason=sbx_resp.get("rejection_reason"),
                fills=fills_list,
            )

            # Record in local lookup maps
            self._orders[order_id] = order_obj
            if token:
                self._idempotency_map[token] = order_id

            if self.telemetry_engine:
                ev_type = ExecutionEventType.SANDBOX_ORDER_FILLED if status_enum == PaperOrderStatus.FILLED else (
                    ExecutionEventType.SANDBOX_ORDER_REJECTED if status_enum == PaperOrderStatus.REJECTED else ExecutionEventType.SANDBOX_ORDER_ACCEPTED
                )
                self.telemetry_engine.record_event(
                    event_type=ev_type,
                    execution_id=authorization.decision_id,
                    symbol=authorization.symbol,
                    reason=f"Sandbox order outcome: {status_enum.value}",
                    metadata={"order_id": order_id, "status": status_enum.value},
                )

            return PaperExecutionResult(
                order=order_obj,
                status=status_enum,
                new_fills=fills_list,
                account_snapshot={},
                message=f"Sandbox order processed: {status_enum.value}",
            )

    def cancel_order(self, order_id: str) -> bool:
        with self._lock:
            cancelled = self.client.cancel_order(order_id)
            if cancelled and order_id in self._orders:
                self._orders[order_id].status = PaperOrderStatus.CANCELLED
                self._orders[order_id].updated_at = datetime.now(timezone.utc)
                if self.telemetry_engine:
                    self.telemetry_engine.record_event(
                        event_type=ExecutionEventType.SANDBOX_ORDER_CANCELLED,
                        execution_id="CANCEL",
                        symbol=self._orders[order_id].symbol,
                        reason=f"Order {order_id} cancelled in sandbox.",
                    )
            return cancelled

    def get_order(self, order_id: str) -> Optional[PaperOrder]:
        with self._lock:
            return self._orders.get(order_id)

    def list_orders(
        self,
        symbol: Optional[str] = None,
        status: Optional[PaperOrderStatus] = None,
    ) -> List[PaperOrder]:
        with self._lock:
            res = list(self._orders.values())
            if symbol:
                res = [o for o in res if o.symbol.upper() == symbol.upper()]
            if status:
                res = [o for o in res if o.status == status]
            return res

    def process_fills(
        self,
        order_id: str,
        market_price: Optional[float] = None,
        fill_ratio: float = 1.0,
        evaluation_timestamp: Optional[datetime] = None,
    ) -> PaperExecutionResult:
        """Process or report simulated fill for an order in the sandbox adapter."""
        with self._lock:
            order = self._orders.get(order_id)
            if not order:
                dummy = PaperOrder(
                    order_id=order_id,
                    authorization_id="UNKNOWN",
                    decision_id="UNKNOWN",
                    symbol="UNKNOWN",
                    side=PreflightSide.BUY,
                    requested_quantity=0,
                    status=PaperOrderStatus.REJECTED,
                    created_at=evaluation_timestamp or datetime.now(timezone.utc),
                    updated_at=evaluation_timestamp or datetime.now(timezone.utc),
                    rejection_reason="ORDER_NOT_FOUND",
                )
                return PaperExecutionResult(
                    order=dummy,
                    status=PaperOrderStatus.REJECTED,
                    new_fills=[],
                    account_snapshot={},
                    message="Order not found in sandbox adapter.",
                )
            return PaperExecutionResult(
                order=order,
                status=order.status,
                new_fills=order.fills,
                account_snapshot={},
                message=f"Sandbox order status: {order.status.value}",
            )

    def synchronize(self) -> BrokerAccountState:
        """Explicitly poll sandbox client and refresh local synchronization timestamp."""
        acct = self.get_account_state()
        self._last_sync_timestamp = datetime.now(timezone.utc)
        return acct

    def reset(self, initial_cash: Optional[float] = None) -> None:
        with self._lock:
            self.client.reset(initial_cash)
            self._orders.clear()
            self._idempotency_map.clear()
            self._reconciliation_needed = False
            self._last_sync_timestamp = None

    def _create_rejected_order(
        self,
        authorization: ExecutionAuthorizationSnapshot,
        reason: str,
        now: datetime,
    ) -> PaperOrder:
        order_id = f"sbx-rej-{uuid.uuid4().hex[:8]}"
        order = PaperOrder(
            order_id=order_id,
            authorization_id=authorization.authorization_id,
            decision_id=authorization.decision_id,
            symbol=authorization.symbol,
            side=authorization.side,
            requested_quantity=max(0, authorization.approved_quantity),
            remaining_quantity=0,
            status=PaperOrderStatus.REJECTED,
            created_at=now,
            updated_at=now,
            idempotency_token=authorization.idempotency_token,
            rejection_reason=reason,
        )
        self._orders[order_id] = order
        return order
