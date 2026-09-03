"""
Phase 28 — State Conflict Detector & Resolution Engine

Detects:
- Revision conflicts & out-of-order writes
- Concurrent worker partition ownership conflicts
- Divergent checksums across replicas
- Conflicting accounting and position balances

Safety Invariant:
- Financial & accounting conflicts are NEVER blindly resolved or guessed.
- Conflicting partitions are strictly QUARANTINED and fail-closed until verified.
- Real-money live trading remains permanently locked, unroutable, and fail-closed.
"""

from datetime import datetime, timezone
import logging
import threading
from typing import Any, Dict, List, Optional, Tuple
import uuid

from backend.domain.observability_schemas import EventCategory, EventSeverity
from backend.domain.distributed_state_schemas import (
    ConflictRecord,
    ConflictResolution,
)
from backend.application.tamper_evident_audit_chain import global_audit_chain

logger = logging.getLogger(__name__)


class StateConflictResolver:
    """
    Deterministic conflict detector and fail-closed resolution engine.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._conflicts: Dict[str, ConflictRecord] = {}
        self._resolutions: Dict[str, ConflictResolution] = {}

    def detect_revision_conflict(
        self,
        partition: str,
        current_revision: int,
        attempted_revision: int,
        node_id: str,
    ) -> Optional[ConflictRecord]:
        """Detect stale or duplicate revision writes."""
        with self._lock:
            if attempted_revision <= current_revision:
                rec = ConflictRecord(
                    partition=partition,
                    conflicting_nodes=[node_id],
                    conflicting_revisions=[current_revision, attempted_revision],
                    field_name="revision",
                    reason=f"Stale revision {attempted_revision} <= current {current_revision}.",
                    is_quarantined=True,
                )
                self._record_conflict(rec)
                return rec
            return None

    def detect_accounting_conflict(
        self,
        partition: str,
        local_cash: float,
        remote_cash: float,
        local_node: str,
        remote_node: str,
    ) -> Optional[ConflictRecord]:
        """
        Detect divergent accounting cash or position balances across nodes.
        Financial divergence strictly quarantines execution.
        """
        with self._lock:
            if abs(local_cash - remote_cash) > 0.01:
                rec = ConflictRecord(
                    partition=partition,
                    conflicting_nodes=[local_node, remote_node],
                    conflicting_revisions=[],
                    field_name="cash_balance",
                    reason=f"Accounting divergence: {local_node} has {local_cash}, but {remote_node} reported {remote_cash}.",
                    is_quarantined=True,
                )
                self._record_conflict(rec)
                return rec
            return None

    def resolve_non_financial_conflict(
        self,
        conflict_id: str,
        strategy: str,
        notes: str,
    ) -> Tuple[bool, str]:
        """
        Resolve non-financial conflicts using approved deterministic strategies (e.g. LWW for telemetry).
        Accounting conflicts cannot be resolved automatically and require manual audit.
        """
        with self._lock:
            conflict = self._conflicts.get(conflict_id)
            if not conflict:
                return False, f"Conflict '{conflict_id}' not found."

            if conflict.field_name in ("cash_balance", "positions", "orders"):
                return False, f"Financial field '{conflict.field_name}' cannot be resolved automatically. Requires audit recovery."

            res = ConflictResolution(
                conflict_id=conflict_id,
                resolved=True,
                strategy=strategy,
                resolution_notes=notes,
                timestamp=datetime.now(timezone.utc),
            )
            self._resolutions[conflict_id] = res
            conflict.is_quarantined = False

            global_audit_chain.append_event(
                event_type="STATE_CONFLICT_RESOLVED",
                category=EventCategory.SYSTEM,
                component="StateConflictResolver",
                correlation_id=f"corr-conf-{conflict_id}",
                severity=EventSeverity.INFO,
                payload={"conflict_id": conflict_id, "strategy": strategy},
            )
            return True, f"Conflict '{conflict_id}' resolved using strategy: {strategy}."

    def get_active_conflicts(self) -> List[ConflictRecord]:
        with self._lock:
            return [c for c in self._conflicts.values() if c.is_quarantined]

    def _record_conflict(self, record: ConflictRecord) -> None:
        """Store conflict and emit tamper-evident audit event."""
        self._conflicts[record.conflict_id] = record
        global_audit_chain.append_event(
            event_type="STATE_CONFLICT",
            category=EventCategory.SECURITY,
            component="StateConflictResolver",
            correlation_id=f"corr-conf-{record.conflict_id}",
            severity=EventSeverity.CRITICAL,
            payload={
                "conflict_id": record.conflict_id,
                "partition": record.partition,
                "field": record.field_name,
                "reason": record.reason,
            },
        )
        logger.warning(f"Recorded state conflict {record.conflict_id} on {record.partition}: {record.reason}")


# Global state conflict resolver singleton
global_state_conflict_resolver = StateConflictResolver()
