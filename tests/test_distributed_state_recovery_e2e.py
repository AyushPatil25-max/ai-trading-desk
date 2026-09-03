"""
Phase 28 — Distributed State, Persistent Recovery & Multi-Node Coordination E2E Tests

Comprehensive test suite covering:
1. Distributed state schemas and monotonic revision checks
2. Persistent state store: atomic disk writes and checksum verification
3. State corruption detection: corrupted file fails closed with StateCorruptionError
4. Monotonic revision enforcement: stale revision raises StaleRevisionError
5. Idempotent mutation handling: duplicate key returns without duplicate state changes
6. Snapshot creation, checksum calculation, and verified restoration
7. Corrupted snapshot restoration fails closed
8. Write-ahead state journal: append-only and SHA-256 cryptographic chaining
9. Journal integrity verification from genesis
10. Journal corruption detection fails closed
11. Multi-node identity: sanitized metadata, software version, zero secrets
12. Worker leases: acquisition, TTL calculation, renewal
13. Duplicate worker prevention and split-brain detection
14. Split-brain automatic quarantine and fail-closed execution halt
15. Manual partition quarantine and unquarantine controls
16. State conflict resolver: revision conflict detection
17. State conflict resolver: accounting balance divergence quarantine
18. Non-financial vs financial conflict resolution restrictions
19. 14-Step deterministic recovery workflow execution (all 14 steps pass)
20. Recovery verification report structure and audit event emission
21. Integration with Phase 27 System Certification Scorecard
22. Direct REST route invocations across all distributed endpoints
23. FastAPI router inclusion in main application
24. Non-negotiable safety invariant: TIER_4_LIVE_REAL_MONEY permanently locked
"""

from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from backend.domain.distributed_state_schemas import (
    DISTRIBUTED_STATE_VERSION,
    ConflictRecord,
    ConsistencyState,
    CoordinationState,
    DistributedHealthSnapshot,
    JournalRecord,
    LeaderStatus,
    LeaseStatus,
    NodeIdentity,
    RecoveryStatus,
    RecoveryVerificationReport,
    StateRevision,
    StateSnapshot,
    WorkerLease,
)
from backend.application.persistent_state_store import (
    PersistentStateStore,
    StaleRevisionError,
    StateCorruptionError,
    global_persistent_state_store,
)
from backend.application.state_journal import (
    JournalCorruptionError,
    StateJournal,
    global_state_journal,
)
from backend.application.node_identity_manager import (
    NodeIdentityManager,
    global_node_identity_manager,
)
from backend.application.distributed_coordinator import (
    DistributedCoordinator,
    global_distributed_coordinator,
)
from backend.application.state_conflict_resolver import (
    StateConflictResolver,
    global_state_conflict_resolver,
)
from backend.application.distributed_recovery_engine import (
    DistributedRecoveryEngine,
    global_distributed_recovery_engine,
)
from backend.application.production_readiness_engine import global_production_readiness_engine
from backend.application.tamper_evident_audit_chain import global_audit_chain
from backend.application.broker_interface import BrokerFactory, ConfigurationSafetyError


