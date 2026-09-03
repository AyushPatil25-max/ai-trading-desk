"""
Phase 7 — Paper Brokerage Adapter & Simulated Order Lifecycle Engine

Deterministic, offline, simulated broker service that processes approved
ExecutionAuthorizationSnapshot instances from Phase 6.9 through the full order
execution lifecycle, simulated fills, slippage modeling, and portfolio ledger accounting.

ABSOLUTE ISOLATION:
Zero real broker credentials, zero live network calls, zero live order placement.
"""

from datetime import datetime, timezone
import math
import threading
from typing import Any, Dict, List, Optional
import uuid

from backend.domain.schemas import MarketContext
from backend.domain.preflight_schemas import (
    PreflightOrderType,
    PreflightSide,
    ExecutionAuthorizationSnapshot,
)
from backend.domain.paper_broker_schemas import (
    PAPER_BROKER_ENGINE_VERSION,
    PaperOrderStatus,
    VALID_PAPER_ORDER_TRANSITIONS,
    PaperFill,
    PaperOrder,
    PaperPosition,
    PaperAccount,
    PaperExecutionResult,
)
from backend.domain.telemetry_schemas import (
    ExecutionEventType,
    EventSeverity,
)
from backend.domain.broker_schemas import (
    BrokerAccountState,
    BrokerCapabilities,
    BrokerConnectionState,
    BrokerMode,
    BrokerPosition,
)
from backend.application.broker_interface import BrokerAdapter


