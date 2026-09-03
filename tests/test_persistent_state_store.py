"""
Phase 28 — Unit & Integration Tests for PersistentStateStore

Covers:
- Basic state get, set, delete, contains, clear, snapshot
- Monotonic revision enforcement & StaleRevisionError
- Atomic crash-safe disk persistence (temp file + os.replace)
- Idempotency key tracking
- Checksum verification and corruption detection
- Backup recovery fallback
- Secret redaction in persisted states
- Concurrency and thread-safety
"""

import json
import os
import shutil
import tempfile
import threading
import unittest

from backend.execution.persistent_state_store import (
    PERSISTENT_STORE_SCHEMA_VERSION,
    PersistentStateStore,
    StaleRevisionError,
    StateCorruptionError,
)


class TestPersistentStateStore(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_pss_")
        self.store = PersistentStateStore(data_dir=self.temp_dir, node_id="test-node")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_basic_crud_operations(self):
        # Set
        rev1 = self.store.set("key1", "value1")
        self.assertEqual(rev1, 1)
        self.assertTrue(self.store.contains("key1"))
        self.assertEqual(self.store.get("key1"), "value1")
        self.assertEqual(self.store.revision, 1)

        # Update
        rev2 = self.store.set("key1", "value2")
        self.assertEqual(rev2, 2)
        self.assertEqual(self.store.get("key1"), "value2")

        # Set another key
        self.store.set("key2", {"a": 1, "b": 2})
        self.assertEqual(self.store.get("key2"), {"a": 1, "b": 2})

        # Delete
        deleted = self.store.delete("key1")
        self.assertTrue(deleted)
        self.assertFalse(self.store.contains("key1"))
        self.assertIsNone(self.store.get("key1"))

        # Delete non-existent
        self.assertFalse(self.store.delete("nonexistent"))

    def test_snapshot_structure_and_checksum(self):
        self.store.set("config", {"market": "NSE", "active": True})
        snap = self.store.snapshot()

        self.assertEqual(snap["schema_version"], PERSISTENT_STORE_SCHEMA_VERSION)
        self.assertEqual(snap["node_id"], "test-node")
        self.assertEqual(snap["revision"], 1)
        self.assertIn("config", snap["data"])
        self.assertTrue(len(snap["checksum"]) == 64)

    def test_monotonic_revision_enforcement(self):
        self.store.set("k1", "v1")  # rev 1
        self.store.set("k2", "v2")  # rev 2
        self.assertEqual(self.store.revision, 2)

        # Expected revision 2 succeeds
        self.store.commit_mutation("TEST_MUT", {"k3": "v3"}, expected_revision=2)
        self.assertEqual(self.store.revision, 3)

        # Stale revision (expected revision 1 < current 3) raises StaleRevisionError
        with self.assertRaises(StaleRevisionError):
            self.store.commit_mutation("STALE_MUT", {"k4": "v4"}, expected_revision=1)

    def test_idempotency_key_deduplication(self):
        res1 = self.store.commit_mutation("MUT1", {"key": "val1"}, idempotency_key="idemp-100")
        self.assertEqual(res1["status"], "COMMITTED")
        self.assertEqual(res1["new_revision"], 1)

        # Duplicate mutation with same idempotency key
        res2 = self.store.commit_mutation("MUT1", {"key": "val2"}, idempotency_key="idemp-100")
        self.assertEqual(res2["status"], "DUPLICATE_IGNORED")
        self.assertEqual(res2["revision"], 1)
        self.assertEqual(self.store.get("key"), "val1")

    def test_secret_scrubbing_on_persistence(self):
        sensitive_data = {
            "symbol": "TCS.NS",
            "dhan_access_token": "SUPER_SECRET_TOKEN_12345",
            "client_secret": "MY_CLIENT_SECRET",
            "raw_confirmation_token": "CONFIRM_TOKEN_ABC",
        }
        self.store.set("order_payload", sensitive_data)

        # Read directly from state file on disk
        state_file = self.store._state_file
        with open(state_file, "r", encoding="utf-8") as f:
            disk_content = f.read()

        self.assertNotIn("SUPER_SECRET_TOKEN_12345", disk_content)
        self.assertNotIn("MY_CLIENT_SECRET", disk_content)
        self.assertNotIn("CONFIRM_TOKEN_ABC", disk_content)
        self.assertIn("***REDACTED***", disk_content)

    def test_restart_persistence(self):
        self.store.set("user_pref", {"theme": "dark", "sound": False})
        self.store.set("counter", 42)
        rev = self.store.revision

        # Re-instantiate store pointing to same data_dir (simulating process restart)
        restarted_store = PersistentStateStore(data_dir=self.temp_dir, node_id="test-node")
        self.assertEqual(restarted_store.revision, rev)
        self.assertEqual(restarted_store.get("user_pref"), {"theme": "dark", "sound": False})
        self.assertEqual(restarted_store.get("counter"), 42)

    def test_backup_recovery_on_corrupted_primary(self):
        self.store.set("important_state", "preserved_data")
        rev = self.store.revision

        # Corrupt the primary state file
        with open(self.store._state_file, "w", encoding="utf-8") as f:
            f.write("CORRUPTED_GARBAGE_JSON{{{")

        # Re-instantiate store -> should recover from backup file
        recovered_store = PersistentStateStore(data_dir=self.temp_dir, node_id="test-node")
        self.assertEqual(recovered_store.revision, rev)
        self.assertEqual(recovered_store.get("important_state"), "preserved_data")

    def test_fail_closed_on_both_files_corrupted(self):
        self.store.set("data", 123)

        # Corrupt both files
        with open(self.store._state_file, "w", encoding="utf-8") as f:
            f.write("CORRUPTED")
        with open(self.store._backup_file, "w", encoding="utf-8") as f:
            f.write("CORRUPTED")

        # Should fail safely with clean blank state (never crash or fabricate)
        safe_store = PersistentStateStore(data_dir=self.temp_dir, node_id="test-node")
        self.assertEqual(safe_store.revision, 0)
        self.assertEqual(safe_store.snapshot()["data"], {})

    def test_concurrent_mutations_thread_safety(self):
        def worker(worker_id: int):
            for i in range(10):
                self.store.commit_mutation(
                    mutation_type=f"WORKER_{worker_id}",
                    mutations={f"w_{worker_id}_{i}": i},
                )

        threads = [threading.Thread(target=worker, args=(w,)) for w in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(self.store.revision, 50)
        status = self.store.get_status()
        self.assertEqual(status["keys_count"], 50)
        self.assertTrue(status["is_healthy"])


if __name__ == "__main__":
    unittest.main()
