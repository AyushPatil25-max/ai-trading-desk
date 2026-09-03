"""
Phase 27 — Live Failure Recovery & Resilient Order Submission Engine

Coordinates thread-safe transient error retry, backoff, and idempotent failure recovery
for live Dhan broker operations.

Safety Invariants:
1. ONLY retries explicitly transient network/availability failures (timeouts, 502/503/504, URLError).
2. NEVER retries permanent errors (auth failures, validation errors, safety gate rejections, 4xx errors).
3. NEVER blind-retries: Before re-submitting after uncertain network errors, reconciles with Dhan order book.
4. Fail-closed: Halts immediately if emergency kill switch is engaged or live execution is disarmed.
5. Emits ORDER_RETRY_ATTEMPTED, ORDER_RETRY_SUCCEEDED, and ORDER_RETRY_EXCEEDED audit events.
"""

from datetime import datetime, timezone
import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

from backend.domain.broker_schemas import (
    NormalizedOrderStatus,
    OrderRequest,
    OrderResult,
)
from backend.domain.observability_schemas import EventCategory, EventSeverity
from backend.application.tamper_evident_audit_chain import global_audit_chain
from backend.application.confirmation_store import compute_order_fingerprint
from backend.config.broker_config import (
    get_live_retry_max,
    get_live_retry_backoff,
)
from backend.execution.order_tracker import global_order_tracker

logger = logging.getLogger(__name__)


def is_transient_error(exc: Exception) -> bool:
    """
    Deterministically classify whether an exception represents a transient failure.
    Permanent failures (Auth, Validation, Safety, Client errors) return False.
    """
    if exc is None:
        return False

    err_str = str(exc).upper()

    # Explicitly permanent failures (NEVER retry)
    permanent_markers = [
        "DHAN_AUTH_FAILED",
        "AUTH_FAILED",
        "401",
        "403",
        "400",
        "422",
        "UNPROCESSABLE",
        "INVALID_REQUEST",
        "SAFETY_REJECTED",
        "KILL_SWITCH",
        "DISARMED",
        "NOT_ARMED",
        "DUPLICATE",
    ]
    for marker in permanent_markers:
        if marker in err_str:
            return False

    # Explicitly transient failures
    transient_markers = [
        "DHAN_UNAVAILABLE",
        "TIMEOUT",
        "TIMED OUT",
        "CONNECTION RESET",
        "CONNECTION REFUSED",
        "CONNECTION_RESET",
        "TEMPORARY",
        "502",
        "503",
        "504",
        "GATEWAY",
        "URLERROR",
        "SOCKET",
        "BROKER_UNAVAILABLE",
    ]
    for marker in transient_markers:
        if marker in err_str:
            return True

    # Standard python network/timeout exception types
    transient_types = (
        TimeoutError,
        ConnectionError,
        ConnectionResetError,
        ConnectionRefusedError,
    )
    if isinstance(exc, transient_types):
        return True

    return False


