"""
Phase 28 — Deterministic Crash Recovery Engine for Trading OS Execution

Orchestrates startup crash recovery and state reconstruction:
1. Load persistent snapshot from PersistentStateStore
2. Verify snapshot integrity (checksum validation)
3. Load StateJournal and verify cryptographic integrity
4. Identify committed vs incomplete mutations
5. Replay only valid committed mutations (strictly idempotent)
6. Reconstruct latest valid state into execution subsystems:
   - Restores order tracker state
   - In-flight/ambiguous orders set to RECOVERY_REQUIRES_RECONCILIATION
   - Live arming strictly remains disarmed (NEVER survives restart)
   - Failure recovery retry loops purged (no blind automatic live retry)
7. Emits tamper-evident audit events and exposes recovery diagnostics

Safety Invariants:
- ZERO live-money authority restored on startup.
- Live arming NEVER survives process restart.
- Ambiguous orders MUST be reconciled with Dhan before any action.
- If recovery is corrupted or untrusted, fails closed to DEGRADED/BLOCKED state.
"""

from datetime import datetime, timezone
from enum import Enum
import logging
import threading
from typing import Any, Dict, List, Optional
import uuid

from backend.domain.observability_schemas import (
    EventCategory,
    EventSeverity,
    _sanitize_payload,
)
from backend.application.tamper_evident_audit_chain import global_audit_chain
from backend.execution.persistent_state_store import (
    PersistentStateStore,
    StateCorruptionError,
    global_persistent_state_store,
)
from backend.execution.state_journal import (
    JournalCorruptionError,
    StateJournal,
    global_state_journal,
)
from backend.execution.order_tracker import global_order_tracker
from backend.execution.live_arming_store import global_live_arming_store
from backend.execution.live_failure_recovery import global_live_failure_engine

logger = logging.getLogger(__name__)


class RecoveryState(str, Enum):
    """Operational state of crash recovery engine."""
    UNINITIALIZED = "UNINITIALIZED"
    RECOVERING = "RECOVERING"
    OPERATIONAL = "OPERATIONAL"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"


