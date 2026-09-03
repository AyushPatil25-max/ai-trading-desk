"""
Phase 28 — Unit & Integration Tests for Durable Order Recovery

Covers:
- Persistent order tracker restoration across process restart
- Incomplete/in-flight orders transitioned to RECOVERY_REQUIRES_RECONCILIATION
- Duplicate prevention remains fully functional on restored orders
- Reconciliation service resolves restored orders with Dhan order book
- No automatic live order retry upon restart
- REST API `/api/broker/live/status` persistence fields
- REST API `/api/broker/live/recovery/run` execution
- Zero live-money order placement during tests
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient

from backend.main import app
from backend.domain.broker_schemas import (
    ExchangeSegment,
    NormalizedOrderStatus,
    OrderRequest,
    OrderSide,
    OrderType,
    ProductType,
)
from backend.execution.order_tracker import InMemoryOrderTracker, global_order_tracker
from backend.execution.persistent_state_store import PersistentStateStore, global_persistent_state_store
from backend.execution.state_journal import StateJournal, global_state_journal
from backend.execution.crash_recovery import CrashRecoveryEngine, global_state_recovery_engine
from backend.execution.reconciliation_service import ReconciliationService


class TestDurableOrderRecovery(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_order_rec_")
        self.client = TestClient(app)
        
        # Override globals for API test safety
        global_persistent_state_store._data = {}
        global_persistent_state_store._revision = 0
        global_persistent_state_store._applied_idempotency_keys = set()
        global_persistent_state_store._state_file = Path(self.temp_dir) / "execution_state.json"
        
        global_state_journal.filepath = Path(self.temp_dir) / "test_journal.log"
        global_state_journal._entries = []
        global_state_journal._fd = None
        
        global_state_recovery_engine._corruption_detected = False


    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_order_tracker_persistence_and_restoration(self):
        tracker = InMemoryOrderTracker()
        store = PersistentStateStore(data_dir=self.temp_dir)
        journal = StateJournal(data_dir=self.temp_dir)

        order_req = OrderRequest(
            symbol="TCS.NS",
            side=OrderSide.BUY,
            quantity=10,
            order_type=OrderType.MARKET,
            product_type=ProductType.CNC,
            exchange_segment=ExchangeSegment.NSE,
            request_id="req-test-100",
        )
        fp = "fp_abc123456789"

        # Record submission and success
        tracker.record_submission(fp, "req-test-100", order=order_req)
        tracker.record_success(fp, "DHAN-ORD-9999", details={"symbol": "TCS.NS", "quantity": 10}, status="FILLED")

        # Save to store
        store.set("tracked_orders", tracker._tracked_orders)

        # Simulate restart with fresh tracker and engine
        fresh_tracker = InMemoryOrderTracker()
        engine = CrashRecoveryEngine(state_store=store, journal=journal)

        report = engine.run_recovery()
        self.assertTrue(report["is_recovered"])
        self.assertEqual(report["restored_orders_count"], 1)

        # Verify duplicate detection survives
        self.assertTrue(global_order_tracker.is_duplicate(fp))
        tracked = global_order_tracker.lookup(fp)
        self.assertIsNotNone(tracked)
        self.assertEqual(tracked["broker_order_id"], "DHAN-ORD-9999")
        self.assertEqual(tracked["status"], "FILLED")

    def test_in_flight_orders_require_reconciliation(self):
        store = PersistentStateStore(data_dir=self.temp_dir)
        journal = StateJournal(data_dir=self.temp_dir)

        # Store contains an in-flight order before crash
        in_flight_fp = "fp_in_flight_999"
        store.set("tracked_orders", {
            in_flight_fp: {
                "fingerprint": in_flight_fp,
                "request_id": "req-inflight-1",
                "broker_order_id": "DHAN-PENDING-123",
                "symbol": "INFY.NS",
                "status": "PENDING_SUBMISSION",
            }
        })

        engine = CrashRecoveryEngine(state_store=store, journal=journal)
        report = engine.run_recovery()

        self.assertEqual(report["pending_reconciliation_count"], 1)
        restored = global_order_tracker.lookup(in_flight_fp)
        self.assertEqual(restored["status"], "RECOVERY_REQUIRES_RECONCILIATION")

        # Duplicate detection still triggers to prevent double placement
        self.assertTrue(global_order_tracker.is_duplicate(in_flight_fp))

    def test_reconciliation_resolves_restored_orders(self):
        store = PersistentStateStore(data_dir=self.temp_dir)
        fp = "fp_reconcile_test"
        global_order_tracker._tracked_orders[fp] = {
            "fingerprint": fp,
            "request_id": "req-rec-1",
            "broker_order_id": "DHAN-ORD-MATCH",
            "symbol": "RELIANCE.NS",
            "status": "RECOVERY_REQUIRES_RECONCILIATION",
        }
        global_order_tracker._order_id_to_fingerprint["DHAN-ORD-MATCH"] = fp

        # Mock adapter
        class MockDhanAdapter:
            def get_order_book(self):
                return [
                    {
                        "orderId": "DHAN-ORD-MATCH",
                        "correlationId": "req-rec-1",
                        "orderStatus": "TRADED",
                        "filledQty": 10,
                    }
                ]

        rec_service = ReconciliationService()
        report = rec_service.run_once(adapter=MockDhanAdapter())

        self.assertTrue(report["success"])
        self.assertEqual(report["matched_count"], 1)
        self.assertEqual(report["resolved_count"], 1)

        # Status updated to FILLED
        updated = global_order_tracker.lookup(fp)
        self.assertEqual(updated["status"], NormalizedOrderStatus.FILLED.value)

    def test_api_status_includes_persistence_and_recovery(self):
        res = self.client.get("/api/broker/live/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertIn("persistent_store", data)
        self.assertIn("state_journal", data)
        self.assertIn("crash_recovery", data)

        self.assertIn("current_revision", data["persistent_store"])
        self.assertIn("latest_sequence", data["state_journal"])
        self.assertIn("is_operational", data["crash_recovery"])

    def test_api_recovery_run_endpoint(self):
        res = self.client.post("/api/broker/live/recovery/run")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("is_recovered"))
        self.assertFalse(data.get("live_armed"))


if __name__ == "__main__":
    unittest.main()