class PaperBrokerAdapter(BrokerAdapter):
    """
    Simulated broker adapter and order lifecycle engine.
    Pure Python deterministic simulation. Zero LLM dependencies.
    """

    DEFAULT_COMMISSION_RATE = 0.0003  # 0.03% broker commission
    DEFAULT_SLIPPAGE_RATE = 0.0005    # 0.05% slippage

    def __init__(
        self,
        initial_cash: float = 100000.0,
        commission_rate: float = DEFAULT_COMMISSION_RATE,
        slippage_rate: float = DEFAULT_SLIPPAGE_RATE,
        telemetry_engine: Optional[Any] = None,
    ):
        self.initial_cash = float(initial_cash)
        self.commission_rate = float(commission_rate)
        self.slippage_rate = float(slippage_rate)
        self.telemetry_engine = telemetry_engine

        self._lock = threading.Lock()
        self._token_to_order_id: Dict[str, str] = {}
        self.account = PaperAccount(
            initial_cash=self.initial_cash,
            cash=self.initial_cash,
            buying_power=self.initial_cash,
            total_equity=self.initial_cash,
        )

    # ── Order Submission & Lifecycle ──────────────────────────────────────────

    def submit_order(
        self,
        authorization: ExecutionAuthorizationSnapshot,
        market_context: Optional[MarketContext] = None,
        evaluation_timestamp: Optional[datetime] = None,
    ) -> PaperExecutionResult:
        """
        Submit an approved ExecutionAuthorizationSnapshot to the paper broker.
        Enforces authorization boundary, risk veto check, and idempotency.
        """
        now = evaluation_timestamp or datetime.now(timezone.utc)

        # ── 0. Operator Kill Switch Check ─────────────────────────────────────
        if self.telemetry_engine and self.telemetry_engine.is_kill_switch_triggered():
            return self._create_rejected_order(
                authorization=authorization if isinstance(authorization, ExecutionAuthorizationSnapshot) else None,
                reason="KILL_SWITCH_TRIGGERED: Operator emergency kill switch is active.",
                now=now,
            )

        # ── 1. Authorization Boundary Check ───────────────────────────────────
        if not isinstance(authorization, ExecutionAuthorizationSnapshot):
            return self._create_rejected_order(
                authorization=None,
                reason="INVALID_AUTHORIZATION: Object is not a valid ExecutionAuthorizationSnapshot.",
                now=now,
            )

        if not authorization.authorization_id:
            return self._create_rejected_order(
                authorization=authorization,
                reason="INVALID_AUTHORIZATION: authorization_id is empty.",
                now=now,
            )

        risk_state = authorization.risk_state or {}
        if risk_state.get("veto_applied", False):
            return self._create_rejected_order(
                authorization=authorization,
                reason="RISK_VETO: Authorization contains active risk veto.",
                now=now,
            )

        if authorization.approved_quantity <= 0:
            return self._create_rejected_order(
                authorization=authorization,
                reason=f"INVALID_QUANTITY: Approved quantity {authorization.approved_quantity} <= 0.",
                now=now,
            )

        if not isinstance(authorization.approved_quantity, int) or isinstance(authorization.approved_quantity, bool):
            return self._create_rejected_order(
                authorization=authorization,
                reason=f"FRACTIONAL_SHARES_PROHIBITED: Quantity {authorization.approved_quantity} must be an integer.",
                now=now,
            )

        # ── 1.5 Buying Power Check ──────────────────────────────────────────
        limit_px = authorization.normalized_limit_price or 0.0
        if authorization.side == PreflightSide.BUY and limit_px > 0:
            est_cost = authorization.approved_quantity * limit_px
            if est_cost > self.account.buying_power:
                return self._create_rejected_order(
                    authorization=authorization,
                    reason=f"INSUFFICIENT_BUYING_POWER: Estimated cost ₹{est_cost:.2f} exceeds available buying power ₹{self.account.buying_power:.2f}.",
                    now=now,
                )

        # ── 2. Idempotency Check ──────────────────────────────────────────────
        with self._lock:
            existing_order_id = self._token_to_order_id.get(authorization.idempotency_token)
            if existing_order_id and existing_order_id in self.account.orders:
                existing_order = self.account.orders[existing_order_id]
                return PaperExecutionResult(
                    order=existing_order,
                    status=existing_order.status,
                    new_fills=[],
                    account_snapshot=self._build_account_snapshot(),
                    message="IDEMPOTENT: Order already submitted and active.",
                )

            # ── 3. Create Paper Order (CREATED -> SUBMITTED -> ACKNOWLEDGED) ──
            order = PaperOrder(
                order_id=f"pord-{uuid.uuid4().hex[:8]}",
                authorization_id=authorization.authorization_id,
                decision_id=authorization.decision_id,
                symbol=authorization.symbol,
                side=authorization.side,
                order_type=PreflightOrderType.LIMIT if authorization.normalized_limit_price else PreflightOrderType.MARKET,
                requested_quantity=authorization.approved_quantity,
                filled_quantity=0,
                remaining_quantity=authorization.approved_quantity,
                limit_price=authorization.normalized_limit_price,
                stop_price=authorization.normalized_stop_price,
                target_price=authorization.normalized_target_price,
                status=PaperOrderStatus.CREATED,
                created_at=now,
                updated_at=now,
                idempotency_token=authorization.idempotency_token,
            )

            # Transition: CREATED -> SUBMITTED -> ACKNOWLEDGED
            order.status = PaperOrderStatus.SUBMITTED
            order.status = PaperOrderStatus.ACKNOWLEDGED
            order.updated_at = now

            self.account.orders[order.order_id] = order
            self._token_to_order_id[authorization.idempotency_token] = order.order_id

        return PaperExecutionResult(
            order=order,
            status=order.status,
            new_fills=[],
            account_snapshot=self._build_account_snapshot(),
            message="Order submitted and acknowledged.",
        )

    # ── Fill Engine & Execution Simulation ────────────────────────────────────

    def process_fills(
        self,
        order_id: str,
        market_price: float,
        fill_ratio: float = 1.0,
        evaluation_timestamp: Optional[datetime] = None,
    ) -> PaperExecutionResult:
        """
        Simulate deterministic order fills against the specified market price.
        Calculates slippage, commissions, updates the position ledger, and transitions order status.
        """
        now = evaluation_timestamp or datetime.now(timezone.utc)

        with self._lock:
            if order_id not in self.account.orders:
                raise ValueError(f"Order '{order_id}' not found in paper broker.")

            order = self.account.orders[order_id]

            # Terminal states cannot receive fills
            if order.status in (PaperOrderStatus.FILLED, PaperOrderStatus.CANCELLED, PaperOrderStatus.REJECTED):
                return PaperExecutionResult(
                    order=order,
                    status=order.status,
                    new_fills=[],
                    account_snapshot=self._build_account_snapshot(),
                    message=f"Order in terminal status {order.status.value}; no fill processed.",
                )

            # ── Check Fill / Trigger Condition ────────────────────────────────
            if order.order_type == PreflightOrderType.LIMIT and order.limit_price is not None:
                if order.side == PreflightSide.BUY and market_price > order.limit_price:
                    return PaperExecutionResult(
                        order=order,
                        status=order.status,
                        new_fills=[],
                        account_snapshot=self._build_account_snapshot(),
                        message=f"Limit BUY unsatisfied: market price {market_price} > limit {order.limit_price}.",
                    )
                elif order.side == PreflightSide.SELL and market_price < order.limit_price:
                    return PaperExecutionResult(
                        order=order,
                        status=order.status,
                        new_fills=[],
                        account_snapshot=self._build_account_snapshot(),
                        message=f"Limit SELL unsatisfied: market price {market_price} < limit {order.limit_price}.",
                    )

            if order.order_type in (PreflightOrderType.STOP, PreflightOrderType.STOP_LIMIT) and order.stop_price is not None:
                if order.side == PreflightSide.BUY and market_price < order.stop_price:
                    return PaperExecutionResult(
                        order=order,
                        status=order.status,
                        new_fills=[],
                        account_snapshot=self._build_account_snapshot(),
                        message=f"Stop BUY untriggered: market price {market_price} < stop {order.stop_price}.",
                    )
                elif order.side == PreflightSide.SELL and market_price > order.stop_price:
                    return PaperExecutionResult(
                        order=order,
                        status=order.status,
                        new_fills=[],
                        account_snapshot=self._build_account_snapshot(),
                        message=f"Stop SELL untriggered: market price {market_price} > stop {order.stop_price}.",
                    )

            # ── Calculate Fill Quantity & Overfill Guard ──────────────────────
            fill_ratio = max(0.0, min(1.0, fill_ratio))
            raw_fill_qty = max(1, int(round(order.remaining_quantity * fill_ratio)))
            fill_qty = min(order.remaining_quantity, raw_fill_qty)

            if fill_qty <= 0:
                return PaperExecutionResult(
                    order=order,
                    status=order.status,
                    new_fills=[],
                    account_snapshot=self._build_account_snapshot(),
                    message="Zero fill quantity computed.",
                )

            # Strict overfill guard
            if order.filled_quantity + fill_qty > order.requested_quantity:
                fill_qty = order.requested_quantity - order.filled_quantity

            # ── Determine Fill Price with Deterministic Slippage ───────────────
            if order.side == PreflightSide.BUY:
                fill_price = market_price * (1.0 + self.slippage_rate)
                if order.order_type == PreflightOrderType.LIMIT and order.limit_price is not None:
                    fill_price = min(fill_price, order.limit_price)
            else:
                fill_price = market_price * (1.0 - self.slippage_rate)
                if order.order_type == PreflightOrderType.LIMIT and order.limit_price is not None:
                    fill_price = max(fill_price, order.limit_price)

            fill_price = round(fill_price, 4)
            slippage_amt = round(abs(fill_price - market_price) * fill_qty, 4)
            commission = round(fill_qty * fill_price * self.commission_rate, 4)

            # ── Create Fill Record ────────────────────────────────────────────
            fill = PaperFill(
                execution_id=order.authorization_id,
                order_id=order.order_id,
                symbol=order.symbol,
                side=order.side,
                quantity=fill_qty,
                price=fill_price,
                timestamp=now,
                slippage_amount=slippage_amt,
                commission=commission,
                remaining_quantity=order.remaining_quantity - fill_qty,
            )

            order.fills.append(fill)
            self.account.fills.append(fill)

            # ── Update Order State ────────────────────────────────────────────
            order.filled_quantity += fill_qty
            order.remaining_quantity -= fill_qty

            total_filled_notional = sum(f.quantity * f.price for f in order.fills)
            order.average_fill_price = round(total_filled_notional / order.filled_quantity, 4)

            # Transition: PARTIALLY_FILLED or FILLED
            if order.remaining_quantity == 0:
                order.status = PaperOrderStatus.FILLED
            else:
                order.status = PaperOrderStatus.PARTIALLY_FILLED
            order.updated_at = now

            # ── Update Portfolio Ledger ───────────────────────────────────────
            self._update_ledger_on_fill(fill, market_price, now)

        return PaperExecutionResult(
            order=order,
            status=order.status,
            new_fills=[fill],
            account_snapshot=self._build_account_snapshot(),
            message=f"Filled {fill_qty} shares at ₹{fill_price:.2f}.",
        )

    # ── Order Cancellation ────────────────────────────────────────────────────

    def cancel_order(self, order_id: str, evaluation_timestamp: Optional[datetime] = None) -> PaperExecutionResult:
        """
        Request cancellation of an active paper order.
        Enforces valid state transition rules.
        """
        now = evaluation_timestamp or datetime.now(timezone.utc)

        with self._lock:
            if order_id not in self.account.orders:
                raise ValueError(f"Order '{order_id}' not found in paper broker.")

            order = self.account.orders[order_id]

            if not order.can_transition_to(PaperOrderStatus.CANCEL_REQUESTED):
                raise ValueError(f"Illegal transition: Cannot cancel order in status '{order.status.value}'.")

            # Transition: ACTIVE -> CANCEL_REQUESTED -> CANCELLED
            order.status = PaperOrderStatus.CANCEL_REQUESTED
            order.status = PaperOrderStatus.CANCELLED
            order.updated_at = now

        return PaperExecutionResult(
            order=order,
            status=order.status,
            new_fills=[],
            account_snapshot=self._build_account_snapshot(),
            message="Order cancelled successfully.",
        )

    # ── Portfolio & Position Ledger Accounting ────────────────────────────────

    def _update_ledger_on_fill(self, fill: PaperFill, market_price: float, now: datetime) -> None:
        """
        Atomically update cash, positions, average entry price, and realized P&L.
        """
        pos = self.account.positions.get(fill.symbol)
        if pos is None:
            pos = PaperPosition(
                symbol=fill.symbol,
                quantity=0,
                average_entry_price=0.0,
                current_price=market_price,
                market_value=0.0,
                realized_pnl=0.0,
                unrealized_pnl=0.0,
                updated_at=now,
            )
            self.account.positions[fill.symbol] = pos

        if fill.side == PreflightSide.BUY:
            total_cost = (fill.quantity * fill.price) + fill.commission
            self.account.cash = round(self.account.cash - total_cost, 4)

            new_qty = pos.quantity + fill.quantity
            if new_qty > 0:
                new_avg = ((pos.quantity * pos.average_entry_price) + (fill.quantity * fill.price)) / new_qty
                pos.average_entry_price = round(new_avg, 4)
            pos.quantity = new_qty
            pos.current_price = market_price
            pos.market_value = round(pos.quantity * market_price, 4)
            pos.unrealized_pnl = round((market_price - pos.average_entry_price) * pos.quantity, 4)
            pos.updated_at = now

        elif fill.side == PreflightSide.SELL:
            total_proceeds = (fill.quantity * fill.price) - fill.commission
            self.account.cash = round(self.account.cash + total_proceeds, 4)

            # Realized P&L on exited shares
            realized = round((fill.price - pos.average_entry_price) * fill.quantity - fill.commission, 4)
            self.account.realized_pnl = round(self.account.realized_pnl + realized, 4)
            pos.realized_pnl = round(pos.realized_pnl + realized, 4)

            pos.quantity = max(0, pos.quantity - fill.quantity)
            pos.current_price = market_price
            pos.market_value = round(pos.quantity * market_price, 4)
            pos.unrealized_pnl = round((market_price - pos.average_entry_price) * pos.quantity, 4) if pos.quantity > 0 else 0.0
            pos.updated_at = now

        # Update account-level totals
        total_market_val = sum(p.market_value for p in self.account.positions.values())
        self.account.unrealized_pnl = round(sum(p.unrealized_pnl for p in self.account.positions.values()), 4)
        self.account.total_equity = round(self.account.cash + total_market_val, 4)
        self.account.buying_power = max(0.0, self.account.cash)
        self.account.updated_at = now

    def mark_to_market(self, current_prices: Dict[str, float], evaluation_timestamp: Optional[datetime] = None) -> PaperAccount:
        """
        Revalue open positions against new market quotes and update account equity.
        """
        now = evaluation_timestamp or datetime.now(timezone.utc)
        with self._lock:
            total_market_val = 0.0
            total_unrealized = 0.0

            for sym, pos in self.account.positions.items():
                if sym in current_prices:
                    pos.current_price = current_prices[sym]
                if pos.quantity > 0:
                    pos.market_value = round(pos.quantity * pos.current_price, 4)
                    pos.unrealized_pnl = round((pos.current_price - pos.average_entry_price) * pos.quantity, 4)
                else:
                    pos.market_value = 0.0
                    pos.unrealized_pnl = 0.0
                pos.updated_at = now
                total_market_val += pos.market_value
                total_unrealized += pos.unrealized_pnl

            self.account.unrealized_pnl = round(total_unrealized, 4)
            self.account.total_equity = round(self.account.cash + total_market_val, 4)
            self.account.buying_power = max(0.0, self.account.cash)
            self.account.updated_at = now
            return self.account

    # ── Queries & Inspections ─────────────────────────────────────────────────

    def get_order(self, order_id: str) -> Optional[PaperOrder]:
        with self._lock:
            return self.account.orders.get(order_id)

    def list_orders(
        self,
        symbol: Optional[str] = None,
        status: Optional[PaperOrderStatus] = None,
    ) -> List[PaperOrder]:
        with self._lock:
            orders = list(self.account.orders.values())
            if symbol:
                orders = [o for o in orders if o.symbol == symbol]
            if status:
                orders = [o for o in orders if o.status == status]
            return orders

    def get_account(self) -> PaperAccount:
        with self._lock:
            return self.account

    def get_capabilities(self) -> BrokerCapabilities:
        """Return the explicit, deterministic capability matrix of PaperBrokerAdapter."""
        return BrokerCapabilities(
            broker_name="PaperBrokerAdapter",
            mode=BrokerMode.PAPER,
            is_live=False,
            supports_paper=True,
            supports_market_orders=True,
            supports_limit_orders=True,
            supports_stop_orders=True,
            supports_order_cancellation=True,
            supports_order_modification=False,
            supports_fractional_shares=False,
            supports_streaming_quotes=False,
            supports_account_polling=True,
            max_order_quantity_limit=50000,
        )

    def get_account_state(self) -> BrokerAccountState:
        """Return normalized account balances, cash, buying power, and positions."""
        with self._lock:
            return BrokerAccountState.from_paper_account(self.account, broker_name="PaperBrokerAdapter")

    def get_positions(self) -> Dict[str, BrokerPosition]:
        """Return normalized open stock positions."""
        with self._lock:
            return {sym: BrokerPosition.from_paper_position(p) for sym, p in self.account.positions.items()}

    def get_connection_state(self) -> BrokerConnectionState:
        """Return operational connection state for the paper broker."""
        return BrokerConnectionState.SIMULATED_ACTIVE

    def reset(self, initial_cash: Optional[float] = None) -> None:
        """Reset paper account, order book, fill history, and idempotency cache."""
        with self._lock:
            cash = float(initial_cash) if initial_cash is not None else self.initial_cash
            self.account = PaperAccount(
                initial_cash=cash,
                cash=cash,
                buying_power=cash,
                total_equity=cash,
            )
            self._token_to_order_id.clear()

    # ── Private Helpers ───────────────────────────────────────────────────────

    def _build_account_snapshot(self) -> Dict[str, Any]:
        return {
            "cash": self.account.cash,
            "total_equity": self.account.total_equity,
            "buying_power": self.account.buying_power,
            "realized_pnl": self.account.realized_pnl,
            "unrealized_pnl": self.account.unrealized_pnl,
            "open_positions_count": len([p for p in self.account.positions.values() if p.quantity > 0]),
        }

    def _create_rejected_order(
        self,
        authorization: Optional[ExecutionAuthorizationSnapshot],
        reason: str,
        now: datetime,
    ) -> PaperExecutionResult:
        order = PaperOrder(
            order_id=f"pord-rej-{uuid.uuid4().hex[:8]}",
            authorization_id=authorization.authorization_id if authorization else "NONE",
            decision_id=authorization.decision_id if authorization else "NONE",
            symbol=authorization.symbol if authorization else "NONE",
            side=authorization.side if authorization else PreflightSide.BUY,
            requested_quantity=max(0, authorization.approved_quantity) if authorization else 0,
            remaining_quantity=0,
            status=PaperOrderStatus.REJECTED,
            created_at=now,
            updated_at=now,
            idempotency_token=authorization.idempotency_token if authorization else f"rej-{uuid.uuid4().hex[:8]}",
            rejection_reason=reason,
        )
        return PaperExecutionResult(
            order=order,
            status=PaperOrderStatus.REJECTED,
            new_fills=[],
            account_snapshot=self._build_account_snapshot(),
            message=reason,
        )


# Global shared singleton instance
global_paper_broker = PaperBrokerAdapter()