class CrashRecoveryEngine:
    """
    Deterministic crash recovery coordinator that reconstructs valid operational state
    from persistent snapshots and write-ahead state journals on startup.
    """

    def __init__(
        self,
        state_store: Optional[PersistentStateStore] = None,
        journal: Optional[StateJournal] = None,
    ):
        self._lock = threading.RLock()
        self.state_store = state_store or global_persistent_state_store
        self.journal = journal or global_state_journal
        self._state: RecoveryState = RecoveryState.UNINITIALIZED
        self._last_recovery_time: Optional[datetime] = None
        self._replayed_mutations_count: int = 0
        self._restored_orders_count: int = 0
        self._pending_reconciliation_count: int = 0
        self._corruption_detected: bool = False
        self._error_details: Optional[str] = None
        self._recovery_report: Dict[str, Any] = {}

    @property
    def operational_state(self) -> RecoveryState:
        with self._lock:
            return self._state

    def run_recovery(self) -> Dict[str, Any]:
        """
        Execute deterministic 7-step crash recovery sequence.
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            self._state = RecoveryState.RECOVERING
            correlation_id = f"rec-{uuid.uuid4().hex[:8]}"

            # 1. Emit Recovery Started Event
            self._emit_audit(
                event_type="STATE_RECOVERY_STARTED",
                category=EventCategory.SYSTEM,
                severity=EventSeverity.INFO,
                reason="Initiating deterministic crash recovery sequence",
                payload={"correlation_id": correlation_id},
            )

            # 2. Verify and Load Snapshot from PersistentStateStore
            try:
                snapshot = self.state_store.snapshot()
                store_health = self.state_store.get_status()
                if store_health.get("corruption_detected", False):
                    self._corruption_detected = True
                    logger.warning("Corruption detected in persistent store during recovery.")
            except Exception as e:
                err_msg = f"Failed to load persistent state snapshot: {e}"
                logger.error(err_msg)
                return self._fail_recovery(err_msg, correlation_id)

            # 3. Verify Journal Integrity
            is_journal_valid, verified_seq_count, journal_err = self.journal.verify_integrity()
            if not is_journal_valid:
                err_msg = f"Write-ahead state journal cryptographic integrity check failed: {journal_err}"
                logger.error(err_msg)
                self._corruption_detected = True
                return self._fail_recovery(err_msg, correlation_id)

            # 4. Identify and Replay Uncommitted Journal Mutations
            replayed_count = 0
            try:
                replayed_count, replayed_keys = self.journal.replay(state_store=self.state_store)
                self._replayed_mutations_count = replayed_count
            except Exception as e:
                err_msg = f"Failed during journal mutation replay: {e}"
                logger.error(err_msg)
                return self._fail_recovery(err_msg, correlation_id)

            # 5. Restore Order Tracker State
            restored_orders = 0
            reconciliation_required = 0
            try:
                orders_data = self.state_store.get("tracked_orders", {})
                if isinstance(orders_data, dict) and orders_data:
                    for fp, record in orders_data.items():
                        if isinstance(record, dict):
                            restored_orders += 1
                            order_status = record.get("status", "SUBMITTED")

                            # Any in-flight orders MUST require reconciliation
                            if order_status in ("PENDING_SUBMISSION", "SUBMITTED", "PENDING", "OPEN"):
                                record["status"] = "RECOVERY_REQUIRES_RECONCILIATION"
                                reconciliation_required += 1
                                self._emit_audit(
                                    event_type="ORDER_RECOVERY_REQUIRES_RECONCILIATION",
                                    category=EventCategory.SECURITY,
                                    severity=EventSeverity.WARNING,
                                    reason=f"Restored in-flight order {record.get('broker_order_id', fp[:8])} requires broker reconciliation",
                                    payload={
                                        "fingerprint": fp,
                                        "broker_order_id": record.get("broker_order_id"),
                                        "request_id": record.get("request_id"),
                                        "status": "RECOVERY_REQUIRES_RECONCILIATION",
                                    },
                                )

                            # Feed back into in-memory tracker
                            global_order_tracker._tracked_orders[fp] = record
                            broker_oid = record.get("broker_order_id")
                            if broker_oid:
                                global_order_tracker._order_id_to_fingerprint[broker_oid] = fp

                    if restored_orders > 0:
                        self._emit_audit(
                            event_type="ORDER_STATE_RESTORED",
                            category=EventCategory.SYSTEM,
                            severity=EventSeverity.INFO,
                            reason=f"Restored {restored_orders} tracked orders from persistent store",
                            payload={
                                "restored_orders_count": restored_orders,
                                "reconciliation_required_count": reconciliation_required,
                            },
                        )

                self._restored_orders_count = restored_orders
                self._pending_reconciliation_count = reconciliation_required
            except Exception as e:
                err_msg = f"Failed to restore order tracker state: {e}"
                logger.error(err_msg)
                return self._fail_recovery(err_msg, correlation_id)

            # 6. Safety Enforcements: Disarm Live Trading & Reset In-Flight Retries
            global_live_arming_store.disarm(reason="Process restart recovery - fail-closed disarm")
            global_live_failure_engine.reset()

            # 7. Complete Recovery
            self._last_recovery_time = datetime.now(timezone.utc)
            self._state = RecoveryState.OPERATIONAL if not self._corruption_detected else RecoveryState.DEGRADED
            self._error_details = None

            report = {
                "status": self._state.value,
                "is_recovered": True,
                "timestamp": self._last_recovery_time.isoformat(),
                "revision": self.state_store.revision,
                "journal_sequence": self.journal.latest_sequence,
                "replayed_mutations_count": self._replayed_mutations_count,
                "restored_orders_count": self._restored_orders_count,
                "pending_reconciliation_count": self._pending_reconciliation_count,
                "corruption_detected": self._corruption_detected,
                "live_armed": False,
            }
            self._recovery_report = report

            self._emit_audit(
                event_type="STATE_RECOVERY_COMPLETED",
                category=EventCategory.SYSTEM,
                severity=EventSeverity.INFO,
                reason=f"Recovery complete: operational state is {self._state.value}",
                payload=report,
            )

            return report

    def _fail_recovery(self, error_message: str, correlation_id: str) -> Dict[str, Any]:
        """Fail closed when recovery encounters unrecoverable corruption."""
        self._state = RecoveryState.BLOCKED
        self._error_details = error_message
        self._last_recovery_time = datetime.now(timezone.utc)

        report = {
            "status": RecoveryState.BLOCKED.value,
            "is_recovered": False,
            "timestamp": self._last_recovery_time.isoformat(),
            "error": error_message,
            "corruption_detected": True,
            "live_armed": False,
        }
        self._recovery_report = report

        self._emit_audit(
            event_type="STATE_RECOVERY_FAILED",
            category=EventCategory.FAILURE,
            severity=EventSeverity.CRITICAL,
            reason=f"Crash recovery failed: {error_message}",
            payload=report,
        )

        return report

    def get_status(self) -> Dict[str, Any]:
        """Return recovery status and diagnostics."""
        with self._lock:
            return {
                "state": self._state.value,
                "is_operational": self._state == RecoveryState.OPERATIONAL,
                "last_recovery_time": self._last_recovery_time.isoformat() if self._last_recovery_time else None,
                "replayed_mutations_count": self._replayed_mutations_count,
                "restored_orders_count": self._restored_orders_count,
                "pending_reconciliation_count": self._pending_reconciliation_count,
                "corruption_detected": self._corruption_detected,
                "error_details": self._error_details,
                "store_status": self.state_store.get_status(),
                "journal_status": self.journal.get_status(),
            }

    def status(self) -> Dict[str, Any]:
        return self.get_status()

    def _emit_audit(
        self,
        event_type: str,
        category: EventCategory,
        severity: EventSeverity,
        reason: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            global_audit_chain.append_event(
                event_type=event_type,
                category=category,
                component="CrashRecoveryEngine",
                correlation_id=f"rec-{uuid.uuid4().hex[:8]}",
                severity=severity,
                reason=reason,
                payload=_sanitize_payload(payload or {}),
            )
        except Exception:
            pass


# Global singleton instance
global_state_recovery_engine = CrashRecoveryEngine()
