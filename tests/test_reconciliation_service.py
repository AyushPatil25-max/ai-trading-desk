"""
Phase 27 — Dedicated Unit Tests for Reconciliation Service
"""

import time
import unittest
from unittest.mock import MagicMock

from backend.domain.broker_schemas import (
    ExchangeSegment,
    NormalizedOrderStatus,
    OrderRequest,
    OrderSide,
    OrderType,
    ProductType,
)
from backend.application.confirmation_store import compute_order_fingerprint
from backend.execution.order_tracker import global_order_tracker
from backend.execution.reconciliation_service import (
    ReconciliationService,
    global_reconciliation_service,
)


class TestReconciliationServiceDetailed(unittest.TestCase):

    def setUp(self):
        global_order_tracker.clear()
        self.service = ReconciliationService(interval_seconds=60)

    def tearDown(self):
        global_order_tracker.clear()
        self.service.stop()

    def _sample_order(self, req_id="recon-test-001"):
        return OrderRequest(
            request_id=req_id,
            symbol="TCS",
            exchange_segment=ExchangeSegment.NSE,
            product_type=ProductType.CNC,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            price=3500.0,
            trigger_price=None,
            validity="DAY",
        )

    def test_run_once_successful_matching(self):
        order = self._sample_order()
        fp = compute_order_fingerprint(order)
        global_order_tracker.record_success(fp, "dhan-99901", {"request_id": order.request_id}, status="SUBMITTED")

        mock_adapter = MagicMock()
        mock_adapter.get_order_book.return_value = [
            {
                "orderId": "dhan-99901",
                "correlationId": order.request_id,
                "orderStatus": "FILLED",
                "filledQty": 10,
            }
        ]

        report = self.service.run_once(adapter=mock_adapter)
        self.assertTrue(report["success"])
        self.assertEqual(report["matched_count"], 1)
        self.assertEqual(report["resolved_count"], 1)

        rec = global_order_tracker.lookup(fp)
        self.assertEqual(rec["status"], NormalizedOrderStatus.FILLED.value)

    def test_run_once_broker_error_fail_closed(self):
        order = self._sample_order()
        fp = compute_order_fingerprint(order)
        global_order_tracker.record_success(fp, "dhan-99902", {"request_id": order.request_id})

        mock_adapter = MagicMock()
        mock_adapter.get_order_book.side_effect = RuntimeError("DHAN_UNAVAILABLE")

        report = self.service.run_once(adapter=mock_adapter)
        self.assertFalse(report["success"])
        self.assertIn("error", report)

        # Status in tracker is preserved (not corrupted)
        rec = global_order_tracker.lookup(fp)
        self.assertIsNotNone(rec)

    def test_start_stop_lifecycle(self):
        self.assertFalse(self.service.get_status()["is_running"])
        self.service.start()
        self.assertTrue(self.service.get_status()["is_running"])
        self.service.stop()
        self.assertFalse(self.service.get_status()["is_running"])


if __name__ == "__main__":
    unittest.main()
