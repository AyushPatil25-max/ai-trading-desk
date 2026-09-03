"""
Phase 27 — In-Memory Order Tracker & Duplicate Prevention

Thread-safe order tracking store that binds order fingerprints to broker order IDs,
preventing duplicate live submissions and tracking order lifecycle states.

Safety Invariants:
1. Prevents duplicate live order submissions via SHA-256 order parameter fingerprints.
2. Thread-safe operations using re-entrant locks.
3. Zero credentials or secret tokens stored in tracking records.
4. Fail-closed: Duplicate orders are rejected before reaching any broker adapter call.
5. Emits ORDER_DUPLICATE_DETECTED audit events on collision.
"""

from datetime import datetime, timezone
import logging
import threading
from typing import Any, Dict, List, Optional

from backend.domain.broker_schemas import OrderRequest
from backend.domain.observability_schemas import EventCategory, EventSeverity
from backend.application.tamper_evident_audit_chain import global_audit_chain
from backend.application.confirmation_store import compute_order_fingerprint

logger = logging.getLogger(__name__)


class InMemoryOrderTracker:
    """
    Thread-safe in-memory order tracker for live broker execution.
    Maintains fingerprint -> order_id and lifecycle status mappings.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._tracked_orders: Dict[str, Dict[str, Any]] = {}
        self._order_id_to_fingerprint: Dict[str, str] = {}

    def is_duplicate(self, fingerprint_or_order: Any) -> bool:
        """
        Check if an active, pending, or submitted order already exists for this fingerprint.
        If a duplicate is found, emits an ORDER_DUPLICATE_DETECTED audit event.
        """
        if isinstance(fingerprint_or_order, OrderRequest):
            fingerprint = compute_order_fingerprint(fingerprint_or_order)
            symbol = fingerprint_or_order.symbol
            req_id = fingerprint_or_order.request_id
        else:
            fingerprint = str(fingerprint_or_order)
            symbol = "UNKNOWN"
            req_id = "UNKNOWN"

        with self._lock:
            record = self._tracked_orders.get(fingerprint)
            if record is not None:
                # Active if status is SUBMITTED, PENDING, PENDING_SUBMISSION, ACCEPTED, or FILLED (unless purged by reconciliation)
                status = record.get("status", "SUBMITTED")
                if status in ("SUBMITTED", "PENDING", "PENDING_SUBMISSION", "ACCEPTED", "OPEN", "PARTIALLY_FILLED", "FILLED", "RECOVERY_REQUIRES_RECONCILIATION"):
                    try:
                        global_audit_chain.append_event(
                            event_type="ORDER_DUPLICATE_DETECTED",
                            category=EventCategory.SECURITY,
                            component="OrderTracker",
                            correlation_id=req_id if req_id != "UNKNOWN" else record.get("request_id", "UNKNOWN"),
                            symbol=symbol if symbol != "UNKNOWN" else record.get("symbol", "UNKNOWN"),
                            severity=EventSeverity.WARNING,
                            reason=f"Duplicate order detected with fingerprint {fingerprint[:12]}... (current status: {status})",
                            payload={
                                "fingerprint": fingerprint,
                                "existing_order_id": record.get("broker_order_id"),
                                "existing_request_id": record.get("request_id"),
                                "status": status,
                            },
                        )
                    except Exception:
                        pass
                    return True
            return False

    def record_submission(
        self,
        fingerprint: str,
        request_id: str,
        order: Optional[OrderRequest] = None,
        status: str = "PENDING_SUBMISSION",
    ) -> None:
        """Record an in-flight submission attempt before or during broker API call."""
        with self._lock:
            now = datetime.now(timezone.utc)
            self._tracked_orders[fingerprint] = {
                "fingerprint": fingerprint,
                "request_id": request_id,
                "broker_order_id": None,
                "symbol": order.symbol if order else "UNKNOWN",
                "side": order.side.value if order else "UNKNOWN",
                "quantity": float(order.quantity) if order else 0.0,
                "order_type": order.order_type.value if order else "UNKNOWN",
                "status": status,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "details": {},
            }
            self._persist_state("ORDER_RECORD_SUBMISSION", fingerprint)

    def record_success(
        self,
        fingerprint: str,
        order_id: str,
        details: Optional[Dict[str, Any]] = None,
        status: str = "SUBMITTED",
    ) -> None:
        """Record a confirmed broker order ID following successful broker acceptance."""
        with self._lock:
            now = datetime.now(timezone.utc)
            if fingerprint in self._tracked_orders:
                self._tracked_orders[fingerprint]["broker_order_id"] = order_id
                self._tracked_orders[fingerprint]["status"] = status
                self._tracked_orders[fingerprint]["updated_at"] = now.isoformat()
                if details:
                    self._tracked_orders[fingerprint]["details"].update(details)
            else:
                self._tracked_orders[fingerprint] = {
                    "fingerprint": fingerprint,
                    "request_id": details.get("request_id", "UNKNOWN") if details else "UNKNOWN",
                    "broker_order_id": order_id,
                    "symbol": details.get("symbol", "UNKNOWN") if details else "UNKNOWN",
                    "side": details.get("side", "UNKNOWN") if details else "UNKNOWN",
                    "quantity": float(details.get("quantity", 0.0)) if details else 0.0,
                    "order_type": details.get("order_type", "UNKNOWN") if details else "UNKNOWN",
                    "status": status,
                    "created_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                    "details": details or {},
                }
            self._order_id_to_fingerprint[order_id] = fingerprint
            self._persist_state("ORDER_RECORD_SUCCESS", fingerprint)

    def update_status(
        self,
        fingerprint: str,
        status: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Update lifecycle status of a tracked order."""
        with self._lock:
            if fingerprint not in self._tracked_orders:
                return False
            now = datetime.now(timezone.utc)
            self._tracked_orders[fingerprint]["status"] = status
            self._tracked_orders[fingerprint]["updated_at"] = now.isoformat()
            if details:
                self._tracked_orders[fingerprint].setdefault("details", {}).update(details)
            self._persist_state("ORDER_UPDATE_STATUS", fingerprint)
            return True

    def lookup(self, fingerprint: str) -> Optional[Dict[str, Any]]:
        """Retrieve tracking record by fingerprint."""
        with self._lock:
            record = self._tracked_orders.get(fingerprint)
            return dict(record) if record else None

    def lookup_by_order_id(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve tracking record by broker order ID."""
        with self._lock:
            fp = self._order_id_to_fingerprint.get(order_id)
            if fp and fp in self._tracked_orders:
                return dict(self._tracked_orders[fp])
            return None

    def remove(self, fingerprint: str) -> bool:
        """Remove an order from active tracking (e.g. after completed reconciliation)."""
        with self._lock:
            if fingerprint in self._tracked_orders:
                record = self._tracked_orders.pop(fingerprint)
                order_id = record.get("broker_order_id")
                if order_id and order_id in self._order_id_to_fingerprint:
                    self._order_id_to_fingerprint.pop(order_id, None)
                self._persist_state("ORDER_REMOVE", fingerprint)
                return True
            return False

    def clear(self) -> None:
        """Clear all tracking state (e.g. on emergency kill switch activation)."""
        with self._lock:
            self._tracked_orders.clear()
            self._order_id_to_fingerprint.clear()
            self._persist_state("ORDER_CLEAR_ALL", "ALL")

    def get_all_tracked(self) -> List[Dict[str, Any]]:
        """Return a copy of all currently tracked orders."""
        with self._lock:
            return [dict(v) for v in self._tracked_orders.values()]

    def get_stats(self) -> Dict[str, Any]:
        """Return summary statistics of tracked orders."""
        with self._lock:
            statuses: Dict[str, int] = {}
            for rec in self._tracked_orders.values():
                st = rec.get("status", "UNKNOWN")
                statuses[st] = statuses.get(st, 0) + 1
            return {
                "total_tracked": len(self._tracked_orders),
                "by_status": statuses,
            }

    def _persist_state(self, mutation_type: str, key_suffix: str) -> None:
        """Persist tracker state to PersistentStateStore and StateJournal safely."""
        try:
            from backend.execution.persistent_state_store import global_persistent_state_store
            from backend.execution.state_journal import global_state_journal

            store_data = dict(self._tracked_orders)
            res = global_persistent_state_store.commit_mutation(
                mutation_type=mutation_type,
                mutations={"tracked_orders": store_data},
                idempotency_key=f"ot-{uuid.uuid4().hex[:8]}",
            )
            global_state_journal.append_entry(
                event_type=mutation_type,
                state_revision=res.get("new_revision", global_persistent_state_store.revision),
                payload={"tracked_orders_count": len(store_data), "key_suffix": key_suffix},
            )
        except Exception as e:
            logger.debug("Could not persist order tracker state: %s", e)


# Global singleton instance
global_order_tracker = InMemoryOrderTracker()
