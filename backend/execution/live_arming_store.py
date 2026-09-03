"""
Phase 26 — Live Trading Arming Store

Thread-safe, in-memory store for managing short-lived, explicit live-trading authorization.
Ensures live orders cannot be submitted unless an active, unexpired armed session exists.
"""

from datetime import datetime, timezone, timedelta
import threading
from typing import Optional, Tuple
import uuid

from backend.domain.live_readiness_schemas import LiveArmingStatus
from backend.domain.observability_schemas import EventCategory, EventSeverity
from backend.application.tamper_evident_audit_chain import global_audit_chain


class LiveArmingStore:
    """
    In-memory manager for temporary live-trading authorization.
    
    Invariants:
    1. Armed state is strictly temporary (default 5 min TTL, max 15 min TTL).
    2. Requires explicit user acknowledgement acknowledging financial risk.
    3. Auto-expires when TTL elapses.
    4. Immediately invalidated if kill switch activates or critical configuration changes.
    5. Disarm is always available.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._is_armed: bool = False
        self._armed_at: Optional[datetime] = None
        self._expires_at: Optional[datetime] = None
        self._session_id: Optional[str] = None
        self._armed_by: str = "OPERATOR"
        self._operator_notes: Optional[str] = None

    def arm(
        self,
        acknowledgement: bool,
        duration_seconds: int = 300,
        operator_notes: Optional[str] = None,
        armed_by: str = "OPERATOR",
    ) -> Tuple[bool, str, LiveArmingStatus]:
        """
        Arm live trading with explicit acknowledgement and bounded TTL.
        """
        if not acknowledgement:
            return False, "Explicit risk acknowledgement is mandatory to arm live trading.", self.get_status()

        clamped_duration = max(30, min(duration_seconds, 900))
        now = datetime.now(timezone.utc)

        with self._lock:
            self._is_armed = True
            self._armed_at = now
            self._expires_at = now + timedelta(seconds=clamped_duration)
            self._session_id = f"arm-{uuid.uuid4().hex[:12]}"
            self._armed_by = armed_by
            self._operator_notes = operator_notes

            status = self._build_status(now)

        # Record tamper-evident audit event
        try:
            global_audit_chain.append_event(
                event_type="LIVE_TRADING_ARMED",
                category=EventCategory.EXECUTION,
                component="LiveArmingStore",
                correlation_id=self._session_id or "live-arm",
                severity=EventSeverity.WARNING,
                reason=f"Live trading armed for {clamped_duration}s by {armed_by}",
                payload={
                    "session_id": self._session_id,
                    "duration_seconds": clamped_duration,
                    "expires_at": self._expires_at.isoformat() if self._expires_at else None,
                    "armed_by": armed_by,
                },
            )
        except Exception:
            pass

        return True, f"Live trading successfully armed for {clamped_duration} seconds.", status

    def disarm(self, reason: str = "Manual operator disarm") -> LiveArmingStatus:
        """
        Disarm live trading immediately.
        """
        with self._lock:
            prev_session = self._session_id
            self._is_armed = False
            self._armed_at = None
            self._expires_at = None
            self._session_id = None
            self._operator_notes = None

            status = self._build_status(datetime.now(timezone.utc), disarm_reason=reason)

        try:
            global_audit_chain.append_event(
                event_type="LIVE_TRADING_DISARMED",
                category=EventCategory.EXECUTION,
                component="LiveArmingStore",
                correlation_id=prev_session or "live-disarm",
                severity=EventSeverity.INFO,
                reason=f"Live trading disarmed: {reason}",
                payload={"reason": reason, "previous_session_id": prev_session},
            )
        except Exception:
            pass

        return status

    def get_status(self) -> LiveArmingStatus:
        """
        Return the current arming status, automatically expiring if TTL elapsed.
        """
        now = datetime.now(timezone.utc)
        with self._lock:
            if self._is_armed and self._expires_at and now >= self._expires_at:
                self._is_armed = False
                self._session_id = None

            return self._build_status(now)

    def is_currently_armed(self) -> bool:
        """
        Return True if live trading is actively armed and within TTL.
        """
        status = self.get_status()
        return status.is_armed

    def validate_active_arm(self) -> Tuple[bool, str]:
        """
        Evaluate if live trading is authorized for order submission.
        """
        status = self.get_status()
        if not status.is_armed:
            return False, "Live order blocked: Live trading is not currently armed or armed session has expired."
        return True, "Live trading authorization is active."

    def invalidate(self, reason: str = "Emergency invalidation"):
        """
        Force-disarm without exception.
        """
        self.disarm(reason=reason)

    def reset(self):
        """Reset store for testing."""
        with self._lock:
            self._is_armed = False
            self._armed_at = None
            self._expires_at = None
            self._session_id = None
            self._operator_notes = None
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

    def _build_status(self, now: datetime, disarm_reason: Optional[str] = None) -> LiveArmingStatus:
        remaining = 0
        is_active = False
        if self._is_armed and self._expires_at:
            if now < self._expires_at:
                remaining = int((self._expires_at - now).total_seconds())
                is_active = True
            else:
                self._is_armed = False

        return LiveArmingStatus(
            is_armed=is_active,
            armed_at=self._armed_at,
            expires_at=self._expires_at,
            remaining_seconds=remaining,
            armed_by=self._armed_by,
            session_id=self._session_id,
            reason=disarm_reason,
        )


# Global singleton
global_live_arming_store = LiveArmingStore()
