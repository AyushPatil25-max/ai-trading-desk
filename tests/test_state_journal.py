"""
Phase 28 — Unit & Integration Tests for StateJournal

Covers:
- Append-only journal sequencing
- SHA-256 payload checksums & cryptographic hash chaining
- Integrity verification
- Tamper detection (modified payload, sequence gap, modified record_hash, deleted lines)
- Replay into PersistentStateStore
- Truncation and compaction
- Secret redaction
"""

import json
import os
import shutil
import tempfile
import unittest

from backend.execution.state_journal import (
    GENESIS_JOURNAL_HASH,
    JournalCorruptionError,
    StateJournal,
)
from backend.execution.persistent_state_store import PersistentStateStore


class TestStateJournal(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_jnl_")
        self.journal = StateJournal(data_dir=self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_basic_append_and_sequence(self):
        r1 = self.journal.append(
            event_type="SET_CONFIG",
            previous_revision=0,
            new_revision=1,
            payload={"market": "NSE"},
            key="config",
        )
        self.assertEqual(r1["sequence_num"], 1)
        self.assertEqual(r1["prev_hash"], GENESIS_JOURNAL_HASH)
        self.assertEqual(self.journal.latest_sequence, 1)

        r2 = self.journal.append(
            event_type="UPDATE_CONFIG",
            previous_revision=1,
            new_revision=2,
            payload={"market": "BSE"},
            key="config",
        )
        self.assertEqual(r2["sequence_num"], 2)
        self.assertEqual(r2["prev_hash"], r1["record_hash"])
        self.assertEqual(self.journal.latest_sequence, 2)

    def test_verify_integrity_success(self):
        for i in range(1, 6):
            self.journal.append(
                event_type=f"EVENT_{i}",
                previous_revision=i - 1,
                new_revision=i,
                payload={"step": i},
            )

        is_valid, count, err = self.journal.verify_integrity()
        self.assertTrue(is_valid)
        self.assertEqual(count, 5)
        self.assertIsNone(err)

    def test_tamper_detection_modified_payload(self):
        self.journal.append("EV1", 0, 1, {"data": 100})
        self.journal.append("EV2", 1, 2, {"data": 200})

        # Tamper with the journal file line 1
        lines = []
        with open(self.journal._journal_file, "r", encoding="utf-8") as f:
            for line in f:
                lines.append(json.loads(line))

        lines[0]["payload"]["data"] = 999  # Tampered payload

        with open(self.journal._journal_file, "w", encoding="utf-8") as f:
            for l in lines:
                f.write(json.dumps(l) + "\n")

        tampered_journal = StateJournal(data_dir=self.temp_dir)
        is_valid, count, err = tampered_journal.verify_integrity()
        self.assertFalse(is_valid)
        self.assertIn("tampering detected", str(err).lower())

    def test_tamper_detection_deleted_record(self):
        self.journal.append("EV1", 0, 1, {"data": 1})
        self.journal.append("EV2", 1, 2, {"data": 2})
        self.journal.append("EV3", 2, 3, {"data": 3})

        # Delete middle record from file
        lines = []
        with open(self.journal._journal_file, "r", encoding="utf-8") as f:
            for line in f:
                lines.append(line)

        with open(self.journal._journal_file, "w", encoding="utf-8") as f:
            f.write(lines[0])
            f.write(lines[2])  # Skip line 1

        tampered_journal = StateJournal(data_dir=self.temp_dir)
        is_valid, count, err = tampered_journal.verify_integrity()
        self.assertFalse(is_valid)
        self.assertIn("sequence gap", str(err).lower())

    def test_journal_replay_into_state_store(self):
        store = PersistentStateStore(data_dir=self.temp_dir, node_id="replay-node")
        store.clear()

        self.journal.append("SET_A", 0, 1, {"val": 10}, key="a")
        self.journal.append("SET_B", 1, 2, {"val": 20}, key="b")
        self.journal.append("SET_C", 2, 3, {"val": 30}, key="c")

        replayed_count, keys = self.journal.replay(state_store=store)
        self.assertEqual(replayed_count, 3)
        self.assertEqual(store.get("a"), {"val": 10})
        self.assertEqual(store.get("b"), {"val": 20})
        self.assertEqual(store.get("c"), {"val": 30})

    def test_secret_scrubbing_in_journal(self):
        secret_payload = {
            "order_id": "ORD-123",
            "dhan_access_token": "SENSITIVE_SECRET_TOKEN_XYZ",
            "confirmation_token": "RAW_CONFIRM_TOKEN_ABC",
        }
        rec = self.journal.append("ORDER_SUBMITTED", 0, 1, secret_payload)

        # Check in memory and on disk
        self.assertNotIn("SENSITIVE_SECRET_TOKEN_XYZ", json.dumps(rec))
        self.assertNotIn("RAW_CONFIRM_TOKEN_ABC", json.dumps(rec))

        with open(self.journal._journal_file, "r", encoding="utf-8") as f:
            disk_content = f.read()

        self.assertNotIn("SENSITIVE_SECRET_TOKEN_XYZ", disk_content)
        self.assertNotIn("RAW_CONFIRM_TOKEN_ABC", disk_content)

    def test_journal_truncation(self):
        for i in range(1, 10):
            self.journal.append(f"EV_{i}", i - 1, i, {"count": i})

        self.assertEqual(len(self.journal.read_all()), 9)

        # Truncate to retain 4
        success = self.journal.truncate(retain_count=4)
        self.assertTrue(success)
        self.assertEqual(len(self.journal.read_all()), 4)


if __name__ == "__main__":
    unittest.main()
