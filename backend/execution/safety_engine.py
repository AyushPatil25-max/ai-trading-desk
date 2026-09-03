from backend.config.app_config import get_app_config
"""
Execution Safety Engine — Phase 5.1

Central coordinator for kill switch protection, duplicate order prevention,
and deterministic conversion from Investment Committee decisions to executable orders.
"""

from datetime import datetime, timezone
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
        """Engage the kill switch. Halts all order execution and triggers emergency recovery purge."""
        with self._lock:
            self._active = True

        # Phase 27: Integrated recovery purge
        try:
            from backend.execution.live_failure_recovery import global_live_failure_engine
            global_live_failure_engine.reset()
        except Exception:
            pass

        try:
            from backend.execution.order_tracker import global_order_tracker
            global_order_tracker.clear()
        except Exception:
            pass

        try:
            from backend.execution.live_arming_store import global_live_arming_store
            global_live_arming_store.disarm(reason="Emergency Kill Switch Activated")
        except Exception:
            pass

        try:
            from backend.application.tamper_evident_audit_chain import global_audit_chain
            from backend.domain.observability_schemas import EventCategory, EventSeverity
            global_audit_chain.append_event(
                event_type="KILL_SWITCH_RECOVERY",
                category=EventCategory.SECURITY,
                component="KillSwitch",
                correlation_id=f"killswitch-{uuid.uuid4().hex[:8]}",
                severity=EventSeverity.CRITICAL,
                reason="Emergency Kill Switch engaged: pending retries purged, order tracker cleared, live trading disarmed.",
                payload={"kill_switch_active": True},
            )
        except Exception:
            pass

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
                validated_at=datetime.now(timezone.utc),
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
                validated_at=datetime.now(timezone.utc),
            )

        # 3. Comprehensive Deterministic Order Validation
        validation = self.validator.validate(
            order=order,
            portfolio_state=portfolio_state,
            market_context=market_context,
            decision=decision,
        )

        return validation

    def is_kill_switch_active(self) -> bool:
        """Check if kill switch is active."""
        return self.kill_switch.is_active()

    def engage_kill_switch(self, reason: Optional[str] = None) -> None:
        """Engage the kill switch."""
        self.kill_switch.activate()

    def disengage_kill_switch(self) -> None:
        """Disengage the kill switch."""
        self.kill_switch.deactivate()

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


# ── Phase 24 — Manual Order Safety Gate for Dhan ────────────────────────────

import os
from backend.domain.broker_schemas import (
    ExchangeSegment,
    OrderPreview,
    OrderRequest as BrokerOrderRequestDomain,
    OrderSide as BrokerOrderSide,
    OrderType as BrokerOrderType,
    ProductType,
    SafetyGateResult,
    SafetyReasonCode,
)
from backend.domain.observability_schemas import EventCategory, EventSeverity
from backend.application.tamper_evident_audit_chain import global_audit_chain


def build_dhan_order_payload(order: BrokerOrderRequestDomain, dhan_client_id: str) -> Dict[str, Any]:
    """
    Construct official Dhan v2 order payload from a validated BrokerOrderRequestDomain.
    """
    segment_map = {
        ExchangeSegment.NSE: "NSE_EQ",
        ExchangeSegment.BSE: "BSE_EQ",
        ExchangeSegment.NSE_FNO: "NSE_FNO",
        ExchangeSegment.BSE_FNO: "BSE_FNO",
    }
    exchange_segment_str = segment_map.get(order.exchange_segment, order.exchange_segment.value)

    return {
        "dhanClientId": dhan_client_id,
        "correlationId": order.request_id,
        "transactionType": order.side.value,
        "exchangeSegment": exchange_segment_str,
        "productType": order.product_type.value,
        "orderType": order.order_type.value,
        "validity": order.validity,
        "securityId": order.symbol,
        "quantity": int(order.quantity),
        "disclosedQuantity": 0,
        "price": float(order.price) if order.price is not None else 0.0,
        "triggerPrice": float(order.trigger_price) if order.trigger_price is not None else 0.0,
        "afterMarketOrder": False,
    }


