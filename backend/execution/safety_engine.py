"""
Execution Safety Engine — Phase 5.1

Central coordinator for kill switch protection, duplicate order prevention,
and deterministic conversion from Investment Committee decisions to executable orders.
"""

from datetime import datetime
import threading
from typing import Dict, Optional, Set
import uuid

from backend.domain.execution_schemas import (
    ExecutionDecision,
    OrderRequest,
    OrderSide,
    OrderType,
    OrderValidationResult,
    PortfolioState,
    RejectionReason,
    RiskLimits,
)
from backend.domain.investment_committee_schemas import (
    InvestmentAction,
    InvestmentDecision,
    InvestmentDecisionState,
)
from backend.domain.schemas import MarketContext
from backend.execution.order_validator import OrderValidator


class KillSwitch:
    """
    Thread-safe emergency kill switch. When active, all order execution is unconditionally halted.
    """

    def __init__(self, initially_active: bool = False) -> None:
        self._active = bool(initially_active)
        self._lock = threading.Lock()

    def activate(self) -> None:
        """Engage the kill switch. Halts all order execution."""
        with self._lock:
            self._active = True

    def deactivate(self) -> None:
        """Disengage the kill switch."""
        with self._lock:
            self._active = False

    def is_active(self) -> bool:
        """Check current kill switch status."""
        with self._lock:
            return self._active


class DuplicateTracker:
    """
    Prevents accidental duplicate orders for the same decision / context snapshot.
    """

    def __init__(self) -> None:
        self._seen_keys: Set[str] = set()
        self._lock = threading.Lock()

    def _make_key(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        context_id: str,
        run_id: Optional[str] = None,
    ) -> str:
        return f"{symbol}|{side.value}|{quantity}|{context_id}|{run_id or ''}"

    def is_duplicate(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        context_id: str,
        run_id: Optional[str] = None,
    ) -> bool:
        key = self._make_key(symbol, side, quantity, context_id, run_id)
        with self._lock:
            return key in self._seen_keys

    def record_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        context_id: str,
        run_id: Optional[str] = None,
    ) -> None:
        key = self._make_key(symbol, side, quantity, context_id, run_id)
        with self._lock:
            self._seen_keys.add(key)

    def clear(self) -> None:
        with self._lock:
            self._seen_keys.clear()


class ExecutionSafetyEngine:
    """
    Coordinates the execution safety boundary before any order reaches the broker.
    """

    def __init__(
        self,
        validator: Optional[OrderValidator] = None,
        kill_switch: Optional[KillSwitch] = None,
        duplicate_tracker: Optional[DuplicateTracker] = None,
    ) -> None:
        self.validator = validator or OrderValidator()
        self.kill_switch = kill_switch or KillSwitch()
        self.duplicate_tracker = duplicate_tracker or DuplicateTracker()

    def evaluate_order(
        self,
        order: OrderRequest,
        portfolio_state: PortfolioState,
        market_context: Optional[MarketContext] = None,
        decision: Optional[InvestmentDecision] = None,
    ) -> OrderValidationResult:
        """
        Evaluate an order request across all safety layers in strict deterministic order.
        """
        # 1. Kill Switch Check (Highest Priority)
        if self.kill_switch.is_active():
            return OrderValidationResult(
                is_valid=False,
                decision=ExecutionDecision.BLOCKED,
                rejection_reasons=[RejectionReason.KILL_SWITCH],
                rejection_details=["Emergency Kill Switch is ACTIVE. All trading blocked."],
                checks_passed=[],
                checks_failed=["Emergency Kill Switch"],
                validated_at=datetime.utcnow(),
            )

        # 2. Duplicate Order Check
        if self.duplicate_tracker.is_duplicate(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            context_id=order.context_id,
            run_id=order.run_id,
        ):
            return OrderValidationResult(
                is_valid=False,
                decision=ExecutionDecision.BLOCKED,
                rejection_reasons=[RejectionReason.DUPLICATE_ORDER],
                rejection_details=["Duplicate order: Identical order already processed for this context/run"],
                checks_passed=["Emergency Kill Switch"],
                checks_failed=["Duplicate order check"],
                validated_at=datetime.utcnow(),
            )

        # 3. Comprehensive Deterministic Order Validation
        validation = self.validator.validate(
            order=order,
            portfolio_state=portfolio_state,
            market_context=market_context,
            decision=decision,
        )

        return validation

    def create_order_from_decision(
        self,
        decision: InvestmentDecision,
        market_context: MarketContext,
        portfolio_state: PortfolioState,
        current_price: Optional[float] = None,
    ) -> Optional[OrderRequest]:
        """
        Deterministically convert an InvestmentDecision into an OrderRequest.
        Returns None if decision is not executable (HOLD, REJECT, RISK_VETO, etc.)
        or if position sizing is unavailable.
        """
        # Only APPROVE decisions are executable for new orders
        if decision.state != InvestmentDecisionState.APPROVE:
            return None

        # Check action
        plan = decision.execution_plan
        if plan.action != InvestmentAction.BUY:
            return None

        # Check position sizing
        sizing = plan.position_sizing
        if not sizing.is_available or sizing.recommended_size_pct <= 0.0:
            return None

        price = current_price if current_price and current_price > 0 else market_context.current_price
        if price <= 0:
            return None

        # Calculate integer share quantity based on portfolio equity
        total_equity = portfolio_state.total_equity if portfolio_state.total_equity > 0 else portfolio_state.cash
        target_allocation_value = total_equity * (sizing.recommended_size_pct / 100.0)
        quantity = int(target_allocation_value / price)

        if quantity <= 0:
            return None

        order_id = f"ord-{uuid.uuid4().hex[:8]}"

        return OrderRequest(
            order_id=order_id,
            symbol=decision.symbol,
            side=OrderSide.BUY,
            quantity=float(quantity),
            price=float(price),
            order_type=OrderType.MARKET,
            context_id=market_context.context_id,
            run_id=decision.run_id,
            decision_id=decision.decision_id,
            created_at=market_context.data_timestamp,
            provenance={
                "decision_state": decision.state.value,
                "confidence": decision.confidence,
                "recommended_size_pct": sizing.recommended_size_pct,
                "calculated_quantity": quantity,
                "market_context_id": market_context.context_id,
            },
        )
