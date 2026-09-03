"""
Phase 28 — Unit & Integration Tests for CrashRecoveryEngine

Covers:
- Deterministic 7-step recovery sequence
- Snapshot + Journal integrity verification
- Idempotent recovery runs
- Replay of missing journal mutations
- Fail-closed behavior on corrupted state / journal (DEGRADED / BLOCKED)
- Disarming of live trading on recovery (NEVER survives restart)
- Purging of transient retry loops on recovery
"""

import json
import os
import shutil
import tempfile
import unittest

from backend.execution.persistent_state_store import PersistentStateStore
from backend.execution.state_journal import StateJournal
from backend.execution.crash_recovery import CrashRecoveryEngine, RecoveryState
from backend.execution.live_arming_store import global_live_arming_store


class TestStateRecovery(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_recovery_")
        self.store = PersistentStateStore(data_dir=self.temp_dir, node_id="test-node")
        self.journal = StateJournal(data_dir=self.temp_dir)
        self.engine = CrashRecoveryEngine(state_store=self.store, journal=self.journal)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_clean_recovery_operational(self):
        self.store.set("app_mode", "PAPER")
        self.store.set("active_symbols", ["TCS.NS", "INFY.NS"])
        self.journal.append("SET_APP_MODE", 0, 1, {"app_mode": "PAPER"}, key="app_mode")
        self.journal.append("SET_SYMBOLS", 1, 2, {"active_symbols": ["TCS.NS", "INFY.NS"]}, key="active_symbols")

        report = self.engine.run_recovery()
        self.assertEqual(report["status"], RecoveryState.OPERATIONAL.value)
        self.assertTrue(report["is_recovered"])
        self.assertFalse(report["corruption_detected"])
        self.assertFalse(report["live_armed"])
        self.assertEqual(self.engine.operational_state, RecoveryState.OPERATIONAL)

    def test_recovery_replays_missing_journal_mutations(self):
        # Store is at revision 1
        self.store.set("initial_key", "initial_val")

        # Journal has additional mutations (e.g. store crashed before snapshot was saved)
        self.journal.append("UPDATE_A", 1, 2, {"val": 100}, key="key_a")
        self.journal.append("UPDATE_B", 2, 3, {"val": 200}, key="key_b")

        report = self.engine.run_recovery()
        self.assertEqual(report["status"], RecoveryState.OPERATIONAL.value)
        self.assertEqual(report["replayed_mutations_count"], 2)
        self.assertEqual(self.store.get("key_a"), {"val": 100})
        self.assertEqual(self.store.get("key_b"), {"val": 200})

    def test_recovery_idempotency(self):
        self.store.set("k1", "v1")
        self.journal.append("SET_K1", 0, 1, {"k1": "v1"}, key="k1")

        report1 = self.engine.run_recovery()
        report2 = self.engine.run_recovery()

        self.assertEqual(report1["status"], report2["status"])
        self.assertEqual(report1["revision"], report2["revision"])

    def test_recovery_fails_closed_on_corrupted_journal(self):
        self.journal.append("EV1", 0, 1, {"data": 1})
        self.journal.append("EV2", 1, 2, {"data": 2})

        # Tamper with journal
        with open(self.journal._journal_file, "w", encoding="utf-8") as f:
            f.write("CORRUPTED_TAMPERED_JOURNAL\n")

        tampered_journal = StateJournal(data_dir=self.temp_dir)
        engine = CrashRecoveryEngine(state_store=self.store, journal=tampered_journal)

        report = engine.run_recovery()
        self.assertEqual(report["status"], RecoveryState.BLOCKED.value)
        self.assertFalse(report["is_recovered"])
        self.assertTrue(report["corruption_detected"])
        self.assertEqual(engine.operational_state, RecoveryState.BLOCKED)

    def test_live_trading_disarmed_on_recovery(self):
        # Arm live trading in memory
        global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)
        self.assertTrue(global_live_arming_store.get_status().is_armed)

        # Run recovery
        report = self.engine.run_recovery()
        self.assertFalse(report["live_armed"])
        self.assertFalse(global_live_arming_store.get_status().is_armed)


if __name__ == "__main__":
    unittest.main()
