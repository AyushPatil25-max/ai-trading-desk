"""
Phase 28 — Append-Only Write-Ahead State Journal

Implements a deterministic, cryptographically chained state journal recording:
- Tick ingestion state
- Decision state
- Risk assessment state
- Order intent & paper order submissions
- Fills & position state updates
- Accounting adjustments
- Worker lifecycle events
- Checkpoint commits

Integrates seamlessly with Phase 23 TamperEvidentAuditChain to prevent split audit trails.

Safety Invariant:
- Real-money live trading remains permanently locked, unroutable, and fail-closed.
- Operates strictly in PAPER, SHADOW, and RESEARCH modes.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional, Tuple
import uuid

from backend.domain.observability_schemas import EventCategory, EventSeverity
from backend.domain.distributed_state_schemas import JournalRecord
from backend.application.tamper_evident_audit_chain import global_audit_chain

logger = logging.getLogger(__name__)


class JournalCorruptionError(Exception):
    """Raised when journal hash chaining or record verification fails (Fail-Closed)."""
    pass


class StateJournal:
    """
    Append-only write-ahead state journal with SHA-256 cryptographic chaining.
    """

    def __init__(self, journal_dir: Optional[str] = None, node_id: str = "node-local"):
        self._lock = threading.RLock()
        self.node_id = node_id
        self.journal_dir = Path(journal_dir) if journal_dir else Path("backend/data/journal")
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        self.journal_file = self.journal_dir / "state_journal.jsonl"

        self._records: List[JournalRecord] = []
        self._last_record_hash: str = "GENESIS_STATE_JOURNAL_HASH_PHASE28"

        # Load existing records if available
        self._load_and_verify_journal()

    @property
    def latest_sequence(self) -> int:
        with self._lock:
            return len(self._records)

    @property
    def last_hash(self) -> str:
        with self._lock:
            return self._last_record_hash

    def append_entry(
        self,
        event_type: str,
        state_revision: int,
        payload: Dict[str, Any],
        correlation_id: Optional[str] = None,
    ) -> JournalRecord:
        """
        Append a deterministic event to the journal with SHA-256 hash chaining.
        Also emits an operational event to global_audit_chain.
        """
        with self._lock:
            seq_num = len(self._records) + 1
            payload_canonical = json.dumps(payload, sort_keys=True)
            p_checksum = hashlib.sha256(payload_canonical.encode("utf-8")).hexdigest()

            record = JournalRecord(
                sequence_num=seq_num,
                event_type=event_type,
                state_revision=state_revision,
                source_node=self.node_id,
                payload=payload,
                payload_checksum=p_checksum,
                prev_hash=self._last_record_hash,
            )
            record.record_hash = record.compute_record_hash()

            self._records.append(record)
            self._last_record_hash = record.record_hash

            # Append to disk journal
            with open(self.journal_file, "a", encoding="utf-8") as f:
                f.write(record.model_dump_json() + "\n")

            # Forward to Phase 23 TamperEvidentAuditChain for unified observability
            global_audit_chain.append_event(
                event_type=f"JOURNAL_{event_type}",
                category=EventCategory.SYSTEM,
                component="StateJournal",
                correlation_id=correlation_id or f"corr-jrn-{uuid.uuid4().hex[:8]}",
                severity=EventSeverity.INFO,
                payload={
                    "seq": seq_num,
                    "event_type": event_type,
                    "state_revision": state_revision,
                    "record_hash": record.record_hash,
                },
            )

            return record

    def verify_integrity(self) -> Tuple[bool, int, Optional[str]]:
        """
        Verify the integrity of all journal records from genesis to head.
        Returns (is_valid, records_verified, error_message).
        """
        with self._lock:
            expected_prev = "GENESIS_STATE_JOURNAL_HASH_PHASE28"
            for idx, rec in enumerate(self._records):
                if rec.prev_hash != expected_prev:
                    msg = (
                        f"Journal hash chain broken at sequence {rec.sequence_num}: "
                        f"expected prev_hash '{expected_prev}', got '{rec.prev_hash}'."
                    )
                    return False, idx, msg

                if not rec.verify_record_hash():
                    msg = f"Journal record payload hash mismatch at sequence {rec.sequence_num}."
                    return False, idx, msg

                expected_prev = rec.record_hash

            return True, len(self._records), None

    def get_entries_since(self, sequence_num: int) -> List[JournalRecord]:
        """Retrieve journal records starting from a specific sequence number."""
        with self._lock:
            return [r for r in self._records if r.sequence_num >= sequence_num]

    def _load_and_verify_journal(self) -> None:
        """Load journal from disk and verify hash chain integrity."""
        if not self.journal_file.exists():
            return

        loaded_records: List[JournalRecord] = []
        with open(self.journal_file, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if line_str:
                    rec = JournalRecord.model_validate_json(line_str)
                    loaded_records.append(rec)

        self._records = loaded_records
        if self._records:
            is_valid, count, err = self.verify_integrity()
            if not is_valid:
                raise JournalCorruptionError(f"Corrupted journal on disk: {err}. Fail closed.")
            self._last_record_hash = self._records[-1].record_hash
            logger.info(f"Loaded and verified {count} journal entries. Head: {self._last_record_hash[:12]}...")


# Global state journal singleton
global_state_journal = StateJournal()
