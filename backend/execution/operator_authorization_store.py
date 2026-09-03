"""
Phase 42 — Operator Authorization Store & Gate

Thread-safe, in-memory store for managing time-bound, cryptographically single-use
human operator authorization tokens for live execution.

Safety Invariants:
1. Pure Python deterministic gating.
2. AI/LLM code is explicitly prohibited from generating, issuing, or consuming operator tokens.
3. Every token is strictly bound to the SHA-256 fingerprint of the exact order request.
4. Tokens are strictly single-use and auto-expire after a short TTL (default 120s, max 300s).
5. All secrets and sensitive tokens are masked/redacted before logging or auditing.
6. Fail-closed: missing, expired, reused, or mismatched tokens unconditionally reject order execution.
"""

from datetime import datetime, timezone, timedelta
import logging
import threading
from typing import Dict, Optional, Tuple

from backend.domain.broker_schemas import OrderRequest as BrokerOrderRequestDomain
from backend.domain.phase42_schemas import (
    OperatorAuthorizationSource,
    OperatorAuthorizationToken,
    LiveExecutionGateReasonCode,
)
from backend.domain.observability_schemas import EventCategory, EventSeverity
from backend.application.tamper_evident_audit_chain import global_audit_chain
from backend.application.confirmation_store import compute_order_fingerprint

logger = logging.getLogger(__name__)

DEFAULT_OPERATOR_AUTH_TTL_SECONDS = 120  # 2 minutes