class ManualOrderSafetyGate:
    """
    Phase 24 — Deterministic Safety Gate for Manual Dhan Orders.
    Enforces strict fail-closed safety boundary before any order can reach live broker execution.
    """

    def __init__(
        self,
        kill_switch: Optional[KillSwitch] = None,
        max_quantity_limit: int = 50_000,
        max_order_value_limit: float = 200_000.0,
    ) -> None:
        self.kill_switch = kill_switch or KillSwitch()
        self.max_quantity_limit = max_quantity_limit
        self.max_order_value_limit = max_order_value_limit

    def evaluate_order(
        self,
        order: BrokerOrderRequestDomain,
        target_broker: str = "Dhan",
        require_live_enabled: bool = True,
        buying_power: Optional[float] = None,
        reference_price: Optional[float] = None,
        data_timestamp: Optional[datetime] = None,
    ) -> SafetyGateResult:
        """
        Evaluate an OrderRequest across all 15+ safety checks in deterministic sequence.
        Fails closed on any error, missing config, invalid parameter, or policy violation.
        """
        checks_performed: list[str] = []
        checks_passed: list[str] = []
        checks_failed: list[str] = []

        now = datetime.now(timezone.utc)

        def _reject(code: SafetyReasonCode, msg: str, est_val: Optional[float] = None) -> SafetyGateResult:
            try:
                global_audit_chain.append_event(
                    event_type="ORDER_SAFETY_REJECTED",
                    category=EventCategory.SECURITY,
                    component="ManualOrderSafetyGate",
                    correlation_id=getattr(order, "request_id", "UNKNOWN"),
                    symbol=getattr(order, "symbol", "UNKNOWN"),
                    severity=EventSeverity.WARNING,
                    reason=f"Safety Gate Rejected: {code.value} - {msg}",
                    payload={
                        "reason_code": code.value,
                        "details": msg,
                        "checks_failed": checks_failed,
                    },
                )
            except Exception:
                pass

            return SafetyGateResult(
                is_approved=False,
                reason_code=code,
                reason=msg,
                validated_order=order if isinstance(order, BrokerOrderRequestDomain) else None,
                estimated_order_value=est_val,
                safety_checks_performed=checks_performed,
                safety_checks_passed=checks_passed,
                safety_checks_failed=checks_failed,
                evaluated_at=now,
            )

        try:
            # 1. Structural validity
            checks_performed.append("STRUCTURAL_VALIDITY")
            if not isinstance(order, BrokerOrderRequestDomain):
                checks_failed.append("STRUCTURAL_VALIDITY")
                return _reject(SafetyReasonCode.SAFETY_CHECK_UNAVAILABLE, "Order request is not a valid OrderRequest instance.")
            checks_passed.append("STRUCTURAL_VALIDITY")

            # 2. Kill Switch
            checks_performed.append("KILL_SWITCH")
            if self.kill_switch.is_active():
                checks_failed.append("KILL_SWITCH")
                return _reject(SafetyReasonCode.KILL_SWITCH_ACTIVE, "Emergency Kill Switch is ACTIVE. All order execution is halted.")
            checks_passed.append("KILL_SWITCH")

            # 3. Target Broker Identity
            checks_performed.append("BROKER_IDENTITY")
            if not target_broker or target_broker.lower() not in ("dhan", "dhanbroker"):
                checks_failed.append("BROKER_IDENTITY")
                return _reject(SafetyReasonCode.BROKER_NOT_CONFIGURED, f"Target broker must be 'Dhan', received '{target_broker}'.")
            checks_passed.append("BROKER_IDENTITY")

            # 4. Broker Configuration
            checks_performed.append("BROKER_CONFIGURATION")
            app_config = get_app_config()
            dhan_enabled = app_config.dhan_enabled
            client_id = app_config.dhan_client_id
            access_token = app_config.dhan_access_token
            if not (dhan_enabled and client_id and access_token):
                checks_failed.append("BROKER_CONFIGURATION")
                return _reject(SafetyReasonCode.BROKER_NOT_CONFIGURED, "Dhan broker configuration is missing or disabled (DHAN_ENABLED, DHAN_CLIENT_ID, or DHAN_ACCESS_TOKEN not configured).")
            checks_passed.append("BROKER_CONFIGURATION")

            # 5. Live Execution Flag
            checks_performed.append("LIVE_EXECUTION_FLAG")
            live_enabled = get_app_config().live_execution_enabled
            if require_live_enabled and not live_enabled:
                checks_failed.append("LIVE_EXECUTION_FLAG")
                return _reject(SafetyReasonCode.LIVE_EXECUTION_DISABLED, "LIVE_EXECUTION_ENABLED is false. Real-money live execution is locked (fail-closed).")
            checks_passed.append("LIVE_EXECUTION_FLAG")

            # 6. Symbol Validation
            checks_performed.append("SYMBOL_VALIDATION")
            if not order.symbol or not isinstance(order.symbol, str) or not order.symbol.strip():
                checks_failed.append("SYMBOL_VALIDATION")
                return _reject(SafetyReasonCode.INVALID_SYMBOL, "Security/symbol identifier is missing or empty.")
            sym = order.symbol.strip().upper()
            if len(sym) < 1 or len(sym) > 30:
                checks_failed.append("SYMBOL_VALIDATION")
                return _reject(SafetyReasonCode.INVALID_SYMBOL, f"Symbol length out of bounds: '{sym}'.")
            checks_passed.append("SYMBOL_VALIDATION")

            # 7. Exchange Segment Validation
            checks_performed.append("EXCHANGE_SEGMENT")
            if not isinstance(order.exchange_segment, ExchangeSegment) or order.exchange_segment not in ExchangeSegment:
                checks_failed.append("EXCHANGE_SEGMENT")
                return _reject(SafetyReasonCode.INVALID_EXCHANGE, f"Invalid exchange segment '{order.exchange_segment}'.")
            checks_passed.append("EXCHANGE_SEGMENT")

            # 8. Side Validation
            checks_performed.append("SIDE_VALIDATION")
            if not isinstance(order.side, BrokerOrderSide) or order.side not in (BrokerOrderSide.BUY, BrokerOrderSide.SELL):
                checks_failed.append("SIDE_VALIDATION")
                return _reject(SafetyReasonCode.INVALID_ORDER_TYPE, f"Invalid transaction side '{order.side}'. Must be BUY or SELL.")
            checks_passed.append("SIDE_VALIDATION")

            # 9. Quantity Validation
            checks_performed.append("QUANTITY_VALIDATION")
            if not isinstance(order.quantity, int) or isinstance(order.quantity, bool) or order.quantity <= 0:
                checks_failed.append("QUANTITY_VALIDATION")
                return _reject(SafetyReasonCode.INVALID_QUANTITY, f"Order quantity must be a positive integer > 0, got {order.quantity}.")
            if order.quantity > self.max_quantity_limit:
                checks_failed.append("QUANTITY_VALIDATION")
                return _reject(SafetyReasonCode.QUANTITY_LIMIT_EXCEEDED, f"Quantity {order.quantity} exceeds maximum allowed limit of {self.max_quantity_limit}.")
            checks_passed.append("QUANTITY_VALIDATION")

            # 10. Order Type & Product Type
            checks_performed.append("ORDER_TYPE_VALIDATION")
            if not isinstance(order.order_type, BrokerOrderType) or order.order_type not in (BrokerOrderType.MARKET, BrokerOrderType.LIMIT):
                checks_failed.append("ORDER_TYPE_VALIDATION")
                return _reject(SafetyReasonCode.INVALID_ORDER_TYPE, f"Unsupported order type '{order.order_type}'.")
            checks_passed.append("ORDER_TYPE_VALIDATION")

            checks_performed.append("PRODUCT_TYPE_VALIDATION")
            if not isinstance(order.product_type, ProductType) or order.product_type not in (ProductType.CNC, ProductType.MIS, ProductType.NRML):
                checks_failed.append("PRODUCT_TYPE_VALIDATION")
                return _reject(SafetyReasonCode.INVALID_PRODUCT_TYPE, f"Unsupported product type '{order.product_type}'.")
            checks_passed.append("PRODUCT_TYPE_VALIDATION")

            # 11. Price Validation
            checks_performed.append("PRICE_VALIDATION")
            if order.order_type == BrokerOrderType.LIMIT:
                if order.price is None or not isinstance(order.price, (int, float)) or order.price <= 0.0:
                    checks_failed.append("PRICE_VALIDATION")
                    return _reject(SafetyReasonCode.INVALID_PRICE, f"LIMIT order requires a strictly positive price > 0, received {order.price}.")
            if order.price is not None and order.price < 0.0:
                checks_failed.append("PRICE_VALIDATION")
                return _reject(SafetyReasonCode.INVALID_PRICE, f"Price cannot be negative: {order.price}.")
            checks_passed.append("PRICE_VALIDATION")

            # 12. Trigger Price Validation
            checks_performed.append("TRIGGER_PRICE_VALIDATION")
            if order.trigger_price is not None:
                if not isinstance(order.trigger_price, (int, float)) or order.trigger_price <= 0.0:
                    checks_failed.append("TRIGGER_PRICE_VALIDATION")
                    return _reject(SafetyReasonCode.INVALID_TRIGGER_PRICE, f"Trigger price must be positive > 0, received {order.trigger_price}.")
            checks_passed.append("TRIGGER_PRICE_VALIDATION")

            # 13. Estimated Order Value & Value Limit
            checks_performed.append("ORDER_VALUE_LIMIT")
            effective_price = order.price if (order.price is not None and order.price > 0) else reference_price
            estimated_value = 0.0
            if effective_price is not None and effective_price > 0:
                estimated_value = float(order.quantity) * float(effective_price)

            if estimated_value > self.max_order_value_limit:
                checks_failed.append("ORDER_VALUE_LIMIT")
                return _reject(
                    SafetyReasonCode.ORDER_VALUE_LIMIT_EXCEEDED,
                    f"Estimated order value ₹{estimated_value:,.2f} exceeds maximum limit of ₹{self.max_order_value_limit:,.2f}.",
                    est_val=estimated_value,
                )
            checks_passed.append("ORDER_VALUE_LIMIT")

            # 14. Buying Power Check
            checks_performed.append("BUYING_POWER")
            if order.side == BrokerOrderSide.BUY and buying_power is not None and buying_power >= 0 and estimated_value > 0:
                if estimated_value > buying_power:
                    checks_failed.append("BUYING_POWER")
                    return _reject(
                        SafetyReasonCode.INSUFFICIENT_BUYING_POWER,
                        f"Insufficient buying power: Required ₹{estimated_value:,.2f}, available ₹{buying_power:,.2f}.",
                        est_val=estimated_value,
                    )
            checks_passed.append("BUYING_POWER")

            # 15. Stale Data Check
            checks_performed.append("DATA_FRESHNESS")
            if data_timestamp:
                dt = data_timestamp if data_timestamp.tzinfo else data_timestamp.replace(tzinfo=timezone.utc)
                age_sec = (now - dt).total_seconds()
                if age_sec > 300:
                    checks_failed.append("DATA_FRESHNESS")
                    return _reject(SafetyReasonCode.STALE_DATA, f"Market data timestamp is stale ({age_sec:.1f}s > 300s).", est_val=estimated_value)
            checks_passed.append("DATA_FRESHNESS")

            # All checks cleared!
            try:
                global_audit_chain.append_event(
                    event_type="ORDER_SAFETY_CHECKED",
                    category=EventCategory.SECURITY,
                    component="ManualOrderSafetyGate",
                    correlation_id=order.request_id,
                    symbol=order.symbol,
                    severity=EventSeverity.INFO,
                    reason="All manual order safety gate checks passed successfully",
                    payload={
                        "symbol": order.symbol,
                        "side": order.side.value,
                        "quantity": order.quantity,
                        "estimated_value": estimated_value,
                        "checks_passed_count": len(checks_passed),
                    },
                )
            except Exception:
                pass

            return SafetyGateResult(
                is_approved=True,
                reason_code=SafetyReasonCode.VALID,
                reason="All safety gate checks passed successfully.",
                validated_order=order,
                estimated_order_value=estimated_value,
                safety_checks_performed=checks_performed,
                safety_checks_passed=checks_passed,
                safety_checks_failed=[],
                evaluated_at=now,
            )

        except Exception as e:
            checks_failed.append("UNHANDLED_EXCEPTION")
            return _reject(SafetyReasonCode.SAFETY_CHECK_UNAVAILABLE, f"Safety gate validation encountered an unhandled error: {str(e)}")

    def preview_order(
        self,
        order: BrokerOrderRequestDomain,
        target_broker: str = "Dhan",
        buying_power: Optional[float] = None,
        reference_price: Optional[float] = None,
        data_timestamp: Optional[datetime] = None,
    ) -> Tuple[SafetyGateResult, OrderPreview]:
        """
        Validate an order for preview/preparation (does not enforce live execution flag).
        Constructs the OrderPreview and Dhan payload.
        """
        # Safety gate evaluation for preview (require_live_enabled=False)
        gate_res = self.evaluate_order(
            order=order,
            target_broker=target_broker,
            require_live_enabled=False,
            buying_power=buying_power,
            reference_price=reference_price,
            data_timestamp=data_timestamp,
        )

        client_id = get_app_config().dhan_client_id
        dhan_payload = build_dhan_order_payload(order, client_id) if gate_res.is_approved else {}

        preview = OrderPreview(
            request=order,
            dhan_payload=dhan_payload,
            is_valid=gate_res.is_approved,
            validation_errors=[] if gate_res.is_approved else [gate_res.reason],
        )

        if gate_res.is_approved:
            try:
                global_audit_chain.append_event(
                    event_type="ORDER_PREVIEW_CREATED",
                    category=EventCategory.SECURITY,
                    component="ManualOrderSafetyGate",
                    correlation_id=order.request_id,
                    symbol=order.symbol,
                    severity=EventSeverity.INFO,
                    reason="Order preview generated successfully",
                    payload={
                        "request_id": order.request_id,
                        "symbol": order.symbol,
                        "side": order.side.value,
                        "quantity": order.quantity,
                        "estimated_value": gate_res.estimated_order_value,
                    },
                )
            except Exception:
                pass

        return gate_res, preview


# Global singletons
global_kill_switch = KillSwitch()
global_execution_safety_engine = ExecutionSafetyEngine(kill_switch=global_kill_switch)
global_manual_order_safety_gate = ManualOrderSafetyGate()


def check_manual_order_safety(
    order: BrokerOrderRequestDomain,
    target_broker: str = "Dhan",
    require_live_enabled: bool = True,
    buying_power: Optional[float] = None,
    reference_price: Optional[float] = None,
    data_timestamp: Optional[datetime] = None,
) -> SafetyGateResult:
    """Convenience function for evaluating an order through the global manual safety gate."""
    return global_manual_order_safety_gate.evaluate_order(
        order=order,
        target_broker=target_broker,
        require_live_enabled=require_live_enabled,
        buying_power=buying_power,
        reference_price=reference_price,
        data_timestamp=data_timestamp,
    )


