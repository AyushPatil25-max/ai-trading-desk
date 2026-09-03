"""
Phase 24 — In-Memory Order Confirmation Store

Provides a thread-safe, in-memory store for cryptographically secure,
single-use manual order confirmation tokens.

Safety Invariants:
1. Cryptographically strong random tokens (secrets module).
2. Default TTL = 2 minutes (120 seconds).
3. Strictly single-use (cannot be reused).
4. Strictly bound to the exact OrderRequest fingerprint (symbol, side, qty, price, type, segment, product).
5. Never persisted to disk.
6. Zero raw token logging (sanitized/redacted).
7. Fail-closed: missing, expired, reused, or mismatched tokens are rejected.
"""

from datetime import datetime, timezone, timedelta
import hashlib
import json
import logging
import secrets
import threading
from typing import Any, Dict, Optional, Tuple

from backend.domain.broker_schemas import (
    ConfirmationRecord,
    OrderRequest,
    SafetyReasonCode,
)
from backend.domain.observability_schemas import EventCategory, EventSeverity
from backend.application.tamper_evident_audit_chain import global_audit_chain

logger = logging.getLogger(__name__)

DEFAULT_CONFIRMATION_TTL_SECONDS = 120  # 2 minutes


def compute_order_fingerprint(order: OrderRequest) -> str:
    """
    Compute a deterministic SHA-256 fingerprint over the immutable parameters of an OrderRequest.
    If any critical parameter changes, the fingerprint will mismatch.
    """
    canonical_data = {
        "symbol": order.symbol.strip().upper(),
        "exchange_segment": order.exchange_segment.value,
        "product_type": order.product_type.value,
        "side": order.side.value,
        "order_type": order.order_type.value,
        "quantity": int(order.quantity),
        "price": float(order.price) if order.price is not None else None,
        "trigger_price": float(order.trigger_price) if order.trigger_price is not None else None,
        "validity": order.validity.strip().upper(),
    }
    canonical_json = json.dumps(canonical_data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class ConfirmationStore:
    """
    In-memory, thread-safe, cryptographically secure confirmation store.
    """

    def __init__(self, default_ttl_seconds: int = DEFAULT_CONFIRMATION_TTL_SECONDS):
        self._lock = threading.RLock()
        self._default_ttl_seconds = default_ttl_seconds
        self._store: Dict[str, ConfirmationRecord] = {}

    def _mask_token(self, token: str) -> str:
        """Helper to create a non-reversible token identifier for safe logging."""
        if not token:
            return "***EMPTY***"
        prefix = token[:6] if len(token) >= 6 else "tok"
        return f"{prefix}...***REDACTED***"

    def create_confirmation(
        self,
        order_request: OrderRequest,
        dhan_payload: Optional[Dict[str, Any]] = None,
        estimated_order_value: float = 0.0,
        ttl_seconds: Optional[int] = None,
    ) -> ConfirmationRecord:
        """
        Generate a single-use cryptographically secure confirmation token bound to the OrderRequest.
        """
        with self._lock:
            ttl = ttl_seconds if ttl_seconds is not None and ttl_seconds > 0 else self._default_ttl_seconds
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(seconds=ttl)

            # Generate 256-bit cryptographically secure URL-safe token
            token = secrets.token_urlsafe(32)
            fingerprint = compute_order_fingerprint(order_request)

            record = ConfirmationRecord(
                confirmation_id=token,
                order_request=order_request,
                order_fingerprint=fingerprint,
                dhan_payload=dhan_payload or {},
                estimated_order_value=estimated_order_value,
                created_at=now,
                expires_at=expires_at,
                consumed=False,
                consumed_at=None,
            )

            self._store[token] = record

            # Log sanitized event to audit chain (token redacted)
            try:
                global_audit_chain.append_event(
                    event_type="ORDER_CONFIRMATION_CREATED",
                    category=EventCategory.SECURITY,
                    component="ConfirmationStore",
                    correlation_id=order_request.request_id,
                    symbol=order_request.symbol,
                    severity=EventSeverity.INFO,
                    reason="Confirmation token generated for manual order preview",
                    payload={
                        "token_ref": self._mask_token(token),
                        "request_id": order_request.request_id,
                        "symbol": order_request.symbol,
                        "side": order_request.side.value,
                        "quantity": order_request.quantity,
                        "expires_at": expires_at.isoformat(),
                        "estimated_value": estimated_order_value,
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to record audit event for confirmation creation: {e}")

            return record

    def get_confirmation(self, confirmation_token: str) -> Optional[ConfirmationRecord]:
        """
        Retrieve confirmation record by token without consuming it.
        """
        if not confirmation_token:
            return None
        with self._lock:
            return self._store.get(confirmation_token)

    def consume_confirmation(
        self,
        confirmation_token: str,
        order_request: OrderRequest,
    ) -> Tuple[bool, SafetyReasonCode, str, Optional[ConfirmationRecord]]:
        """
        Validate and consume a confirmation token in a single atomic operation.
        Returns:
            (is_valid, reason_code, reason_message, record)
        """
        if not confirmation_token:
            return (
                False,
                SafetyReasonCode.TOKEN_INVALID,
                "Confirmation token is missing or empty.",
                None,
            )

        with self._lock:
            record = self._store.get(confirmation_token)

            if not record:
                # Audit rejected token attempt
                self._record_audit_rejection(
                    confirmation_token,
                    order_request,
                    SafetyReasonCode.TOKEN_INVALID,
                    "Confirmation token not found in active store.",
                )
                return (
                    False,
                    SafetyReasonCode.TOKEN_INVALID,
                    "Confirmation token not found or already purged.",
                    None,
                )

            # Check if already consumed (reused token protection)
            if record.consumed:
                self._record_audit_rejection(
                    confirmation_token,
                    order_request,
                    SafetyReasonCode.TOKEN_REUSED,
                    "Confirmation token has already been consumed.",
                )
                return (
                    False,
                    SafetyReasonCode.TOKEN_REUSED,
                    "Confirmation token has already been used and cannot be reused.",
                    record,
                )

            now = datetime.now(timezone.utc)

            # Check if expired
            if now > record.expires_at:
                self._record_audit_rejection(
                    confirmation_token,
                    order_request,
                    SafetyReasonCode.TOKEN_EXPIRED,
                    f"Confirmation token expired at {record.expires_at.isoformat()}.",
                )
                return (
                    False,
                    SafetyReasonCode.TOKEN_EXPIRED,
                    f"Confirmation token expired. Token TTL was valid until {record.expires_at.isoformat()}.",
                    record,
                )

            # Check order binding / fingerprint match
            current_fingerprint = compute_order_fingerprint(order_request)
            if current_fingerprint != record.order_fingerprint:
                self._record_audit_rejection(
                    confirmation_token,
                    order_request,
                    SafetyReasonCode.ORDER_MISMATCH,
                    "Order parameters do not match the parameters authorized for this confirmation token.",
                )
                return (
                    False,
                    SafetyReasonCode.ORDER_MISMATCH,
                    "Order request parameters have changed since confirmation preview was generated.",
                    record,
                )

            # Atomic consumption
            record.consumed = True
            record.consumed_at = now

            # Record audit consumption
            try:
                global_audit_chain.append_event(
                    event_type="ORDER_CONFIRMATION_CONSUMED",
                    category=EventCategory.SECURITY,
                    component="ConfirmationStore",
                    correlation_id=order_request.request_id,
                    symbol=order_request.symbol,
                    severity=EventSeverity.INFO,
                    reason="Confirmation token successfully validated and consumed",
                    payload={
                        "token_ref": self._mask_token(confirmation_token),
                        "request_id": order_request.request_id,
                        "consumed_at": now.isoformat(),
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to record audit event for confirmation consumption: {e}")

            return (
                True,
                SafetyReasonCode.VALID,
                "Confirmation token successfully validated and consumed.",
                record,
            )

    def invalidate_confirmation(self, confirmation_token: str) -> bool:
        """
        Manually invalidate/revoke a confirmation token.
        """
        if not confirmation_token:
            return False
        with self._lock:
            if confirmation_token in self._store:
                del self._store[confirmation_token]
                return True
            return False

    def cleanup_expired(self) -> int:
        """
        Purge expired confirmation tokens from memory. Returns count purged.
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            expired_keys = [k for k, v in self._store.items() if now > v.expires_at]
            for k in expired_keys:
                del self._store[k]
            return len(expired_keys)

    def reset(self) -> None:
        """
        Reset in-memory confirmation store (for clean test isolation).
        """
        with self._lock:
            self._store.clear()
        try:
            from backend.execution.order_tracker import global_order_tracker
            global_order_tracker.clear()
        except Exception:
            pass
        try:
            from backend.execution.live_failure_recovery import global_live_failure_engine
            global_live_failure_engine.clear_reset()
        except Exception:
            pass

    def clear(self) -> None:
        """Alias for reset()."""
        self.reset()

    def _record_audit_rejection(
        self,
        token: str,
        order_request: OrderRequest,
        reason_code: SafetyReasonCode,
        details: str,
    ) -> None:
        try:
            global_audit_chain.append_event(
                event_type="ORDER_CONFIRMATION_REJECTED",
                category=EventCategory.SECURITY,
                component="ConfirmationStore",
                correlation_id=order_request.request_id,
                symbol=order_request.symbol,
                severity=EventSeverity.WARNING,
                reason=f"Confirmation rejected: {reason_code.value} - {details}",
                payload={
                    "token_ref": self._mask_token(token),
                    "reason_code": reason_code.value,
                    "details": details,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to record audit rejection event: {e}")


# Global singleton instance
global_confirmation_store = ConfirmationStore()
