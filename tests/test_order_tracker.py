"""
Phase 27 — Dedicated Unit Tests for In-Memory Order Tracker
"""

import unittest

from backend.domain.broker_schemas import (
    ExchangeSegment,
    OrderRequest,
    OrderSide,
    OrderType,
    ProductType,
)
from backend.application.confirmation_store import compute_order_fingerprint
from backend.execution.order_tracker import InMemoryOrderTracker, global_order_tracker


class TestOrderTrackerDetailed(unittest.TestCase):

    def setUp(self):
        self.tracker = InMemoryOrderTracker()

    def tearDown(self):
        self.tracker.clear()
        global_order_tracker.clear()

    def _sample_order(self, symbol="INFY", qty=25, price=1500.0, req_id="req-track-001"):
        return OrderRequest(
            request_id=req_id,
            symbol=symbol,
            exchange_segment=ExchangeSegment.NSE,
            product_type=ProductType.CNC,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=qty,
            price=price,
            trigger_price=None,
            validity="DAY",
        )

    def test_record_submission_and_duplicate_detection(self):
        order = self._sample_order()
        fp = compute_order_fingerprint(order)

        self.assertFalse(self.tracker.is_duplicate(order))

        self.tracker.record_submission(fp, order.request_id, order=order)
        self.assertTrue(self.tracker.is_duplicate(order))

        rec = self.tracker.lookup(fp)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["status"], "PENDING_SUBMISSION")

    def test_record_success_and_order_id_lookup(self):
        order = self._sample_order(req_id="req-success-002")
        fp = compute_order_fingerprint(order)

        self.tracker.record_success(fp, "dhan-987654", {"symbol": "INFY", "quantity": 25})
        self.assertTrue(self.tracker.is_duplicate(order))

        rec = self.tracker.lookup_by_order_id("dhan-987654")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["fingerprint"], fp)
        self.assertEqual(rec["broker_order_id"], "dhan-987654")

    def test_update_status_and_remove(self):
        order = self._sample_order(req_id="req-update-003")
        fp = compute_order_fingerprint(order)

        self.tracker.record_success(fp, "dhan-111222")
        updated = self.tracker.update_status(fp, "FILLED", {"filled_qty": 25})
        self.assertTrue(updated)

        rec = self.tracker.lookup(fp)
        self.assertEqual(rec["status"], "FILLED")

        removed = self.tracker.remove(fp)
        self.assertTrue(removed)
        self.assertFalse(self.tracker.is_duplicate(order))
        self.assertIsNone(self.tracker.lookup(fp))

    def test_clear_resets_all_tracked_orders(self):
        for i in range(5):
            order = self._sample_order(symbol=f"SYM{i}", req_id=f"req-{i}")
            fp = compute_order_fingerprint(order)
            self.tracker.record_success(fp, f"dhan-{i}")

        self.assertEqual(self.tracker.get_stats()["total_tracked"], 5)
        self.tracker.clear()
        self.assertEqual(self.tracker.get_stats()["total_tracked"], 0)


if __name__ == "__main__":
    unittest.main()
