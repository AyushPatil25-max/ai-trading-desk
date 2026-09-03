"""
Phase 28 — Durable Persistent State Store

Implements a crash-safe, deterministic state persistence engine with:
- Monotonic revision enforcement (rejects stale/out-of-order writes)
- Atomic disk writes (temp-file write -> flush -> atomic rename)
- SHA-256 integrity checksum verification
- Fail-closed corruption detection (never silently repairs or accepts corrupted state)
- Snapshot creation and verified recovery
- Idempotent mutation processing

Safety Invariant:
- Real-money live trading remains permanently locked, unroutable, and fail-closed.
- Operates strictly in PAPER, SHADOW, and RESEARCH modes.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from backend.domain.distributed_state_schemas import (
    DISTRIBUTED_STATE_VERSION,
    ConsistencyState,
    StateDelta,
    StateRevision,
    StateSnapshot,
)

logger = logging.getLogger(__name__)


class StateCorruptionError(Exception):
    """Raised when persisted state payload checksum verification fails (Fail-Closed)."""
    pass


class StaleRevisionError(Exception):
    """Raised when attempting to commit a mutation with revision <= current revision."""
    pass


class PersistentStateStore:
    """
    Durable persistent state store with monotonic revision enforcement and atomic disk commits.
    """

    def __init__(self, data_dir: Optional[str] = None, node_id: str = "node-local"):
        self._lock = threading.RLock()
        self.node_id = node_id
        self.data_dir = Path(data_dir) if data_dir else Path("backend/data/state_store")
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self._current_revision: int = 0
        self._current_state: Dict[str, Any] = {
            "initial_capital": 100000.0,
            "cash": 100000.0,
            "positions": {},
            "active_symbols": ["TCS.NS", "RELIANCE.NS", "INFY.NS"],
            "orders": {},
            "decisions": {},
        }
        self._applied_mutation_keys: Set[str] = set()
        self._snapshots: Dict[str, StateSnapshot] = {}

        # Initialize persistence file path
        self._state_file = self.data_dir / "latest_state.json"
        self._meta_file = self.data_dir / "state_meta.json"

        # Load existing state if available
        self._load_from_disk()

    @property
    def current_revision(self) -> int:
        with self._lock:
            return self._current_revision

    def get_state(self) -> Dict[str, Any]:
        """Return deep copy of current in-memory validated state."""
        with self._lock:
            return json.loads(json.dumps(self._current_state))

    def commit_mutation(
        self,
        mutation_type: str,
        mutations: Dict[str, Any],
        expected_revision: Optional[int] = None,
        idempotency_key: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> StateRevision:
        """
        Atomically commit a state mutation with monotonic revision increment and disk persistence.
        Guarantees idempotency: if idempotency_key is already committed, returns existing revision without re-applying.
        """
        with self._lock:
            # 1. Idempotency check
            if idempotency_key and idempotency_key in self._applied_mutation_keys:
                logger.info(f"Duplicate mutation skipped by idempotency key: {idempotency_key}")
                return StateRevision(
                    revision=self._current_revision,
                    source_node=self.node_id,
                    mutation_type=f"{mutation_type}_DUPLICATE_IDEMPOTENT",
                    correlation_id=correlation_id,
                )

            # 2. Monotonic revision validation
            target_revision = self._current_revision + 1
            if expected_revision is not None and expected_revision != target_revision:
                raise StaleRevisionError(
                    f"Stale revision conflict: expected revision {expected_revision}, "
                    f"but next valid revision is {target_revision} (current is {self._current_revision})."
                )

            # 3. Apply mutations in memory
            for k, v in mutations.items():
                if isinstance(v, dict) and isinstance(self._current_state.get(k), dict):
                    self._current_state[k].update(v)
                else:
                    self._current_state[k] = v

            self._current_revision = target_revision
            if idempotency_key:
                self._applied_mutation_keys.add(idempotency_key)

            # 4. Compute canonical checksum
            canonical_payload = json.dumps(self._current_state, sort_keys=True)
            checksum = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()

            rev_record = StateRevision(
                revision=self._current_revision,
                source_node=self.node_id,
                mutation_type=mutation_type,
                payload_checksum=checksum,
                correlation_id=correlation_id,
            )

            # 5. Atomic write to disk
            self._atomic_save_to_disk(checksum, rev_record)

            return rev_record

    def create_snapshot(self) -> StateSnapshot:
        """Create a point-in-time state snapshot with SHA-256 checksum."""
        with self._lock:
            snap = StateSnapshot(
                revision=self._current_revision,
                node_id=self.node_id,
                state_data=self.get_state(),
            )
            snap.checksum = snap.compute_checksum()
            self._snapshots[snap.snapshot_id] = snap

            # Persist snapshot file
            snap_file = self.data_dir / f"snapshot_{snap.revision}_{snap.snapshot_id}.json"
            canonical = snap.model_dump_json(indent=2)
            with open(snap_file, "w", encoding="utf-8") as f:
                f.write(canonical)

            return snap

    def restore_from_snapshot(self, snapshot: StateSnapshot) -> Tuple[bool, str]:
        """
        Restore state from a snapshot. Fails closed if checksum verification fails.
        """
        with self._lock:
            if not snapshot.verify_checksum():
                raise StateCorruptionError(
                    f"Snapshot {snapshot.snapshot_id} checksum mismatch! State is corrupted. Failing closed."
                )

            self._current_state = json.loads(json.dumps(snapshot.state_data))
            self._current_revision = snapshot.revision

            # Re-save restored state
            canonical_payload = json.dumps(self._current_state, sort_keys=True)
            checksum = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
            rev_record = StateRevision(
                revision=self._current_revision,
                source_node=self.node_id,
                mutation_type="SNAPSHOT_RESTORE",
                payload_checksum=checksum,
            )
            self._atomic_save_to_disk(checksum, rev_record)
            return True, f"State restored from snapshot {snapshot.snapshot_id} at revision {snapshot.revision}."

    def _atomic_save_to_disk(self, checksum: str, revision_record: StateRevision) -> None:
        """Write state and metadata using atomic rename pattern."""
        meta_payload = {
            "version": DISTRIBUTED_STATE_VERSION,
            "revision": self._current_revision,
            "node_id": self.node_id,
            "checksum": checksum,
            "timestamp": revision_record.timestamp.isoformat(),
            "mutation_type": revision_record.mutation_type,
        }

        # Write state to temp file then atomic replace
        temp_state = self.data_dir / f"temp_state_{uuid.uuid4().hex[:6]}.tmp"
        temp_meta = self.data_dir / f"temp_meta_{uuid.uuid4().hex[:6]}.tmp"

        try:
            with open(temp_state, "w", encoding="utf-8") as f:
                json.dump(self._current_state, f, indent=2, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())

            with open(temp_meta, "w", encoding="utf-8") as f:
                json.dump(meta_payload, f, indent=2, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())

            # Atomic replace
            os.replace(temp_state, self._state_file)
            os.replace(temp_meta, self._meta_file)
        finally:
            if temp_state.exists():
                try:
                    os.remove(temp_state)
                except Exception:
                    pass
            if temp_meta.exists():
                try:
                    os.remove(temp_meta)
                except Exception:
                    pass

    def _load_from_disk(self) -> None:
        """Load state from disk, validating checksum. Fails closed on corruption."""
        if not self._state_file.exists() or not self._meta_file.exists():
            return

        try:
            with open(self._meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)

            with open(self._state_file, "r", encoding="utf-8") as f:
                state_data = json.load(f)

            canonical = json.dumps(state_data, sort_keys=True)
            computed_checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

            if computed_checksum != meta.get("checksum"):
                raise StateCorruptionError(
                    f"Persisted state checksum mismatch! Expected {meta.get('checksum')}, computed {computed_checksum}. Fail closed."
                )

            self._current_state = state_data
            self._current_revision = meta.get("revision", 0)
            logger.info(f"Loaded valid state at revision {self._current_revision} (checksum {computed_checksum[:12]}...)")
        except StateCorruptionError:
            raise
        except Exception as e:
            logger.error(f"Error loading state from disk: {e}")
            raise StateCorruptionError(f"Failed to load state from disk: {e}. Fail closed.")


# Global persistent state store singleton
global_persistent_state_store = PersistentStateStore()