class TestPersistentStateStore(unittest.TestCase):
    """1, 2, 3, 4, 5, 6, 7. Durable persistence, revisions, checksums, corruption fail-closed."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.store = PersistentStateStore(data_dir=self.temp_dir, node_id="test-node-1")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_atomic_commit_and_monotonic_revision(self):
        rev1 = self.store.commit_mutation(
            mutation_type="UPDATE_CASH",
            mutations={"cash": 120000.0},
        )
        self.assertEqual(rev1.revision, 1)
        self.assertEqual(self.store.current_revision, 1)
        self.assertEqual(self.store.get_state()["cash"], 120000.0)

        # Monotonic increment
        rev2 = self.store.commit_mutation(
            mutation_type="UPDATE_POSITIONS",
            mutations={"positions": {"TCS.NS": 10}},
        )
        self.assertEqual(rev2.revision, 2)
        self.assertEqual(self.store.current_revision, 2)

    def test_stale_revision_rejection_fails_closed(self):
        self.store.commit_mutation("M1", {"cash": 110000.0})
        # Attempting to commit expected_revision 1 when current is 1 (next must be 2)
        with self.assertRaises(StaleRevisionError):
            self.store.commit_mutation("M2", {"cash": 120000.0}, expected_revision=1)

    def test_idempotent_mutation_processing(self):
        rev1 = self.store.commit_mutation(
            "ORDER_FILL",
            {"cash": 95000.0},
            idempotency_key="fill-order-12345",
        )
        self.assertEqual(rev1.revision, 1)

        # Duplicate mutation with same idempotency key
        rev2 = self.store.commit_mutation(
            "ORDER_FILL",
            {"cash": 90000.0},
            idempotency_key="fill-order-12345",
        )
        # Should NOT increment revision or overwrite cash
        self.assertEqual(rev2.revision, 1)
        self.assertIn("DUPLICATE", rev2.mutation_type)
        self.assertEqual(self.store.get_state()["cash"], 95000.0)

    def test_snapshot_creation_and_restoration(self):
        self.store.commit_mutation("SETUP", {"cash": 80000.0, "positions": {"INFY.NS": 50}})
        snap = self.store.create_snapshot()
        self.assertTrue(snap.verify_checksum())
        self.assertEqual(snap.revision, 1)

        # Mutate further
        self.store.commit_mutation("MUTATE", {"cash": 50000.0})
        self.assertEqual(self.store.get_state()["cash"], 50000.0)

        # Restore
        ok, msg = self.store.restore_from_snapshot(snap)
        self.assertTrue(ok)
        self.assertEqual(self.store.get_state()["cash"], 80000.0)
        self.assertEqual(self.store.current_revision, 1)

    def test_corrupted_snapshot_fails_closed(self):
        snap = self.store.create_snapshot()
        snap.state_data["cash"] = 99999999.0  # Tamper payload
        self.assertFalse(snap.verify_checksum())
        with self.assertRaises(StateCorruptionError):
            self.store.restore_from_snapshot(snap)

    def test_disk_corruption_detection_fails_closed(self):
        self.store.commit_mutation("MUT1", {"cash": 105000.0})
        # Deliberately corrupt latest_state.json on disk
        state_path = Path(self.temp_dir) / "latest_state.json"
        with open(state_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"cash": 7777777.0}))

        # Reloading must detect checksum mismatch and fail closed
        with self.assertRaises(StateCorruptionError):
            PersistentStateStore(data_dir=self.temp_dir)


class TestStateJournal(unittest.TestCase):
    """8, 9, 10. Append-only write-ahead journal and cryptographic chaining."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.journal = StateJournal(journal_dir=self.temp_dir, node_id="test-jrn-node")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_journal_append_and_hash_chaining(self):
        r1 = self.journal.append_entry("TICK_INGESTED", 1, {"symbol": "TCS.NS", "price": 3500.0})
        self.assertEqual(r1.sequence_num, 1)
        self.assertEqual(r1.prev_hash, "GENESIS_STATE_JOURNAL_HASH_PHASE28")
        self.assertTrue(r1.verify_record_hash())

        r2 = self.journal.append_entry("ORDER_PLACED", 2, {"symbol": "TCS.NS", "qty": 10})
        self.assertEqual(r2.sequence_num, 2)
        self.assertEqual(r2.prev_hash, r1.record_hash)
        self.assertTrue(r2.verify_record_hash())

        # Verify full chain integrity
        is_valid, count, err = self.journal.verify_integrity()
        self.assertTrue(is_valid)
        self.assertEqual(count, 2)
        self.assertIsNone(err)

    def test_corrupted_journal_fails_closed(self):
        r1 = self.journal.append_entry("EV1", 1, {"data": 1})
        r2 = self.journal.append_entry("EV2", 2, {"data": 2})

        # Deliberately tamper with record 1 payload in-memory
        self.journal._records[0].payload["data"] = 9999
        is_valid, count, err = self.journal.verify_integrity()
        self.assertFalse(is_valid)
        self.assertIn("payload hash mismatch", err)


class TestNodeIdentityManager(unittest.TestCase):
    """11. Multi-node identity, sanitized configuration fingerprints, zero secrets."""

    def test_node_identity_creation_and_zero_secrets(self):
        mgr = NodeIdentityManager(node_id="node-test-01", execution_mode="PAPER")
        node = mgr.local_identity
        self.assertEqual(node.node_id, "node-test-01")
        self.assertEqual(node.execution_mode, "PAPER")
        self.assertEqual(node.software_version, DISTRIBUTED_STATE_VERSION)
        # Ensure no credential or secret fields
        self.assertNotIn("password", node.model_dump())
        self.assertNotIn("secret", node.model_dump())
        self.assertNotIn("api_key", node.model_dump())

    def test_prohibited_live_mode_raises_error(self):
        with self.assertRaises(ValueError):
            NodeIdentity(
                node_id="node-bad",
                process_id=123,
                configuration_fingerprint="abc",
                execution_mode="LIVE",
            )


