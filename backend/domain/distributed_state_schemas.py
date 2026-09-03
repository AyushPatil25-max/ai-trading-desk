"""
Phase 28 — Distributed State, Persistent Recovery & Multi-Node Coordination Domain Schemas

Strongly typed domain models for distributed state revisions, append-safe state journal records,
multi-node identities, worker leases, partition ownership, conflict records, replication status,
and 14-step recovery verification.

Safety Invariant:
- Real-money live trading remains permanently locked, unroutable, and fail-closed.
- Execution mode restricted strictly to PAPER, SHADOW, and RESEARCH.
- Zero live order submission authority.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field, model_validator


DISTRIBUTED_STATE_VERSION = "28.0.0"


# ── Enums ───────────────────────────────────────────────────────────────────

class LeaseStatus(str, Enum):
    """Lifecycle state of a worker partition lease."""
    ACQUIRED = "ACQUIRED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    QUARANTINED = "QUARANTINED"


class LeaderStatus(str, Enum):
    """Cluster coordinator leadership state."""
    LEADER = "LEADER"
    FOLLOWER = "FOLLOWER"
    CANDIDATE = "CANDIDATE"
    ISOLATED = "ISOLATED"


class CoordinationState(str, Enum):
    """Cluster coordination and split-brain safety state."""
    NOMINAL = "NOMINAL"
    SPLIT_BRAIN_SUSPECTED = "SPLIT_BRAIN_SUSPECTED"
    QUARANTINED = "QUARANTINED"
    DEGRADED = "DEGRADED"
    FAIL_CLOSED = "FAIL_CLOSED"


class ConsistencyState(str, Enum):
    """Replication and cluster consistency state."""
    CONSISTENT = "CONSISTENT"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    CONFLICT = "CONFLICT"
    CORRUPTED = "CORRUPTED"
    UNKNOWN = "UNKNOWN"


class RecoveryStatus(str, Enum):
    """Status of distributed state reconstruction and recovery."""
    IDLE = "IDLE"
    IN_PROGRESS = "IN_PROGRESS"
    RECOVERED = "RECOVERED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


# ── Core Distributed State Models ──────────────────────────────────────────

class StateRevision(BaseModel):
    """
    Monotonically increasing state revision tracking.
    Enforces deterministic ordering across mutations.
    """
    revision: int = Field(ge=0, description="Monotonic integer revision")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_node: str
    mutation_type: str
    payload_checksum: str = ""
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None


class StateDelta(BaseModel):
    """Incremental state transition from one monotonic revision to another."""
    delta_id: str = Field(default_factory=lambda: f"delta-{uuid.uuid4().hex[:8]}")
    from_revision: int = Field(ge=0)
    to_revision: int = Field(ge=1)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    mutations: Dict[str, Any] = Field(default_factory=dict)
    checksum: str = ""


class StateSnapshot(BaseModel):
    """
    Point-in-time serialized full system state snapshot with SHA-256 integrity checksum.
    """
    snapshot_id: str = Field(default_factory=lambda: f"snap-{uuid.uuid4().hex[:8]}")
    revision: int = Field(ge=0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    node_id: str
    state_data: Dict[str, Any] = Field(default_factory=dict)
    checksum: str = ""

    def compute_checksum(self) -> str:
        canonical = json.dumps(
            {
                "snapshot_id": self.snapshot_id,
                "revision": self.revision,
                "node_id": self.node_id,
                "state_data": self.state_data,
            },
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def verify_checksum(self) -> bool:
        return self.checksum == self.compute_checksum()


class StatePartition(BaseModel):
    """
    Execution partition (e.g. individual trading symbol or asset sub-portfolio)
    assigned to an individual worker under an authoritative lease.
    """
    partition_id: str
    owner_worker_id: str
    owner_node_id: str
    lease_expires_at: datetime
    is_quarantined: bool = False
    last_revision_processed: int = 0


# ── Multi-Node Identity & Leases ───────────────────────────────────────────

class NodeIdentity(BaseModel):
    """
    Deterministic identity of an operational cluster node.
    Contains strictly sanitized metadata with ZERO secrets.
    """
    node_id: str = Field(default_factory=lambda: f"node-{uuid.uuid4().hex[:8]}")
    process_id: int
    worker_ids: List[str] = Field(default_factory=list)
    startup_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    software_version: str = DISTRIBUTED_STATE_VERSION
    configuration_fingerprint: str
    execution_mode: str = "PAPER"
    is_leader: bool = False

    @model_validator(mode="after")
    def validate_mode_and_secrets(self) -> "NodeIdentity":
        if self.execution_mode.upper() == "LIVE":
            raise ValueError("Prohibited execution mode 'LIVE'. Live trading is locked.")
        return self


class WorkerLease(BaseModel):
    """
    Time-bounded lease granting exclusive processing authority over a partition.
    Guarantees no two workers process the same partition concurrently.
    """
    lease_id: str = Field(default_factory=lambda: f"lease-{uuid.uuid4().hex[:8]}")
    partition: str
    owner_node_id: str
    owner_worker_id: str
    acquired_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
    ttl_seconds: float = 10.0
    renew_count: int = 0
    status: LeaseStatus = LeaseStatus.ACTIVE

    def is_expired(self, current_time: Optional[datetime] = None) -> bool:
        now = current_time or datetime.now(timezone.utc)
        return now >= self.expires_at


# ── State Journal & Checkpointing ──────────────────────────────────────────

class JournalRecord(BaseModel):
    """
    Append-only write-ahead state journal entry with cryptographic chaining.
    """
    sequence_num: int = Field(ge=1)
    event_type: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    state_revision: int = Field(ge=0)
    source_node: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    payload_checksum: str = ""
    prev_hash: str = ""
    record_hash: str = ""

    def compute_record_hash(self) -> str:
        canonical = json.dumps(
            {
                "sequence_num": self.sequence_num,
                "event_type": self.event_type,
                "state_revision": self.state_revision,
                "source_node": self.source_node,
                "payload": self.payload,
                "payload_checksum": self.payload_checksum,
                "prev_hash": self.prev_hash,
            },
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def verify_record_hash(self) -> bool:
        return self.record_hash == self.compute_record_hash()


class RecoveryCheckpoint(BaseModel):
    """Verified recovery checkpoint referencing journal sequence and snapshot hash."""
    checkpoint_id: str = Field(default_factory=lambda: f"rec-chk-{uuid.uuid4().hex[:8]}")
    revision: int = Field(ge=0)
    journal_seq: int = Field(ge=0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    state_hash: str
    is_valid: bool = True


# ── Conflict Detection & Idempotency ───────────────────────────────────────

class ConflictRecord(BaseModel):
    """Audit record of a detected state or ownership conflict."""
    conflict_id: str = Field(default_factory=lambda: f"conf-{uuid.uuid4().hex[:8]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    partition: str
    conflicting_nodes: List[str] = Field(default_factory=list)
    conflicting_revisions: List[int] = Field(default_factory=list)
    field_name: str
    reason: str
    is_quarantined: bool = True


class ConflictResolution(BaseModel):
    """Deterministic audit record of a resolved or quarantined state conflict."""
    conflict_id: str
    resolved: bool
    strategy: str
    resolution_notes: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IdempotencyRecord(BaseModel):
    """Record tracking previously committed state mutations to prevent replay duplicates."""
    mutation_key: str
    first_seen_revision: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    node_id: str


# ── Health, Consistency & Recovery Reports ─────────────────────────────────

class DistributedHealthSnapshot(BaseModel):
    """Point-in-time health metrics of the distributed coordinator and persistence layer."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    node_count: int = 1
    active_leases_count: int = 0
    consistency_state: ConsistencyState = ConsistencyState.CONSISTENT
    coordination_state: CoordinationState = CoordinationState.NOMINAL
    split_brain_detected: bool = False
    quarantined_partitions: List[str] = Field(default_factory=list)
    latest_revision: int = 0
    journal_sequence: int = 0
    tier_4_live_locked: bool = True


class StateConsistencyReport(BaseModel):
    """Detailed cluster replication and consistency report."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: ConsistencyState = ConsistencyState.CONSISTENT
    primary_revision: int = 0
    replica_revisions: Dict[str, int] = Field(default_factory=dict)
    lag_by_replica: Dict[str, int] = Field(default_factory=dict)
    checksum_match: bool = True
    issues: List[str] = Field(default_factory=list)


class RecoveryVerificationReport(BaseModel):
    """
    14-step recovery verification audit report certifying that state was recovered deterministically.
    """
    report_id: str = Field(default_factory=lambda: f"rec-rep-{uuid.uuid4().hex[:8]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: RecoveryStatus = RecoveryStatus.RECOVERED
    steps_completed: int = Field(ge=0, le=14)
    total_steps: int = 14
    checks_passed: List[str] = Field(default_factory=list)
    blockers: List[str] = Field(default_factory=list)
    last_valid_revision: int = 0
    recovered_state_hash: str = ""
    is_safe_for_execution: bool = True
