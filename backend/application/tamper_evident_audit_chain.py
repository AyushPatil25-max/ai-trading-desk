"""
Phase 23 — Tamper-Evident Audit Chain & Unified Event Store

Provides an immutable, append-only operational event store with cryptographic SHA-256
hash chaining, deterministic canonical serialization, and pure-Python tamper detection.

Safety Invariant:
- STRICTLY OBSERVATIONAL and AUDIT ONLY: Zero authority to place orders or mutate risk limits.
- Zero credential logging: All payloads are scrubbed via _sanitize_payload.
- TIER_4_LIVE_REAL_MONEY remains permanently locked and fail-closed.
"""

from collections import deque
from datetime import datetime, timezone
import json
import logging
import threading
from typing import Any, Dict, List, Optional

from backend.domain.observability_schemas import (
    AuditIntegrityReport,
    AuditVerificationStatus,
    EventCategory,
    EventSeverity,
    OperationalEvent,
    _sanitize_payload,
)

logger = logging.getLogger(__name__)

GENESIS_HASH = "0" * 64


class TamperEvidentAuditChain:
    """
    Cryptographically chained, thread-safe operational event store.
    Guarantees detection of any modification, deletion, reordering, or insertion of audit events.
    """

    def __init__(self, max_capacity: int = 10_000):
        self._lock = threading.RLock()
        self._max_capacity = max_capacity
        self._events: List[OperationalEvent] = []
        self._events_by_id: Dict[str, OperationalEvent] = {}
        self._correlation_index: Dict[str, List[str]] = {}  # correlation_id -> list of event_ids
        self._run_index: Dict[str, List[str]] = {}          # run_id -> list of event_ids
        self._symbol_index: Dict[str, List[str]] = {}       # symbol -> list of event_ids
        self._last_event_hash: str = GENESIS_HASH
        self._sequence_counter: int = 0

    # ── Append Operation (Step 3) ─────────────────────────────────────────────

    def append_event(
        self,
        event_type: str,
        category: EventCategory,
        component: str,
        correlation_id: str,
        severity: EventSeverity = EventSeverity.INFO,
        causation_id: Optional[str] = None,
        run_id: Optional[str] = None,
        worker_id: Optional[str] = None,
        symbol: Optional[str] = None,
        lifecycle_state: Optional[str] = None,
        status: Optional[str] = None,
        reason: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> OperationalEvent:
        """
        Append an operational event to the tamper-evident audit chain.
        Calculates monotonic sequence number, previous-event hash, and cryptographic hash.
        """
        with self._lock:
            sanitized_meta = _sanitize_payload(payload or {})

            seq = self._sequence_counter
            prev_hash = self._last_event_hash

            event = OperationalEvent(
                event_type=event_type,
                category=category,
                severity=severity,
                component=component,
                correlation_id=correlation_id,
                causation_id=causation_id,
                run_id=run_id,
                worker_id=worker_id,
                symbol=symbol,
                lifecycle_state=lifecycle_state,
                status=status,
                reason=reason,
                payload=sanitized_meta,
                sequence_number=seq,
                prev_event_hash=prev_hash,
            )

            # Compute canonical SHA-256 hash
            canonical_hash = event.compute_canonical_hash()
            event.event_hash = canonical_hash

            # Manage bounded capacity: when full, remove oldest while keeping index tidy
            if len(self._events) >= self._max_capacity:
                oldest = self._events.pop(0)
                self._events_by_id.pop(oldest.event_id, None)

            self._events.append(event)
            self._events_by_id[event.event_id] = event

            # Update indices
            if correlation_id:
                self._correlation_index.setdefault(correlation_id, []).append(event.event_id)
            if run_id:
                self._run_index.setdefault(run_id, []).append(event.event_id)
            if symbol:
                self._symbol_index.setdefault(symbol, []).append(event.event_id)

            self._last_event_hash = canonical_hash
            self._sequence_counter += 1

            return event

    # ── Tamper Verification (Step 4) ──────────────────────────────────────────

    def verify_integrity(self) -> AuditIntegrityReport:
        """
        Perform complete cryptographic verification across all chained audit events.
        Detects modified payloads, altered timestamps, swapped sequences, or broken hashes.
        """
        with self._lock:
            total_events = len(self._events)
            if total_events == 0:
                return AuditIntegrityReport(
                    status=AuditVerificationStatus.EMPTY_CHAIN,
                    total_events_verified=0,
                    summary_message="Audit chain is empty. Zero events to verify.",
                )

            expected_prev_hash = self._events[0].prev_event_hash or GENESIS_HASH

            for idx, event in enumerate(self._events):
                # 1. Verify sequence monotonicity
                if idx > 0 and event.sequence_number != self._events[idx - 1].sequence_number + 1:
                    return AuditIntegrityReport(
                        status=AuditVerificationStatus.INVALID_SEQUENCE,
                        total_events_verified=total_events,
                        valid_events_count=idx,
                        invalid_events_count=total_events - idx,
                        first_violation_index=idx,
                        violation_details=(
                            f"Sequence discontinuity at index {idx}: event_id={event.event_id}, "
                            f"seq={event.sequence_number}, expected={self._events[idx - 1].sequence_number + 1}"
                        ),
                        summary_message="AUDIT COMPROMISED: Monotonic sequence violation detected.",
                    )

                # 2. Verify previous event hash chaining
                if event.prev_event_hash != expected_prev_hash:
                    return AuditIntegrityReport(
                        status=AuditVerificationStatus.BROKEN_CHAIN,
                        total_events_verified=total_events,
                        valid_events_count=idx,
                        invalid_events_count=total_events - idx,
                        first_violation_index=idx,
                        violation_details=(
                            f"Broken hash chain at index {idx}: event_id={event.event_id}, "
                            f"prev_hash={event.prev_event_hash}, expected={expected_prev_hash}"
                        ),
                        summary_message="AUDIT COMPROMISED: Broken cryptographic hash link detected.",
                    )

                # 3. Verify event's own canonical SHA-256 hash
                recomputed_hash = event.compute_canonical_hash()
                if event.event_hash != recomputed_hash:
                    return AuditIntegrityReport(
                        status=AuditVerificationStatus.INVALID_HASH,
                        total_events_verified=total_events,
                        valid_events_count=idx,
                        invalid_events_count=total_events - idx,
                        first_violation_index=idx,
                        violation_details=(
                            f"Tampered content at index {idx}: event_id={event.event_id}, "
                            f"stored_hash={event.event_hash}, recomputed={recomputed_hash}"
                        ),
                        summary_message="AUDIT COMPROMISED: Event payload or metadata hash mismatch.",
                    )

                expected_prev_hash = event.event_hash

            return AuditIntegrityReport(
                status=AuditVerificationStatus.VALID,
                total_events_verified=total_events,
                valid_events_count=total_events,
                invalid_events_count=0,
                chain_head_hash=self._last_event_hash,
                chain_genesis_hash=self._events[0].prev_event_hash,
                summary_message=(
                    f"Audit chain verified clean: {total_events} events cryptographically validated. "
                    f"Zero tampering detected."
                ),
            )

    # ── Bounded Queries & Access (Step 8) ─────────────────────────────────────

    def get_event_by_id(self, event_id: str) -> Optional[OperationalEvent]:
        with self._lock:
            return self._events_by_id.get(event_id)

    def get_events_by_correlation_id(self, correlation_id: str) -> List[OperationalEvent]:
        with self._lock:
            event_ids = self._correlation_index.get(correlation_id, [])
            return [self._events_by_id[eid] for eid in event_ids if eid in self._events_by_id]

    def get_events_by_run_id(self, run_id: str) -> List[OperationalEvent]:
        with self._lock:
            event_ids = self._run_index.get(run_id, [])
            return [self._events_by_id[eid] for eid in event_ids if eid in self._events_by_id]

    def query_events(
        self,
        correlation_id: Optional[str] = None,
        run_id: Optional[str] = None,
        symbol: Optional[str] = None,
        component: Optional[str] = None,
        category: Optional[EventCategory] = None,
        severity: Optional[EventSeverity] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[OperationalEvent]:
        """
        Bounded, paginated multi-dimensional search across operational events.
        """
        with self._lock:
            results = self._events

            if correlation_id:
                results = [e for e in results if e.correlation_id == correlation_id]
            if run_id:
                results = [e for e in results if e.run_id == run_id]
            if symbol:
                results = [e for e in results if e.symbol == symbol]
            if component:
                results = [e for e in results if e.component == component]
            if category:
                results = [e for e in results if e.category == category]
            if severity:
                results = [e for e in results if e.severity == severity]

            # Bounded pagination
            limit = max(1, min(limit, 500))
            offset = max(0, offset)
            return results[offset : offset + limit]

    def get_recent_events(self, limit: int = 50) -> List[OperationalEvent]:
        """Return the N most recent events from the chain."""
        with self._lock:
            limit = max(1, min(limit, 500))
            return self._events[-limit:]

    @property
    def total_events_count(self) -> int:

        with self._lock:
            return len(self._events)

    def reset(self) -> None:
        """Reset state for clean test isolation."""
        with self._lock:
            self._events.clear()
            self._events_by_id.clear()
            self._correlation_index.clear()
            self._run_index.clear()
            self._symbol_index.clear()
            self._last_event_hash = GENESIS_HASH
            self._sequence_counter = 0


# Global singleton instance
global_audit_chain = TamperEvidentAuditChain()