class TestDistributedCoordinatorAndSplitBrain(unittest.TestCase):
    """12, 13, 14, 15. Leases, TTL, duplicate worker prevention, split-brain quarantine."""

    def setUp(self):
        self.coord = DistributedCoordinator(node_id="coord-node-1", default_lease_ttl=2.0)

    def test_lease_acquisition_and_renewal(self):
        ok, lease, msg = self.coord.acquire_lease("TCS.NS", "node-1", "worker-TCS", ttl_seconds=5.0)
        self.assertTrue(ok)
        self.assertIsNotNone(lease)
        self.assertEqual(lease.partition, "TCS.NS")
        self.assertEqual(lease.owner_worker_id, "worker-TCS")

        # Renew
        ok_ren, lease_ren, msg_ren = self.coord.renew_lease(lease.lease_id, extend_seconds=10.0)
        self.assertTrue(ok_ren)
        self.assertEqual(lease_ren.renew_count, 1)

    def test_split_brain_conflict_triggers_quarantine_and_fails_closed(self):
        # Worker 1 acquires TCS.NS
        ok1, lease1, _ = self.coord.acquire_lease("TCS.NS", "node-1", "worker-TCS-1", ttl_seconds=10.0)
        self.assertTrue(ok1)

        # Worker 2 on node-2 attempts to acquire the exact same partition while lease1 is active
        ok2, lease2, msg2 = self.coord.acquire_lease("TCS.NS", "node-2", "worker-TCS-2")
        self.assertFalse(ok2)
        self.assertIsNone(lease2)
        self.assertIn("Split-brain conflict", msg2)

        # Partition must now be automatically QUARANTINED
        self.assertIn("TCS.NS", self.coord.get_quarantined_partitions())
        self.assertEqual(self.coord.coordination_state, CoordinationState.QUARANTINED)

        # Subsequent lease attempts on quarantined partition fail closed
        ok3, _, msg3 = self.coord.acquire_lease("TCS.NS", "node-1", "worker-TCS-1")
        self.assertFalse(ok3)
        self.assertIn("QUARANTINED", msg3)

    def test_manual_quarantine_and_unquarantine(self):
        self.coord.quarantine_partition("INFY.NS", "Operator requested inspection")
        self.assertIn("INFY.NS", self.coord.get_quarantined_partitions())

        self.coord.unquarantine_partition("INFY.NS")
        self.assertNotIn("INFY.NS", self.coord.get_quarantined_partitions())

    def test_lease_expiration_detection(self):
        lease = WorkerLease(
            partition="TCS.NS",
            owner_node_id="node-1",
            owner_worker_id="worker-1",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=5),
            ttl_seconds=5.0,
        )
        self.assertTrue(lease.is_expired())

    def test_release_lease(self):
        self.coord.acquire_lease("TCS.NS", "node-1", "worker-1")
        ok, msg = self.coord.release_lease("TCS.NS")
        self.assertTrue(ok)
        self.assertEqual(len(self.coord.get_active_leases()), 0)

    def test_unquarantine_restores_nominal_state(self):
        self.coord.quarantine_partition("INFY.NS", "Test")
        self.assertEqual(self.coord.coordination_state, CoordinationState.QUARANTINED)
        self.coord.unquarantine_partition("INFY.NS")
        self.assertEqual(self.coord.coordination_state, CoordinationState.NOMINAL)


class TestStateConflictResolver(unittest.TestCase):
    """16, 17, 18. Conflict detection for revisions and accounting balances."""

    def setUp(self):
        self.resolver = StateConflictResolver()

    def test_detect_revision_conflict(self):
        conf = self.resolver.detect_revision_conflict("TCS.NS", current_revision=10, attempted_revision=8, node_id="node-remote")
        self.assertIsNotNone(conf)
        self.assertEqual(conf.field_name, "revision")
        self.assertTrue(conf.is_quarantined)

    def test_detect_accounting_conflict_and_non_blind_resolution(self):
        conf = self.resolver.detect_accounting_conflict(
            partition="PORTFOLIO",
            local_cash=100000.0,
            remote_cash=85000.0,
            local_node="node-1",
            remote_node="node-2",
        )
        self.assertIsNotNone(conf)
        self.assertEqual(conf.field_name, "cash_balance")

        # Attempting automatic resolution on financial state MUST fail
        ok, msg = self.resolver.resolve_non_financial_conflict(conf.conflict_id, "LWW", "Auto pick")
        self.assertFalse(ok)
        self.assertIn("Financial field", msg)


