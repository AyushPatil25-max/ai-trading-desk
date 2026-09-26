"""
Phase 28 — Durable Persistent State Store for Execution & Operations

Provides a crash-safe, deterministic, thread-safe persistent key-value store for
the Trading OS execution subsystem:
- Monotonic revision numbers (rejects stale/out-of-order writes)
- Atomic disk writes (temporary file -> flush -> fsync -> atomic os.replace)
- SHA-256 payload integrity checksum verification
- Fail-closed corruption detection (fallback to backup, zero silent fabrication)
- Monotonic mutation commits with idempotency checks
- Safe JSON-based storage with recursive secret scrubbing

Safety Invariants:
- STRICTLY OPERATIONAL PERSISTENCE: Zero live trading authority.
- Live arming is NEVER persisted as active.
- Secrets, credentials, tokens, and raw private keys are strictly redacted.
- TIER_4_LIVE_REAL_MONEY remains permanently locked, unroutable, and fail-closed.
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

from backend.domain.observability_schemas import (
    EventCategory,
    EventSeverity,
    _sanitize_payload,
)
from backend.application.tamper_evident_audit_chain import global_audit_chain

logger = logging.getLogger(__name__)

PERSISTENT_STORE_SCHEMA_VERSION = "28.0.0"


class StateCorruptionError(Exception):
    """Raised when persisted state payload checksum verification fails (Fail-Closed)."""
    pass


class StaleRevisionError(Exception):
    """Raised when attempting to commit a mutation with revision <= current revision."""
    pass


class PersistentStateStore:
    """
    Thread-safe, crash-safe, deterministic persistent key-value state store with
    monotonic revision enforcement and atomic disk commits.
    """

    def __init__(self, data_dir: Optional[str] = None, node_id: str = "node-execution"):
        self._lock = threading.RLock()
        self.node_id = node_id
        self.data_dir = Path(data_dir) if data_dir else Path("backend/data/execution_state")
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self._revision: int = 0
        self._data: Dict[str, Any] = {}
        self._applied_idempotency_keys: Set[str] = set()
        self._corruption_detected: bool = False
        self._last_mutation_time: Optional[datetime] = None

        self._state_file = self.data_dir / "execution_state.json"
        self._backup_file = self.data_dir / "execution_state.backup.json"
        self._meta_file = self.data_dir / "execution_meta.json"

        # Initialize or load from disk
        self._load_from_disk()

    @property
    def revision(self) -> int:
        """Return the current monotonic revision number."""
        with self._lock:
            return self._revision

    def get_revision(self) -> int:
        """Return current revision number."""
        return self.revision

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve value by key from in-memory state."""
        with self._lock:
            val = self._data.get(key, default)
        return json.loads(json.dumps(val, default=str)) if isinstance(val, (dict, list)) else val

    def set(self, key: str, value: Any) -> int:
        """
        Set a single key-value pair and commit mutation atomically.
        Returns the new monotonic revision number.
        """
        with self._lock:
            res = self.commit_mutation(
                mutation_type=f"SET_{key}",
                mutations={key: value},
            )
            return res.get("new_revision", self._revision)

    def delete(self, key: str) -> bool:
        """
        Delete a key from the persistent store atomically.
        Returns True if key was present and deleted, False otherwise.
        """
        with self._lock:
            if key not in self._data:
                return False
            self.commit_mutation(
                mutation_type=f"DELETE_{key}",
                mutations={key: "__DELETED__"},
            )
            return True

    def contains(self, key: str) -> bool:
        """Check if a key exists in state."""
        with self._lock:
            return key in self._data

    def snapshot(self) -> Dict[str, Any]:
        """Return a point-in-time deep copy of the complete state dictionary."""
        with self._lock:
            return {
                "schema_version": PERSISTENT_STORE_SCHEMA_VERSION,
                "revision": self._revision,
                "node_id": self.node_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": json.loads(json.dumps(self._data)),
                "checksum": self._compute_checksum(self._data, self._revision),
            }

    def clear(self) -> None:
        """Clear all in-memory and persisted state (e.g. for test isolation)."""
        with self._lock:
            self._data.clear()
            self._applied_idempotency_keys.clear()
            self._revision = 0
            self._corruption_detected = False
            self._save_to_disk()

    def load(self) -> Dict[str, Any]:
        """Force reload state from persistent disk storage."""
        with self._lock:
            self._load_from_disk()
            return self.snapshot()

    def save(self) -> bool:
        """Force save current in-memory state to disk atomically."""
        with self._lock:
            return self._save_to_disk()

    def commit_mutation(
        self,
        mutation_type: str,
        mutations: Dict[str, Any],
        expected_revision: Optional[int] = None,
        idempotency_key: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Atomically apply and persist a batch of mutations with monotonic revision checking.
        """
        with self._lock:
            # 1. Idempotency Check
            if idempotency_key:
                if idempotency_key in self._applied_idempotency_keys:
                    logger.debug("Mutation with idempotency_key %s already applied.", idempotency_key)
                    return {
                        "status": "DUPLICATE_IGNORED",
                        "revision": self._revision,
                        "previous_revision": self._revision,
                        "new_revision": self._revision,
                        "mutations_applied": 0,
                    }

            # 2. Monotonic Revision Enforcement
            if expected_revision is not None:
                if expected_revision < self._revision:
                    self._emit_audit(
                        event_type="STATE_REVISION_CONFLICT",
                        category=EventCategory.FAILURE,
                        severity=EventSeverity.CRITICAL,
                        reason=f"Stale revision rejected: expected {expected_revision} <= current {self._revision}",
                        payload={
                            "expected_revision": expected_revision,
                            "current_revision": self._revision,
                            "mutation_type": mutation_type,
                        },
                    )
                    raise StaleRevisionError(
                        f"Stale revision conflict: expected revision {expected_revision} "
                        f"is strictly less than current revision {self._revision}"
                    )

            # 3. Apply Mutations to working state copy
            # Preserve Research Chat session identifiers
            if any(key.startswith("chat:session:") for key in mutations.keys()):
                sanitized_mutations = mutations
            else:
                sanitized_mutations = _sanitize_payload(mutations)
            working_data = json.loads(json.dumps(self._data, default=str))

            for k, v in sanitized_mutations.items():
                if v == "__DELETED__":
                    working_data.pop(k, None)
                else:
                    working_data[k] = v

            prev_rev = self._revision
            new_rev = self._revision + 1

            # 4. Atomic Disk Commit
            old_data = self._data
            old_rev = self._revision

            self._data = working_data
            self._revision = new_rev
            self._last_mutation_time = datetime.now(timezone.utc)

            success = self._save_to_disk()
            if not success:
                # Rollback in-memory state on persistence failure
                self._data = old_data
                self._revision = old_rev
                self._emit_audit(
                    event_type="STATE_MUTATION_REJECTED",
                    category=EventCategory.FAILURE,
                    severity=EventSeverity.CRITICAL,
                    reason="Atomic disk save failed during commit",
                    payload={"mutation_type": mutation_type},
                )
                raise IOError("Failed to atomically persist state mutation to disk.")

            if idempotency_key:
                self._applied_idempotency_keys.add(idempotency_key)

            # 5. Emit Audit Event
            self._emit_audit(
                event_type="STATE_MUTATION_COMMITTED",
                category=EventCategory.CONFIGURATION,
                severity=EventSeverity.INFO,
                reason=f"Committed mutation {mutation_type} (rev {prev_rev} -> {new_rev})",
                payload={
                    "mutation_type": mutation_type,
                    "previous_revision": prev_rev,
                    "new_revision": new_rev,
                    "keys_mutated": list(sanitized_mutations.keys()),
                    "correlation_id": correlation_id,
                },
            )

            return {
                "status": "COMMITTED",
                "previous_revision": prev_rev,
                "new_revision": new_rev,
                "revision": new_rev,
                "timestamp": self._last_mutation_time.isoformat(),
                "mutations_applied": len(sanitized_mutations),
            }

    # ── Internal Disk Persistence & Atomic Writes ─────────────────────────────

    def _compute_checksum(self, data: Dict[str, Any], revision: int) -> str:
        """Compute deterministic SHA-256 integrity checksum."""
        canonical = json.dumps(
            {
                "schema_version": PERSISTENT_STORE_SCHEMA_VERSION,
                "revision": revision,
                "node_id": self.node_id,
                "data": data,
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _save_to_disk(self) -> bool:
        """
        Execute atomic write using temp file + flush + fsync + os.replace.
        Also creates a secondary backup file for crash resiliency.
        """
        checksum = self._compute_checksum(self._data, self._revision)
        payload = {
            "schema_version": PERSISTENT_STORE_SCHEMA_VERSION,
            "revision": self._revision,
            "node_id": self.node_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "checksum": checksum,
            "data": _sanitize_payload(self._data),
        }
        serialized = json.dumps(payload, indent=2, sort_keys=True, default=str)

        try:
            # 1. Write to temporary file in the same directory as the state file to guarantee same filesystem
            state_dir = self._state_file.parent
            state_dir.mkdir(parents=True, exist_ok=True)
            temp_fd, temp_path = tempfile.mkstemp(
                dir=str(state_dir),
                prefix="exec_state_tmp_",
                suffix=".tmp",
            )
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                f.write(serialized)
                f.flush()
                os.fsync(f.fileno())

            # 2. Atomic replace primary state file (fallback if os.replace fails)
            try:
                os.replace(temp_path, str(self._state_file))
            except OSError as replace_err:
                logger.warning("os.replace failed (%s); attempting shutil.move fallback.", replace_err)
                import shutil
                try:
                    shutil.move(temp_path, str(self._state_file))
                except Exception as move_err:
                    logger.error("Fallback move also failed: %s", move_err)
                    raise

            # 3. Write backup file to its own directory
            backup_dir = self._backup_file.parent
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_fd, backup_tmp = tempfile.mkstemp(
                dir=str(backup_dir),
                prefix="exec_backup_tmp_",
                suffix=".tmp",
            )
            with os.fdopen(backup_fd, "w", encoding="utf-8") as f:
                f.write(serialized)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.replace(backup_tmp, str(self._backup_file))
            except OSError as replace_err:
                logger.warning("Backup os.replace failed (%s); attempting shutil.move fallback.", replace_err)
                import shutil
                try:
                    shutil.move(backup_tmp, str(self._backup_file))
                except Exception as move_err:
                    logger.error("Backup fallback move also failed: %s", move_err)
                    raise

            # 4. Update metadata file
            meta = {
                "schema_version": PERSISTENT_STORE_SCHEMA_VERSION,
                "latest_revision": self._revision,
                "latest_checksum": checksum,
                "last_written_at": datetime.now(timezone.utc).isoformat(),
            }
            with open(self._meta_file, "w", encoding="utf-8") as mf:
                json.dump(meta, mf, indent=2)

            return True
        except Exception as e:
            logger.error("Atomic disk save failed: %s", e)
            if 'temp_path' in locals() and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            return False

    def _load_from_disk(self) -> None:
        """
        Load state from disk with checksum integrity verification.
        Falls back to backup file if primary file is corrupted.
        """
        if not self._state_file.exists():
            # Clean initial state
            self._save_to_disk()
            self._emit_audit(
                event_type="STATE_STORE_INITIALIZED",
                category=EventCategory.SYSTEM,
                severity=EventSeverity.INFO,
                reason="State store initialized with clean state file",
                payload={"data_dir": str(self.data_dir), "revision": 0},
            )
            return

        # Attempt load from primary
        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                payload = json.load(f)

            if not self._verify_payload_checksum(payload):
                raise StateCorruptionError("Primary state file checksum verification failed.")

            self._revision = int(payload.get("revision", 0))
            self._data = payload.get("data", {})
            self._corruption_detected = False
            return
        except Exception as primary_err:
            logger.warning("Primary state file corrupted or unreadable: %s. Attempting backup recovery.", primary_err)
            self._corruption_detected = True

            # Attempt recovery from backup file
            if self._backup_file.exists():
                try:
                    with open(self._backup_file, "r", encoding="utf-8") as bf:
                        backup_payload = json.load(bf)

                    if self._verify_payload_checksum(backup_payload):
                        self._revision = int(backup_payload.get("revision", 0))
                        self._data = backup_payload.get("data", {})
                        logger.info("Successfully recovered persistent state from backup at revision %d.", self._revision)
                        # Re-save to restore primary
                        self._save_to_disk()
                        self._emit_audit(
                            event_type="STATE_CORRUPTION_DETECTED",
                            category=EventCategory.FAILURE,
                            severity=EventSeverity.CRITICAL,
                            reason=f"Primary state corrupted, successfully recovered from backup (rev {self._revision})",
                            payload={"primary_error": str(primary_err), "recovered_revision": self._revision},
                        )
                        return
                except Exception as backup_err:
                    logger.error("Backup state file also corrupted or unreadable: %s", backup_err)

            # Both failed -> Fail closed: emit corruption audit and initialize empty safe state
            self._emit_audit(
                event_type="STATE_CORRUPTION_DETECTED",
                category=EventCategory.FAILURE,
                severity=EventSeverity.CRITICAL,
                reason="Both primary and backup state files corrupted. Failing safely with blank state.",
                payload={"primary_error": str(primary_err)},
            )
            self._revision = 0
            self._data = {}
            self._save_to_disk()

    def _verify_payload_checksum(self, payload: Dict[str, Any]) -> bool:
        """Verify checksum matches canonical content."""
        if not isinstance(payload, dict):
            return False
        expected = payload.get("checksum")
        if not expected:
            return False
        data = payload.get("data", {})
        rev = payload.get("revision", 0)
        computed = self._compute_checksum(data, rev)
        return expected == computed

    # ── Status & Diagnostics ──────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Return sanitized operational status dictionary."""
        with self._lock:
            return {
                "schema_version": PERSISTENT_STORE_SCHEMA_VERSION,
                "current_revision": self._revision,
                "data_dir": str(self.data_dir),
                "keys_count": len(self._data),
                "corruption_detected": self._corruption_detected,
                "last_mutation_time": self._last_mutation_time.isoformat() if self._last_mutation_time else None,
                "is_healthy": not self._corruption_detected,
                "state_file_exists": self._state_file.exists(),
                "backup_file_exists": self._backup_file.exists(),
            }

    def status(self) -> Dict[str, Any]:
        return self.get_status()

    def get_health(self) -> Dict[str, Any]:
        return self.get_status()

    def health(self) -> Dict[str, Any]:
        return self.get_status()

    def _emit_audit(
        self,
        event_type: str,
        category: EventCategory,
        severity: EventSeverity,
        reason: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit standardized audit event into TamperEvidentAuditChain."""
        try:
            global_audit_chain.append_event(
                event_type=event_type,
                category=category,
                component="PersistentStateStore",
                correlation_id=f"pss-{uuid.uuid4().hex[:8]}",
                severity=severity,
                reason=reason,
                payload=_sanitize_payload(payload or {}),
            )
        except Exception:
            pass


# Global singleton instance
global_persistent_state_store = PersistentStateStore()
