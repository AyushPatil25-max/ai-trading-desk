"""
Phase 27 — Live Account Synchronization Service & In-Memory Cache

Synchronizes Dhan account balances, buying power, open positions, and holdings into
a thread-safe in-memory read cache.

Safety Invariants:
1. Purely read-only synchronization: NEVER places or modifies orders.
2. Cached state NEVER authorizes live trading by itself (arming + safety gate always required).
3. Zero credentials or secret tokens exposed in cache or emitted events.
4. Emits ACCOUNT_SYNC audit events with sanitized financial summaries.
"""

from datetime import datetime, timezone
import logging
import threading
import time
from typing import Any, Dict, List, Optional

from backend.domain.broker_schemas import (
    BrokerAccountState,
    BrokerPosition,
)
from backend.domain.observability_schemas import EventCategory, EventSeverity
from backend.application.tamper_evident_audit_chain import global_audit_chain
from backend.config.broker_config import get_account_sync_interval

logger = logging.getLogger(__name__)


class AccountSyncService:
    """
    Maintains an in-memory read-only cache of Dhan account balances and positions.
    """

    def __init__(self, interval_seconds: Optional[int] = None):
        self._lock = threading.RLock()
        self._interval_override = interval_seconds
        self._is_running = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_sync_time: Optional[datetime] = None
        self._total_syncs = 0
        self._cached_account: Optional[BrokerAccountState] = None
        self._cached_positions: Dict[str, BrokerPosition] = {}
        self._cached_holdings: List[Dict[str, Any]] = []
        self._last_error: Optional[str] = None

    @property
    def interval_seconds(self) -> int:
        if self._interval_override is not None:
            return self._interval_override
        return get_account_sync_interval()

    def run_once(self, adapter: Optional[Any] = None) -> Dict[str, Any]:
        """
        Execute a single synchronization cycle from Dhan broker into the local in-memory cache.
        """
        with self._lock:
            from backend.adapters.dhan_adapter import DhanBrokerAdapter
            active_adapter = adapter or DhanBrokerAdapter()

            now = datetime.now(timezone.utc)
            self._last_sync_time = now
            self._total_syncs += 1

            try:
                acct = active_adapter.get_account_state()
                positions = active_adapter.get_positions()
                holdings = active_adapter.get_holdings()

                self._cached_account = acct
                self._cached_positions = positions or {}
                self._cached_holdings = holdings or []
                self._last_error = None

                cash = acct.cash if acct else 0.0
                bp = acct.buying_power if acct else 0.0
                pos_count = len(self._cached_positions)

                sync_report = {
                    "success": True,
                    "timestamp": now.isoformat(),
                    "cash": cash,
                    "buying_power": bp,
                    "positions_count": pos_count,
                    "holdings_count": len(self._cached_holdings),
                }

                try:
                    global_audit_chain.append_event(
                        event_type="ACCOUNT_SYNC",
                        category=EventCategory.AUDIT,
                        component="AccountSyncService",
                        correlation_id=f"sync-{now.strftime('%Y%m%d%H%M%S')}",
                        severity=EventSeverity.INFO,
                        reason=f"Dhan account sync: cash={cash}, buying_power={bp}, open_positions={pos_count}",
                        payload=sync_report,
                    )
                except Exception:
                    pass

                return sync_report

            except Exception as e:
                err_msg = f"Account sync failed: {str(e)}"
                logger.error(err_msg)
                self._last_error = err_msg
                return {
                    "success": False,
                    "timestamp": now.isoformat(),
                    "error": err_msg,
                }

    def get_cached_account(self) -> Optional[BrokerAccountState]:
        """Retrieve thread-safe copy of cached account state."""
        with self._lock:
            return self._cached_account

    def get_cached_positions(self) -> Dict[str, BrokerPosition]:
        """Retrieve thread-safe copy of cached open positions."""
        with self._lock:
            return dict(self._cached_positions)

    def get_cached_holdings(self) -> List[Dict[str, Any]]:
        """Retrieve thread-safe copy of cached holdings."""
        with self._lock:
            return list(self._cached_holdings)

    def start_background(self) -> None:
        """Start background account sync worker."""
        with self._lock:
            if self._is_running:
                return
            self._is_running = True
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="AccountSyncWorker")
            self._thread.start()
            logger.info("Account sync background worker started.")

    def stop_background(self) -> None:
        """Stop background account sync worker."""
        with self._lock:
            if not self._is_running:
                return
            self._stop_event.set()
            self._is_running = False
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=2.0)
            self._thread = None
            logger.info("Account sync background worker stopped.")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception as e:
                logger.error(f"Error in account sync worker loop: {e}")
            self._stop_event.wait(timeout=self.interval_seconds)

    def start(self) -> None:
        """Alias for start_background()."""
        self.start_background()

    def stop(self) -> None:
        """Alias for stop_background()."""
        self.stop_background()

    def get_status(self) -> Dict[str, Any]:
        """Return operational status of account synchronization."""
        with self._lock:
            return {
                "is_running": self._is_running,
                "interval_seconds": self.interval_seconds,
                "total_syncs": self._total_syncs,
                "last_sync_time": self._last_sync_time.isoformat() if self._last_sync_time else None,
                "last_error": self._last_error,
                "cached_positions_count": len(self._cached_positions),
                "cached_holdings_count": len(self._cached_holdings),
            }

    def status(self) -> Dict[str, Any]:
        """Alias for get_status()."""
        return self.get_status()


# Global singleton instance
global_account_sync_service = AccountSyncService()