class TestDistributedRecoveryEngine(unittest.TestCase):
    """19, 20. 14-Step deterministic state recovery workflow."""

    def test_cluster_active_nodes_heartbeat_timeout(self):
        mgr = NodeIdentityManager(node_id="node-active")
        active = mgr.get_active_nodes(max_age_seconds=10.0)
        self.assertEqual(len(active), 1)

        # Set heartbeat in distant past
        mgr._last_heartbeat["node-active"] = datetime.now(timezone.utc) - timedelta(seconds=60)
        active_expired = mgr.get_active_nodes(max_age_seconds=10.0)
        self.assertEqual(len(active_expired), 0)

    def test_recovery_fails_closed_when_accounting_negative(self):
        # Create temp store with negative cash
        temp_dir = tempfile.mkdtemp()
        try:
            store = PersistentStateStore(data_dir=temp_dir, node_id="bad-acc-node")
            store.commit_mutation("BAD_DRAIN", {"cash": -500.0})
            rec_engine = DistributedRecoveryEngine(state_store=store)
            rep = rec_engine.execute_14_step_recovery()
            self.assertEqual(rep.status, RecoveryStatus.FAILED)
            self.assertFalse(rep.is_safe_for_execution)
            self.assertTrue(any("negative" in b.lower() for b in rep.blockers))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_14_step_recovery_workflow_execution(self):
        rec_engine = DistributedRecoveryEngine()
        report = rec_engine.execute_14_step_recovery()

        self.assertEqual(report.steps_completed, 14)
        self.assertEqual(report.total_steps, 14)
        self.assertEqual(report.status, RecoveryStatus.RECOVERED)
        self.assertTrue(report.is_safe_for_execution)
        self.assertEqual(len(report.blockers), 0)
        self.assertGreater(len(report.recovered_state_hash), 0)

        # Audit event emission
        audit_rep = global_audit_chain.verify_integrity()
        self.assertEqual(audit_rep.status.value, "VALID")


class TestCertificationAndAPIIntegration(unittest.TestCase):
    """21, 22, 23, 24. Certification scorecard, REST APIs, FastAPI inclusion, safety locks."""

    def test_phase27_certification_includes_distributed_checks(self):
        cert = global_production_readiness_engine.run_system_certification()
        self.assertEqual(cert.overall_status.value, "CERTIFIED")
        state_cat = next(c for c in cert.categories if c.category_name == "State Integrity")
        self.assertTrue(state_cat.passed)
        self.assertIn("journal verified", state_cat.evidence.lower())

    def test_direct_distributed_route_invocations(self):
        from backend.application.distributed_state_routes import (
            get_nodes,
            get_workers,
            get_state_summary,
            get_distributed_health,
            get_leases,
            get_conflicts,
            get_recovery_status,
            run_recovery_verification,
            quarantine_worker,
            unquarantine_worker,
            QuarantineRequest,
        )

        nodes = get_nodes()
        self.assertGreaterEqual(len(nodes), 1)

        workers = get_workers()
        self.assertIn("active_leases_count", workers)

        state = get_state_summary()
        self.assertIn("current_revision", state)

        health = get_distributed_health()
        self.assertEqual(health.consistency_state, ConsistencyState.CONSISTENT)
        self.assertTrue(health.tier_4_live_locked)

        rec = run_recovery_verification()
        self.assertEqual(rec.status, RecoveryStatus.RECOVERED)

        # Test quarantine via API
        q_res = quarantine_worker("RELIANCE.NS", QuarantineRequest(reason="Test reason"))
        self.assertTrue(q_res["quarantined"])

        uq_res = unquarantine_worker("RELIANCE.NS")
        self.assertFalse(uq_res["quarantined"])

    def test_fastapi_includes_distributed_router(self):
        from backend.main import app
        all_paths = []
        for r in app.routes:
            if hasattr(r, "path"):
                all_paths.append(r.path)
            if hasattr(r, "original_router") and hasattr(r.original_router, "routes"):
                all_paths.extend([sub.path for sub in r.original_router.routes if hasattr(sub, "path")])

        self.assertIn("/api/distributed/nodes", all_paths)
        self.assertIn("/api/distributed/health", all_paths)
        self.assertIn("/api/distributed/recovery/verify", all_paths)

    def test_tier4_live_real_money_permanently_locked(self):
        """TIER_4_LIVE_REAL_MONEY must remain unroutable and raise ConfigurationSafetyError."""
        with self.assertRaises(ConfigurationSafetyError):
            BrokerFactory.get_adapter("live")


if __name__ == "__main__":
    unittest.main()
