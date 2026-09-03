"""
Phase 27 — Periodic Live Broker Reconciliation Service

Reconciles local in-memory order tracker state against authoritative Dhan broker order books.

Safety Invariants:
1. NEVER automatically submits replacement orders.
2. Only updates/resolves local order status against verified broker responses.
3. Fails closed on network/broker discrepancies without corrupting tracker state.
4. Emits RECONCILIATION_RUN audit events with summary statistics.
"""

from datetime import datetime, timezone
import logging
import threading
import time
from typing import Any, Dict, List, Optional

from backend.domain.broker_schemas import (
    NormalizedOrderStatus,
)
from backend.domain.observability_schemas import EventCategory, EventSeverity
from backend.application.tamper_evident_audit_chain import global_audit_chain
from backend.config.broker_config import get_reconciliation_interval
from backend.execution.order_tracker import global_order_tracker

logger = logging.getLogger(__name__)


class ReconciliationService:
    """
    Periodically synchronizes local in-memory order tracking with the Dhan broker order book.
    """

    def __init__(self, interval_seconds: Optional[int] = None):
        self._lock = threading.RLock()
        self._interval_override = interval_seconds
        self._is_running = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_run_time: Optional[datetime] = None
        self._last_report: Optional[Dict[str, Any]] = None
        self._total_runs = 0

    @property
    def interval_seconds(self) -> int:
        if self._interval_override is not None:
            return self._interval_override
        return get_reconciliation_interval()

    def run_once(self, adapter: Optional[Any] = None) -> Dict[str, Any]:
        """
        Execute a single reconciliation cycle against the active Dhan adapter.
        """
        with self._lock:
            from backend.adapters.dhan_adapter import DhanBrokerAdapter
            active_adapter = adapter or DhanBrokerAdapter()

            now = datetime.now(timezone.utc)
            self._last_run_time = now
            self._total_runs += 1

            # Fetch authoritative order book
            try:
                broker_orders = active_adapter.get_order_book()
            except Exception as e:
                err_msg = f"Failed to retrieve broker order book during reconciliation: {str(e)}"
                logger.error(err_msg)
                report = {
                    "success": False,
                    "error": err_msg,
                    "timestamp": now.isoformat(),
                    "matched_count": 0,
                    "resolved_count": 0,
                    "tracked_count": len(global_order_tracker.get_all_tracked()),
                }
                self._last_report = report
                return report

            # Build broker order lookup by orderId and correlationId
            broker_by_order_id: Dict[str, Dict[str, Any]] = {}
            broker_by_corr_id: Dict[str, Dict[str, Any]] = {}

            if isinstance(broker_orders, list):
                for bo in broker_orders:
                    if isinstance(bo, dict):
                        oid = str(bo.get("orderId", ""))
                        cid = str(bo.get("correlationId", ""))
                        if oid:
                            broker_by_order_id[oid] = bo
                        if cid:
                            broker_by_corr_id[cid] = bo

            tracked = global_order_tracker.get_all_tracked()
            matched_count = 0
            resolved_count = 0
            open_count = 0

            for rec in tracked:
                fp = rec.get("fingerprint")
                b_oid = rec.get("broker_order_id")
                req_id = rec.get("request_id")

                found_order = None
                if b_oid and b_oid in broker_by_order_id:
                    found_order = broker_by_order_id[b_oid]
                elif req_id and req_id in broker_by_corr_id:
                    found_order = broker_by_corr_id[req_id]

                if found_order:
                    matched_count += 1
                    raw_status = str(found_order.get("orderStatus", "")).upper()
                    
                    # Normalize status
                    if raw_status in ("TRADED", "FILLED"):
                        norm_st = NormalizedOrderStatus.FILLED.value
                        resolved_count += 1
                    elif raw_status in ("REJECTED", "CANCELLED", "CANCELED", "EXPIRED"):
                        norm_st = NormalizedOrderStatus.REJECTED.value if raw_status == "REJECTED" else NormalizedOrderStatus.CANCELLED.value
                        resolved_count += 1
                    elif raw_status in ("PARTIALLY_FILLED", "PART_TRADED"):
                        norm_st = NormalizedOrderStatus.PARTIALLY_FILLED.value
                        open_count += 1
                    else:
                        norm_st = NormalizedOrderStatus.OPEN.value
                        open_count += 1

                    global_order_tracker.update_status(
                        fp,
                        norm_st,
                        details={
                            "reconciled_at": now.isoformat(),
                            "dhan_status": raw_status,
                            "filled_qty": found_order.get("filledQty", 0),
                        },
                    )
                else:
                    open_count += 1

            report = {
                "success": True,
                "timestamp": now.isoformat(),
                "tracked_orders_count": len(tracked),
                "broker_orders_count": len(broker_orders) if isinstance(broker_orders, list) else 0,
                "matched_count": matched_count,
                "resolved_count": resolved_count,
                "open_count": open_count,
            }
            self._last_report = report

            try:
                global_audit_chain.append_event(
                    event_type="RECONCILIATION_RUN",
                    category=EventCategory.AUDIT,
                    component="ReconciliationService",
                    correlation_id=f"reconcile-{now.strftime('%Y%m%d%H%M%S')}",
                    severity=EventSeverity.INFO,
                    reason=f"Broker reconciliation completed: {matched_count} matched, {resolved_count} resolved.",
                    payload=report,
                )
            except Exception:
                pass

            return report

    def start_background(self) -> None:
        """Start background reconciliation worker thread."""
        with self._lock:
            if self._is_running:
                return
            self._is_running = True
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="ReconciliationWorker")
            self._thread.start()
            logger.info("Reconciliation background worker started.")

    def stop_background(self) -> None:
        """Stop background reconciliation worker thread."""
        with self._lock:
            if not self._is_running:
                return
            self._stop_event.set()
            self._is_running = False
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=2.0)
            self._thread = None
            logger.info("Reconciliation background worker stopped.")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception as e:
                logger.error(f"Error in reconciliation worker loop: {e}")
            self._stop_event.wait(timeout=self.interval_seconds)

    def start(self) -> None:
        """Alias for start_background()."""
        self.start_background()

    def stop(self) -> None:
        """Alias for stop_background()."""
        self.stop_background()

    def get_status(self) -> Dict[str, Any]:
        """Return operational health of the reconciliation service."""
        with self._lock:
            return {
                "is_running": self._is_running,
                "interval_seconds": self.interval_seconds,
                "total_runs": self._total_runs,
                "last_run_time": self._last_run_time.isoformat() if self._last_run_time else None,
                "last_report": self._last_report,
            }

    def status(self) -> Dict[str, Any]:
        """Alias for get_status()."""
        return self.get_status()


# Global singleton instance
global_reconciliation_service = ReconciliationService()
