"""
Phase 28 — Distributed Coordinator & Split-Brain Protection Engine

Manages:
- Symbol partition ownership and worker leases with TTL
- Safe lease acquisition, renewal, and expiration
- Duplicate worker prevention (no two workers own the same symbol)
- Split-brain detection: immediate quarantine and fail-closed state on uncertainty
- Phase 23 Observability integration (OperationalEvent emission to global_audit_chain)

Safety Invariant:
- Real-money live trading remains permanently locked, unroutable, and fail-closed.
- Operates strictly in PAPER, SHADOW, and RESEARCH modes.
"""

from datetime import datetime, timezone, timedelta
import logging
import threading
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from backend.domain.observability_schemas import EventCategory, EventSeverity
from backend.domain.distributed_state_schemas import (
    CoordinationState,
    LeaderStatus,
    LeaseStatus,
    WorkerLease,
)
from backend.application.tamper_evident_audit_chain import global_audit_chain

logger = logging.getLogger(__name__)


class DistributedCoordinator:
    """
    Cluster coordinator managing worker partition leases and enforcing split-brain protection.
    """

    def __init__(self, node_id: str = "node-local", default_lease_ttl: float = 10.0):
        self._lock = threading.RLock()
        self.node_id = node_id
        self.default_lease_ttl = default_lease_ttl
        self.leader_status: LeaderStatus = LeaderStatus.LEADER
        self.coordination_state: CoordinationState = CoordinationState.NOMINAL

        self._leases_by_partition: Dict[str, WorkerLease] = {}
        self._leases_by_id: Dict[str, WorkerLease] = {}
        self._quarantined_partitions: Set[str] = set()

    def acquire_lease(
        self,
        partition: str,
        owner_node_id: str,
        owner_worker_id: str,
        ttl_seconds: Optional[float] = None,
    ) -> Tuple[bool, Optional[WorkerLease], str]:
        """
        Acquire an exclusive processing lease over a partition.
        Fails if partition is quarantined or already leased to another active worker.
        """
        with self._lock:
            partition = partition.upper()
            now = datetime.now(timezone.utc)
            ttl = ttl_seconds or self.default_lease_ttl

            # 1. Check quarantine
            if partition in self._quarantined_partitions:
                return False, None, f"Partition '{partition}' is QUARANTINED due to split-brain suspicion. Fails closed."

            # 2. Check existing lease
            existing = self._leases_by_partition.get(partition)
            if existing and not existing.is_expired(now) and existing.status == LeaseStatus.ACTIVE:
                if existing.owner_node_id == owner_node_id and existing.owner_worker_id == owner_worker_id:
                    # Idempotent renewal
                    return self.renew_lease(existing.lease_id)
                # Split-brain conflict: another active worker already owns this partition!
                self._handle_split_brain(partition, existing, owner_node_id, owner_worker_id)
                return False, None, f"Split-brain conflict: partition '{partition}' already leased to {existing.owner_worker_id}."

            # 3. Grant lease
            expires_at = now + timedelta(seconds=ttl)
            lease = WorkerLease(
                partition=partition,
                owner_node_id=owner_node_id,
                owner_worker_id=owner_worker_id,
                acquired_at=now,
                expires_at=expires_at,
                ttl_seconds=ttl,
                status=LeaseStatus.ACTIVE,
            )
            self._leases_by_partition[partition] = lease
            self._leases_by_id[lease.lease_id] = lease

            global_audit_chain.append_event(
                event_type="LEASE_ACQUIRED",
                category=EventCategory.WORKER,
                component="DistributedCoordinator",
                correlation_id=f"corr-lease-{lease.lease_id}",
                severity=EventSeverity.INFO,
                payload={
                    "lease_id": lease.lease_id,
                    "partition": partition,
                    "owner": owner_worker_id,
                    "ttl": ttl,
                },
            )
            return True, lease, "Lease acquired successfully."

    def renew_lease(self, lease_id: str, extend_seconds: Optional[float] = None) -> Tuple[bool, Optional[WorkerLease], str]:
        """Renew an existing active lease before TTL expiration."""
        with self._lock:
            lease = self._leases_by_id.get(lease_id)
            if not lease:
                return False, None, f"Lease '{lease_id}' not found."

            if lease.partition in self._quarantined_partitions:
                return False, None, f"Partition '{lease.partition}' is quarantined. Renewal rejected."

            now = datetime.now(timezone.utc)
            ttl = extend_seconds or lease.ttl_seconds
            lease.expires_at = now + timedelta(seconds=ttl)
            lease.renew_count += 1
            lease.status = LeaseStatus.ACTIVE

            global_audit_chain.append_event(
                event_type="LEASE_RENEWED",
                category=EventCategory.WORKER,
                component="DistributedCoordinator",
                correlation_id=f"corr-lease-{lease_id}",
                severity=EventSeverity.INFO,
                payload={"lease_id": lease_id, "partition": lease.partition, "renews": lease.renew_count},
            )
            return True, lease, "Lease renewed successfully."

    def release_lease(self, partition: str) -> Tuple[bool, str]:
        """Release lease gracefully upon worker shutdown."""
        with self._lock:
            partition = partition.upper()
            lease = self._leases_by_partition.pop(partition, None)
            if lease:
                lease.status = LeaseStatus.REVOKED
                self._leases_by_id.pop(lease.lease_id, None)
                global_audit_chain.append_event(
                    event_type="LEASE_RELEASED",
                    category=EventCategory.WORKER,
                    component="DistributedCoordinator",
                    correlation_id=f"corr-lease-{lease.lease_id}",
                    severity=EventSeverity.INFO,
                    payload={"lease_id": lease.lease_id, "partition": partition},
                )
                return True, f"Lease for '{partition}' released."
            return False, f"No active lease for '{partition}'."

    def quarantine_partition(self, partition: str, reason: str) -> None:
        """
        Immediately halt paper execution on partition and quarantine it.
        Guarantees fail-closed safety.
        """
        with self._lock:
            partition = partition.upper()
            self._quarantined_partitions.add(partition)
            lease = self._leases_by_partition.get(partition)
            if lease:
                lease.status = LeaseStatus.QUARANTINED

            self.coordination_state = CoordinationState.QUARANTINED

            global_audit_chain.append_event(
                event_type="EXECUTION_QUARANTINED",
                category=EventCategory.SECURITY,
                component="DistributedCoordinator",
                correlation_id=f"corr-quarantine-{uuid.uuid4().hex[:8]}",
                severity=EventSeverity.CRITICAL,
                payload={"partition": partition, "reason": reason, "action": "HALT_EXECUTION_FAIL_CLOSED"},
            )
            logger.critical(f"QUARANTINED partition '{partition}': {reason}. Execution halted fail-closed.")

    def unquarantine_partition(self, partition: str) -> None:
        """Remove quarantine after successful recovery verification."""
        with self._lock:
            partition = partition.upper()
            self._quarantined_partitions.discard(partition)
            if not self._quarantined_partitions:
                self.coordination_state = CoordinationState.NOMINAL

    def get_active_leases(self) -> List[WorkerLease]:
        """Retrieve list of currently valid, unexpired leases."""
        with self._lock:
            now = datetime.now(timezone.utc)
            return [l for l in self._leases_by_partition.values() if not l.is_expired(now) and l.status == LeaseStatus.ACTIVE]

    def get_quarantined_partitions(self) -> List[str]:
        with self._lock:
            return sorted(list(self._quarantined_partitions))

    def _handle_split_brain(
        self,
        partition: str,
        existing_lease: WorkerLease,
        contender_node: str,
        contender_worker: str,
    ) -> None:
        """Enforce split-brain protection by immediately quarantining the partition."""
        reason = (
            f"Split-brain detected on partition {partition}: "
            f"existing lease held by {existing_lease.owner_worker_id} (node {existing_lease.owner_node_id}), "
            f"contender {contender_worker} (node {contender_node}) attempted acquisition."
        )
        self.coordination_state = CoordinationState.SPLIT_BRAIN_SUSPECTED
        self.quarantine_partition(partition, reason)


# Global distributed coordinator singleton
global_distributed_coordinator = DistributedCoordinator()
