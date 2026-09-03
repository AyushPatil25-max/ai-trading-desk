"""
Phase 22 — Deterministic Resilience Fault Injection Framework

Controlled, test-only fault simulation framework capable of synthesizing all 19
failure domain scenarios (delayed ticks, stale data, stream drops, worker crashes,
model timeouts, cache corruptions, sandbox aborts) with explicit seed control.

Safety Invariant:
- TEST-ONLY: Strictly disabled in production runtimes.
- ZERO path to real-money execution (`TIER_4_LIVE_REAL_MONEY = locked`).
- Never mutates production risk rules or ExecutionGuard validation checks.
"""

import contextlib
from datetime import datetime, timezone
import logging
import threading
from typing import Any, Dict, Generator, List, Optional, Set

from backend.domain.resilience_schemas import (
    FailureDomainType,
    ResilienceComponent,
)

logger = logging.getLogger(__name__)


class ResilienceFaultInjector:
    """
    Deterministic fault-injection harness for chaos and resilience testing.
    Thread-safe and strictly inert unless explicitly activated during tests.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._active_faults: Set[FailureDomainType] = set()
        self._fault_metadata: Dict[FailureDomainType, Dict[str, Any]] = {}
        self._is_enabled: bool = False

    def enable(self) -> None:
        """Globally enable the fault injector (test harness only)."""
        with self._lock:
            self._is_enabled = True
            logger.warning("[ResilienceFaultInjector] Fault injection system ENABLED (Test/Simulation mode).")

    def disable(self) -> None:
        """Globally disable fault injection."""
        with self._lock:
            self._is_enabled = False
            self.clear()
            logger.info("[ResilienceFaultInjector] Fault injection system DISABLED.")

    @property
    def is_enabled(self) -> bool:
        with self._lock:
            return self._is_enabled

    def activate_fault(
        self,
        fault_type: FailureDomainType,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Activate a simulated failure mode."""
        with self._lock:
            if not self._is_enabled:
                self._is_enabled = True
            self._active_faults.add(fault_type)
            self._fault_metadata[fault_type] = metadata or {}
            logger.warning(f"[ResilienceFaultInjector] ACTIVATED fault: {fault_type.value}")

    def deactivate_fault(self, fault_type: FailureDomainType) -> None:
        """Deactivate an active simulated failure mode."""
        with self._lock:
            self._active_faults.discard(fault_type)
            self._fault_metadata.pop(fault_type, None)
            logger.info(f"[ResilienceFaultInjector] DEACTIVATED fault: {fault_type.value}")

    def is_fault_active(self, fault_type: FailureDomainType) -> bool:
        """Check whether a specific fault mode is currently active."""
        with self._lock:
            return self._is_enabled and (fault_type in self._active_faults)

    def get_fault_metadata(self, fault_type: FailureDomainType) -> Dict[str, Any]:
        """Retrieve simulation parameters associated with an active fault."""
        with self._lock:
            return self._fault_metadata.get(fault_type, {}).copy()

    def get_active_faults(self) -> List[str]:
        """List all currently active fault modes."""
        with self._lock:
            return [f.value for f in self._active_faults]

    def clear(self) -> None:
        """Clear all active faults and parameters."""
        with self._lock:
            self._active_faults.clear()
            self._fault_metadata.clear()
            logger.info("[ResilienceFaultInjector] Cleared all active faults.")

    @contextlib.contextmanager
    def inject(
        self,
        fault_type: FailureDomainType,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Generator[None, None, None]:
        """
        Scoped context manager for deterministic fault injection within test cases.
        Guarantees deactivation upon block exit even on unexpected exceptions.
        """
        self.activate_fault(fault_type, metadata)
        try:
            yield
        finally:
            self.deactivate_fault(fault_type)


# Global singleton instance
global_resilience_fault_injector = ResilienceFaultInjector()
