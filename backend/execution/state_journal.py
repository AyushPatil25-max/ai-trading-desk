"""
Phase 28 — Write-Ahead State Journal for Execution Subsystems

Provides an append-only, cryptographically chained write-ahead journal for state mutations:
- Monotonically increasing sequence numbering
- SHA-256 payload checksums
- Cryptographic hash chaining from genesis
- Pure-Python tamper, deletion, and truncation detection
- Replay capability for crash recovery
- Automatic secret scrubbing on append

Safety Invariants:
- Append-only disk record storage (JSONL).
- Zero plaintext credentials or live tokens logged.
- Tamper detection immediately fails closed.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional, Tuple
import uuid

from backend.domain.observability_schemas import (
    EventCategory,
    EventSeverity,
    _sanitize_payload,
)
from backend.application.tamper_evident_audit_chain import global_audit_chain

logger = logging.getLogger(__name__)

GENESIS_JOURNAL_HASH = "GENESIS_EXECUTION_JOURNAL_HASH_PHASE28_" + ("0" * 32)
JOURNAL_SCHEMA_VERSION = "28.0.0"


class JournalCorruptionError(Exception):
    """Raised when cryptographic verification of state journal fails (Fail-Closed)."""
    pass


class StateJournal:
    """
    Append-only, thread-safe, cryptographically chained state journal.
    """

    def __init__(self, data_dir: Optional[str] = None):
        self._lock = threading.RLock()
        self.data_dir = Path(data_dir) if data_dir else Path("backend/data/execution_state")
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self._journal_file = self.data_dir / "state_journal.jsonl"
        self._entries: List[Dict[str, Any]] = []
        self._latest_sequence: int = 0
        self._last_hash: str = GENESIS_JOURNAL_HASH
        self._has_corruption: bool = False
        self._corruption_error: Optional[str] = None

        # Load existing entries from disk
        self._load_from_disk()

    @property
    def latest_sequence(self) -> int:
        """Return the latest sequence number."""
        with self._lock:
            return self._latest_sequence

    def get_latest_sequence(self) -> int:
        return self.latest_sequence

    @property
    def last_hash(self) -> str:
        """Return the cryptographic hash of the latest journal record."""
        with self._lock:
            return self._last_hash

    def append(
        self,
        event_type: str,
        previous_revision: int,
        new_revision: int,
        payload: Dict[str, Any],
        key: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Append a new mutation entry to the write-ahead journal with cryptographic hash chaining.
        """
        with self._lock:
            sanitized_payload = _sanitize_payload(payload or {})
            payload_checksum = hashlib.sha256(
                json.dumps(sanitized_payload, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()

            seq = self._latest_sequence + 1
            prev_hash = self._last_hash
            now_iso = datetime.now(timezone.utc).isoformat()

            record_data = {
                "sequence_num": seq,
                "timestamp": now_iso,
                "event_type": event_type,
                "key": key,
                "previous_revision": previous_revision,
                "new_revision": new_revision,
                "payload": sanitized_payload,
                "payload_checksum": payload_checksum,
                "prev_hash": prev_hash,
                "correlation_id": correlation_id,
            }

            canonical = json.dumps(record_data, sort_keys=True, default=str)
            record_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            record_data["record_hash"] = record_hash

            # Write to disk (append-only with immediate flush and sync)
            try:
                with open(self._journal_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record_data) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
            except Exception as e:
                logger.error("Failed to append to state journal file: %s", e)
                raise IOError(f"Write-ahead state journal disk append failed: {e}")

            self._entries.append(record_data)
            self._latest_sequence = seq
            self._last_hash = record_hash

            # Emit audit event
            self._emit_audit(
                event_type="STATE_JOURNAL_APPENDED",
                category=EventCategory.CONFIGURATION,
                severity=EventSeverity.INFO,
                reason=f"Journal sequence #{seq} appended: {event_type} (rev {previous_revision}->{new_revision})",
                payload={
                    "sequence_num": seq,
                    "event_type": event_type,
                    "key": key,
                    "new_revision": new_revision,
                    "record_hash": record_hash,
                },
            )

            return record_data

    def append_entry(
        self,
        event_type: str,
        state_revision: int,
        payload: Dict[str, Any],
        key: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Convenience alias for append using single revision number."""
        prev_rev = max(0, state_revision - 1)
        return self.append(
            event_type=event_type,
            previous_revision=prev_rev,
            new_revision=state_revision,
            payload=payload,
            key=key,
            correlation_id=correlation_id,
        )

    def read_all(self) -> List[Dict[str, Any]]:
        """Return a copy of all loaded journal entries."""
        with self._lock:
            return [json.loads(json.dumps(e)) for e in self._entries]

    def verify_integrity(self) -> Tuple[bool, int, Optional[str]]:
        """
        Verify cryptographic integrity of entire journal history:
        1. Sequence continuity (1, 2, 3...)
        2. Payload checksum matches
        3. Cryptographic hash chaining from genesis
        Returns: (is_valid, verified_count, error_reason)
        """
        with self._lock:
            if self._has_corruption:
                return False, 0, f"Unparseable corrupted line in journal file: {self._corruption_error}"

            if not self._entries:
                return True, 0, None

            expected_prev_hash = GENESIS_JOURNAL_HASH

            for idx, entry in enumerate(self._entries, start=1):
                # 1. Monotonic sequence check
                seq = entry.get("sequence_num")
                if seq != idx:
                    err = f"Journal sequence gap at index {idx}: expected {idx}, got {seq}"
                    logger.error(err)
                    return False, idx - 1, err

                # 2. Previous hash chaining check
                prev_h = entry.get("prev_hash")
                if prev_h != expected_prev_hash:
                    err = f"Broken cryptographic hash chain at sequence {seq}: expected prev_hash {expected_prev_hash[:12]}..., got {str(prev_h)[:12]}..."
                    logger.error(err)
                    return False, idx - 1, err

                # 3. Payload checksum check
                payload = entry.get("payload", {})
                expected_payload_chk = entry.get("payload_checksum")
                actual_payload_chk = hashlib.sha256(
                    json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
                ).hexdigest()
                if expected_payload_chk != actual_payload_chk:
                    err = f"Payload tampering detected at sequence {seq}: checksum mismatch"
                    logger.error(err)
                    return False, idx - 1, err

                # 4. Record hash check
                stored_record_hash = entry.get("record_hash")
                data_copy = dict(entry)
                data_copy.pop("record_hash", None)
                canonical = json.dumps(data_copy, sort_keys=True, default=str)
                recomputed_record_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

                if stored_record_hash != recomputed_record_hash:
                    err = f"Record tampering detected at sequence {seq}: record_hash mismatch"
                    logger.error(err)
                    return False, idx - 1, err

                expected_prev_hash = stored_record_hash

            return True, len(self._entries), None

    def replay(self, state_store: Optional[Any] = None) -> Tuple[int, List[str]]:
        """
        Replay committed journal records into a state store.
        Returns (replayed_count, list_of_keys_replayed).
        """
        with self._lock:
            valid, count, err = self.verify_integrity()
            if not valid:
                raise JournalCorruptionError(f"Cannot replay corrupted journal: {err}")

            target_store = state_store
            replayed_keys = []
            replayed_count = 0

            if target_store is not None:
                for entry in self._entries:
                    key = entry.get("key")
                    payload = entry.get("payload", {})
                    new_rev = entry.get("new_revision", 0)

                    if key and target_store.revision < new_rev:
                        target_store.commit_mutation(
                            mutation_type=entry.get("event_type", "REPLAY"),
                            mutations={key: payload.get(key, payload)},
                            expected_revision=target_store.revision,
                            idempotency_key=f"replay-{entry.get('sequence_num')}",
                        )
                        replayed_keys.append(key)
                        replayed_count += 1

            return replayed_count, replayed_keys

    def truncate(self, retain_count: int = 1000) -> bool:
        """
        Safely compact/truncate the journal file while preserving the latest N entries.
        """
        with self._lock:
            if len(self._entries) <= retain_count:
                return True

            retained = self._entries[-retain_count:]
            try:
                # Write to temp file and replace
                temp_path = self.data_dir / "journal_tmp.jsonl"
                with open(temp_path, "w", encoding="utf-8") as f:
                    for entry in retained:
                        f.write(json.dumps(entry) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp_path, self._journal_file)
                self._entries = retained
                return True
            except Exception as e:
                logger.error("Journal truncation failed: %s", e)
                return False

    def compact(self, retain_count: int = 1000) -> bool:
        return self.truncate(retain_count=retain_count)

    def clear(self) -> None:
        """Clear journal entries and file (used for isolated test fixtures)."""
        with self._lock:
            self._entries.clear()
            self._latest_sequence = 0
            self._last_hash = GENESIS_JOURNAL_HASH
            if self._journal_file.exists():
                try:
                    os.remove(self._journal_file)
                except Exception:
                    pass

    def get_status(self) -> Dict[str, Any]:
        """Return operational status of the state journal."""
        with self._lock:
            is_valid, count, err = self.verify_integrity()
            return {
                "schema_version": JOURNAL_SCHEMA_VERSION,
                "latest_sequence": self._latest_sequence,
                "total_records": len(self._entries),
                "last_hash": self._last_hash,
                "journal_file": str(self._journal_file),
                "is_integrity_valid": is_valid,
                "integrity_error": err,
            }

    def status(self) -> Dict[str, Any]:
        return self.get_status()

    # ── Internal Helpers ──────────────────────────────────────────────────────

    def _load_from_disk(self) -> None:
        """Load and parse JSONL journal records from disk."""
        if not self._journal_file.exists():
            return

        entries = []
        last_h = GENESIS_JOURNAL_HASH
        last_seq = 0

        try:
            with open(self._journal_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        entries.append(record)
                        last_seq = record.get("sequence_num", last_seq + 1)
                        last_h = record.get("record_hash", last_h)
                    except json.JSONDecodeError as je:
                        logger.warning("Corrupted line in state journal: %s", je)
                        self._has_corruption = True
                        self._corruption_error = str(je)

            self._entries = entries
            self._latest_sequence = last_seq
            self._last_hash = last_h
        except Exception as e:
            logger.error("Error reading state journal: %s", e)

    def _emit_audit(
        self,
        event_type: str,
        category: EventCategory,
        severity: EventSeverity,
        reason: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            global_audit_chain.append_event(
                event_type=event_type,
                category=category,
                component="StateJournal",
                correlation_id=f"jnl-{uuid.uuid4().hex[:8]}",
                severity=severity,
                reason=reason,
                payload=_sanitize_payload(payload or {}),
            )
        except Exception:
            pass


# Global singleton instance
global_state_journal = StateJournal()