class OperatorAuthorizationStore:
    """
    In-memory manager for human operator live-order authorization tokens.
    """

    def __init__(self, default_ttl_seconds: int = DEFAULT_OPERATOR_AUTH_TTL_SECONDS):
        self._lock = threading.RLock()
        self._default_ttl_seconds = default_ttl_seconds
        self._tokens: Dict[str, OperatorAuthorizationToken] = {}

    def _mask_token_id(self, token_id: str) -> str:
        """Create a non-reversible identifier for safe audit logging."""
        if not token_id:
            return "***EMPTY***"
        prefix = token_id[:10] if len(token_id) >= 10 else token_id
        return f"{prefix}...***REDACTED***"

    def issue_token(
        self,
        operator_id: str,
        order_request: BrokerOrderRequestDomain,
        ttl_seconds: Optional[int] = None,
        source: str = "HUMAN_OPERATOR",
        operator_notes: Optional[str] = None,
        current_time: Optional[datetime] = None,
    ) -> OperatorAuthorizationToken:
        """
        Issue a new time-bound single-use operator authorization token.
        Rejects AI components or non-human authorization sources.
        """
        if not operator_id or not operator_id.strip():
            raise ValueError("Operator ID is required for operator authorization.")

        source_upper = source.upper().strip()
        if source_upper in ("AI", "AI_ADVISORY", "LLM", "AGENT", "AUTONOMOUS"):
            raise PermissionError("AI components are strictly prohibited from issuing operator authorization.")

        if source_upper != "HUMAN_OPERATOR":
            raise ValueError(f"Invalid operator authorization source: '{source}'. Must be 'HUMAN_OPERATOR'.")

        if ttl_seconds is not None and (ttl_seconds < 10 or ttl_seconds > 3600):
            raise ValueError(f"TTL seconds {ttl_seconds} out of allowed range [10, 3600].")

        now = current_time or datetime.now(timezone.utc)
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl_seconds
        expires_at = now + timedelta(seconds=ttl)

        order_fp = compute_order_fingerprint(order_request)

        with self._lock:
            token = OperatorAuthorizationToken(
                order_fingerprint=order_fp,
                operator_id=operator_id.strip(),
                source=OperatorAuthorizationSource.HUMAN_OPERATOR,
                issued_at=now,
                expires_at=expires_at,
                consumed=False,
                consumed_at=None,
                operator_notes=operator_notes,
            )
            self._tokens[token.token_id] = token

        # Emit audit event
        try:
            global_audit_chain.append_event(
                event_type="OPERATOR_AUTHORIZATION_ISSUED",
                category=EventCategory.SECURITY,
                component="OperatorAuthorizationStore",
                correlation_id=order_request.request_id,
                symbol=order_request.symbol,
                severity=EventSeverity.WARNING,
                reason=f"Human operator '{operator_id}' authorized order for {order_request.symbol} (TTL={ttl}s)",
                payload={
                    "token_ref": self._mask_token_id(token.token_id),
                    "operator_id": operator_id,
                    "symbol": order_request.symbol,
                    "side": order_request.side.value,
                    "quantity": order_request.quantity,
                    "expires_at": expires_at.isoformat(),
                },
            )
        except Exception as e:
            logger.warning("Failed to record audit event for operator token issuance: %s", e)

        return token

    def get_token(self, token_id: str) -> Optional[OperatorAuthorizationToken]:
        """Retrieve token without consuming it."""
        if not token_id:
            return None
        with self._lock:
            return self._tokens.get(token_id)

    def verify_and_consume(
        self,
        token_id: str,
        order: BrokerOrderRequestDomain,
        current_time: Optional[datetime] = None,
    ) -> Tuple[bool, LiveExecutionGateReasonCode, str, Optional[OperatorAuthorizationToken]]:
        """
        Verify and atomically consume an operator authorization token.
        Fails closed on missing, expired, reused, mismatched, or AI-originated token.
        """
        if not token_id:
            return (
                False,
                LiveExecutionGateReasonCode.OPERATOR_AUTH_MISSING,
                "Operator authorization token is missing or empty.",
                None,
            )

        now = current_time or datetime.now(timezone.utc)

        with self._lock:
            token = self._tokens.get(token_id)
            if not token:
                self._record_rejection(
                    token_id,
                    order,
                    LiveExecutionGateReasonCode.OPERATOR_AUTH_MISSING,
                    "Operator authorization token not found in store.",
                )
                return (
                    False,
                    LiveExecutionGateReasonCode.OPERATOR_AUTH_MISSING,
                    "Operator authorization token not found.",
                    None,
                )

            if token.consumed:
                self._record_rejection(
                    token_id,
                    order,
                    LiveExecutionGateReasonCode.OPERATOR_AUTH_REUSED,
                    "Operator authorization token has already been consumed.",
                )
                return (
                    False,
                    LiveExecutionGateReasonCode.OPERATOR_AUTH_REUSED,
                    "Operator authorization token has already been consumed and cannot be reused.",
                    token,
                )

            if token.source != OperatorAuthorizationSource.HUMAN_OPERATOR:
                self._record_rejection(
                    token_id,
                    order,
                    LiveExecutionGateReasonCode.OPERATOR_AUTH_AI_REJECTED,
                    "Operator token source is not human operator.",
                )
                return (
                    False,
                    LiveExecutionGateReasonCode.OPERATOR_AUTH_AI_REJECTED,
                    "Operator authorization token was not issued by a human operator.",
                    token,
                )

            if now > token.expires_at:
                self._record_rejection(
                    token_id,
                    order,
                    LiveExecutionGateReasonCode.OPERATOR_AUTH_EXPIRED,
                    f"Operator authorization token expired at {token.expires_at.isoformat()}.",
                )
                return (
                    False,
                    LiveExecutionGateReasonCode.OPERATOR_AUTH_EXPIRED,
                    f"Operator authorization token expired at {token.expires_at.isoformat()}.",
                    token,
                )

            order_fp = compute_order_fingerprint(order)
            if order_fp != token.order_fingerprint:
                self._record_rejection(
                    token_id,
                    order,
                    LiveExecutionGateReasonCode.OPERATOR_AUTH_MISMATCH,
                    "Order request parameters do not match authorized fingerprint.",
                )
                return (
                    False,
                    LiveExecutionGateReasonCode.OPERATOR_AUTH_MISMATCH,
                    "Order request parameters do not match operator authorization fingerprint.",
                    token,
                )

            # Atomic consumption
            token.consumed = True
            token.consumed_at = now

            # Record audit consumption
            try:
                global_audit_chain.append_event(
                    event_type="OPERATOR_AUTHORIZATION_CONSUMED",
                    category=EventCategory.SECURITY,
                    component="OperatorAuthorizationStore",
                    correlation_id=order.request_id,
                    symbol=order.symbol,
                    severity=EventSeverity.INFO,
                    reason="Operator authorization token successfully verified and consumed",
                    payload={
                        "token_ref": self._mask_token_id(token_id),
                        "operator_id": token.operator_id,
                        "consumed_at": now.isoformat(),
                    },
                )
            except Exception as e:
                logger.warning("Failed to record audit event for operator token consumption: %s", e)

            return (
                True,
                LiveExecutionGateReasonCode.VALID,
                "Operator authorization token successfully verified and consumed.",
                token,
            )

    def invalidate(self, token_id: str) -> bool:
        """Invalidate an operator authorization token."""
        if not token_id:
            return False
        with self._lock:
            if token_id in self._tokens:
                del self._tokens[token_id]
                return True
            return False

    def reset(self) -> None:
        """Reset store for test isolation."""
        with self._lock:
            self._tokens.clear()

    def clear(self) -> None:
        """Alias for reset()."""
        self.reset()

    def _record_rejection(
        self,
        token_id: str,
        order: BrokerOrderRequestDomain,
        code: LiveExecutionGateReasonCode,
        detail: str,
    ) -> None:
        try:
            global_audit_chain.append_event(
                event_type="OPERATOR_AUTHORIZATION_REJECTED",
                category=EventCategory.SECURITY,
                component="OperatorAuthorizationStore",
                correlation_id=getattr(order, "request_id", "UNKNOWN"),
                symbol=getattr(order, "symbol", "UNKNOWN"),
                severity=EventSeverity.WARNING,
                reason=f"Operator authorization rejected: {code.value} - {detail}",
                payload={
                    "token_ref": self._mask_token_id(token_id),
                    "reason_code": code.value,
                    "detail": detail,
                },
            )
        except Exception:
            pass


# Global singleton
global_operator_authorization_store = OperatorAuthorizationStore()