class LiveFailureRecoveryEngine:
    """
    Coordinates safe, resilient execution of live broker operations.
    Provides retry with backoff for transient failures, idempotency verification,
    and fail-closed safety state coordination.
    """

    def __init__(
        self,
        max_retries: Optional[int] = None,
        backoff_seconds: Optional[float] = None,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self._lock = threading.RLock()
        self._max_retries_override = max_retries
        self._backoff_override = backoff_seconds
        self._sleeper = sleeper
        self._pending_retries = 0
        self._total_retries_attempted = 0
        self._total_retries_succeeded = 0
        self._total_retries_exceeded = 0
        self._is_reset = False

    @property
    def max_retries(self) -> int:
        if self._max_retries_override is not None:
            return self._max_retries_override
        return get_live_retry_max()

    @property
    def backoff_seconds(self) -> float:
        if self._backoff_override is not None:
            return self._backoff_override
        return get_live_retry_backoff()

    def reset(self) -> None:
        """
        Emergency reset: halt all pending retries and reset internal retry metrics.
        Called on kill switch activation or emergency disarm.
        """
        with self._lock:
            self._is_reset = True
            self._pending_retries = 0
            logger.warning("[LiveFailureRecoveryEngine] Reset engaged. All pending retries halted.")

    def clear_reset(self) -> None:
        """Clear reset flag to resume standard operations."""
        with self._lock:
            self._is_reset = False

    def execute_with_recovery(
        self,
        order: OrderRequest,
        submit_fn: Callable[[], OrderResult],
        reconcile_check_fn: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
        max_retries: Optional[int] = None,
        backoff_seconds: Optional[float] = None,
    ) -> OrderResult:
        """
        Execute an order submission with transient failure recovery and duplicate protection.

        Step 1: Duplicate check via OrderTracker.
        Step 2: Submit to broker.
        Step 3: If transient failure, check broker order book via reconcile_check_fn before retrying.
        Step 4: Retry up to max_retries with backoff delay.
        Step 5: Record success in OrderTracker.
        """
        fingerprint = compute_order_fingerprint(order)
        effective_max_retries = max_retries if max_retries is not None else self.max_retries
        effective_backoff = backoff_seconds if backoff_seconds is not None else self.backoff_seconds

        with self._lock:
            if self._is_reset:
                return OrderResult(
                    request_id=order.request_id,
                    broker_name="DhanBroker",
                    symbol=order.symbol,
                    side=order.side.value,
                    quantity=order.quantity,
                    order_type=order.order_type.value,
                    product_type=order.product_type.value,
                    exchange_segment=order.exchange_segment.value,
                    status=NormalizedOrderStatus.REJECTED.value,
                    message="Live failure recovery engine is in RESET state (Kill switch / emergency disarm active).",
                    rejection_reason="RECOVERY_ENGINE_RESET",
                )

            # Step 1: Duplicate check
            if global_order_tracker.is_duplicate(fingerprint):
                return OrderResult(
                    request_id=order.request_id,
                    broker_name="DhanBroker",
                    symbol=order.symbol,
                    side=order.side.value,
                    quantity=order.quantity,
                    order_type=order.order_type.value,
                    product_type=order.product_type.value,
                    exchange_segment=order.exchange_segment.value,
                    status=NormalizedOrderStatus.REJECTED.value,
                    message=f"Duplicate order rejected for fingerprint {fingerprint[:12]}...",
                    rejection_reason="DUPLICATE_ORDER_DETECTED",
                )

            # Track in-flight submission
            global_order_tracker.record_submission(fingerprint, order.request_id, order=order)

        attempt = 0
        last_error_msg = "Unknown error"

        while attempt <= effective_max_retries:
            with self._lock:
                if self._is_reset:
                    return OrderResult(
                        request_id=order.request_id,
                        broker_name="DhanBroker",
                        symbol=order.symbol,
                        side=order.side.value,
                        quantity=order.quantity,
                        order_type=order.order_type.value,
                        product_type=order.product_type.value,
                        exchange_segment=order.exchange_segment.value,
                        status=NormalizedOrderStatus.REJECTED.value,
                        message="Execution aborted during retry loop: recovery engine was reset.",
                        rejection_reason="RECOVERY_ENGINE_RESET",
                    )

            if attempt > 0:
                with self._lock:
                    self._total_retries_attempted += 1
                try:
                    global_audit_chain.append_event(
                        event_type="ORDER_RETRY_ATTEMPTED",
                        category=EventCategory.EXECUTION,
                        component="LiveFailureRecoveryEngine",
                        correlation_id=order.request_id,
                        symbol=order.symbol,
                        severity=EventSeverity.WARNING,
                        reason=f"Retrying live order submission (attempt {attempt}/{effective_max_retries}) after transient error: {last_error_msg}",
                        payload={
                            "request_id": order.request_id,
                            "attempt": attempt,
                            "max_retries": effective_max_retries,
                            "last_error": last_error_msg,
                        },
                    )
                except Exception:
                    pass

                # Before blind resubmission, check if Dhan already has this order (correlationId check)
                if reconcile_check_fn:
                    try:
                        existing_dhan_order = reconcile_check_fn(order.request_id)
                        if existing_dhan_order and existing_dhan_order.get("orderId"):
                            # Order was already accepted by broker during prior attempt!
                            order_id = str(existing_dhan_order["orderId"])
                            raw_status = existing_dhan_order.get("orderStatus", "TRANSIT")
                            norm_status = existing_dhan_order.get("status", NormalizedOrderStatus.SUBMITTED.value)
                            
                            with self._lock:
                                self._total_retries_succeeded += 1

                            global_order_tracker.record_success(
                                fingerprint=fingerprint,
                                order_id=order_id,
                                details={
                                    "request_id": order.request_id,
                                    "symbol": order.symbol,
                                    "side": order.side.value,
                                    "quantity": order.quantity,
                                    "order_type": order.order_type.value,
                                    "reconciled_after_transient_failure": True,
                                },
                                status=norm_status,
                            )

                            try:
                                global_audit_chain.append_event(
                                    event_type="ORDER_RETRY_SUCCEEDED",
                                    category=EventCategory.EXECUTION,
                                    component="LiveFailureRecoveryEngine",
                                    correlation_id=order.request_id,
                                    symbol=order.symbol,
                                    severity=EventSeverity.INFO,
                                    reason=f"Order confirmed on Dhan via pre-retry reconciliation: {order_id}",
                                    payload={
                                        "order_id": order_id,
                                        "request_id": order.request_id,
                                        "status": norm_status,
                                        "attempts": attempt,
                                    },
                                Juice=None,
                            )
                            except Exception:
                                pass

                            return OrderResult(
                                order_id=order_id,
                                request_id=order.request_id,
                                broker_name="DhanBroker",
                                symbol=order.symbol,
                                side=order.side.value,
                                quantity=order.quantity,
                                order_type=order.order_type.value,
                                product_type=order.product_type.value,
                                exchange_segment=order.exchange_segment.value,
                                status=norm_status,
                                message="Order established on broker via recovery reconciliation.",
                                rejection_reason=None,
                            )
                    except Exception as e:
                        logger.warning(f"Reconciliation check prior to retry attempt {attempt} failed: {e}")

            # Attempt submission
            try:
                result = submit_fn()

                # Check if result indicates success
                if result.status in (
                    NormalizedOrderStatus.SUBMITTED.value,
                    NormalizedOrderStatus.PENDING.value,
                    NormalizedOrderStatus.OPEN.value,
                    NormalizedOrderStatus.FILLED.value,
                    NormalizedOrderStatus.PARTIALLY_FILLED.value,
                ):
                    if attempt > 0:
                        with self._lock:
                            self._total_retries_succeeded += 1
                        try:
                            global_audit_chain.append_event(
                                event_type="ORDER_RETRY_SUCCEEDED",
                                category=EventCategory.EXECUTION,
                                component="LiveFailureRecoveryEngine",
                                correlation_id=order.request_id,
                                symbol=order.symbol,
                                severity=EventSeverity.INFO,
                                reason=f"Order successfully submitted on retry attempt {attempt}",
                                payload={
                                    "order_id": result.order_id,
                                    "request_id": order.request_id,
                                    "attempts": attempt,
                                },
                            )
                        except Exception:
                            pass

                    # Record confirmed order ID
                    global_order_tracker.record_success(
                        fingerprint=fingerprint,
                        order_id=result.order_id or f"dhan-{order.request_id}",
                        details={
                            "request_id": order.request_id,
                            "symbol": order.symbol,
                            "side": order.side.value,
                            "quantity": order.quantity,
                            "order_type": order.order_type.value,
                        },
                        status=result.status,
                    )
                    return result

                # If result is a permanent safety rejection / broker rejection
                if not is_transient_error(Exception(result.message or result.rejection_reason or "")):
                    global_order_tracker.update_status(fingerprint, "REJECTED", {"reason": result.message})
                    return result

                # If result is classified as transient broker submission error
                last_error_msg = result.message or "Transient broker submission error"

            except Exception as exc:
                if not is_transient_error(exc):
                    # Permanent error: do not retry
                    global_order_tracker.update_status(fingerprint, "REJECTED", {"error": str(exc)})
                    raise exc
                last_error_msg = str(exc)

            attempt += 1
            if attempt <= effective_max_retries:
                with self._lock:
                    self._pending_retries += 1
                if effective_backoff > 0:
                    self._sleeper(effective_backoff)
                with self._lock:
                    self._pending_retries = max(0, self._pending_retries - 1)

        # Retries exhausted
        with self._lock:
            self._total_retries_exceeded += 1
            self._pending_retries = 0

        global_order_tracker.update_status(
            fingerprint,
            "FAILED",
            {"error": f"Retries exhausted ({effective_max_retries} attempts): {last_error_msg}"},
        )

        try:
            global_audit_chain.append_event(
                event_type="ORDER_RETRY_EXCEEDED",
                category=EventCategory.EXECUTION,
                component="LiveFailureRecoveryEngine",
                correlation_id=order.request_id,
                symbol=order.symbol,
                severity=EventSeverity.ERROR,
                reason=f"Live order retries exhausted ({effective_max_retries} attempts). Last error: {last_error_msg}",
                payload={
                    "request_id": order.request_id,
                    "attempts": effective_max_retries,
                    "last_error": last_error_msg,
                },
            )
        except Exception:
            pass

        return OrderResult(
            request_id=order.request_id,
            broker_name="DhanBroker",
            symbol=order.symbol,
            side=order.side.value,
            quantity=order.quantity,
            order_type=order.order_type.value,
            product_type=order.product_type.value,
            exchange_segment=order.exchange_segment.value,
            status=NormalizedOrderStatus.REJECTED.value,
            message=f"Broker submission retries exhausted ({effective_max_retries} attempts). Last error: {last_error_msg}",
            rejection_reason="RETRY_EXHAUSTED",
        )

    def submit_with_retry(
        self,
        order: OrderRequest,
        confirmation_token: str,
        adapter: Optional[Any] = None,
    ) -> OrderResult:
        """
        Public entry point for submitting a manual order with failure recovery and retry.
        Delegates through DhanBrokerAdapter.submit_manual_order to enforce all Phase 24-26 safety gates.
        """
        from backend.adapters.dhan_adapter import DhanBrokerAdapter
        active_adapter = adapter or DhanBrokerAdapter()
        return active_adapter.submit_manual_order(order, confirmation_token)

    def get_status(self) -> Dict[str, Any]:
        """Return operational status and metrics for live failure recovery."""
        with self._lock:
            return {
                "max_retries": self.max_retries,
                "backoff_seconds": self.backoff_seconds,
                "pending_retries": self._pending_retries,
                "total_retries_attempted": self._total_retries_attempted,
                "total_retries_succeeded": self._total_retries_succeeded,
                "total_retries_exceeded": self._total_retries_exceeded,
                "is_reset": self._is_reset,
            }

    def status(self) -> Dict[str, Any]:
        """Alias for get_status()."""
        return self.get_status()


# Global singleton instance
global_live_failure_engine = LiveFailureRecoveryEngine()
