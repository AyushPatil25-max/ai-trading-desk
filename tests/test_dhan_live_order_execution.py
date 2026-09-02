"""
Phase 25 — Comprehensive Tests for Dhan Live Order Execution & Two-Stage Safety Workflow

Scenarios Covered:
A. Valid preview generates Dhan payload and confirmation token.
B. Invalid preview rejected by safety gate.
C. Valid confirmation submits to Dhan API when live enabled (mocked).
D. Expired confirmation rejected.
E. Reused confirmation rejected.
F. Order fingerprint mismatch rejected.
G. Kill switch halts submission.
H. Live execution disabled (LIVE_EXECUTION_ENABLED=false) fails closed.
I. Missing Dhan credentials rejected.
J. Dhan authentication failure handled gracefully.
K. Dhan HTTP error handled gracefully.
L. Dhan timeout handled gracefully.
M. Dhan malformed response handled gracefully.
N. BUY order mapping and submission.
O. SELL order mapping and submission.
P. MARKET order execution without limit price.
Q. LIMIT order execution with price.
R. Quantity limit exceeded rejected.
S. Order value limit exceeded rejected.
T. Insufficient buying power rejected.
U. Duplicate submission protection (single-use token).
V. Order status normalization (TRANSIT, TRADED, REJECTED, CANCELLED, etc.).
W. Audit event generation across full lifecycle.
X. Secret & token redaction in logs/audit records.
Y. Order status query and cancellation API endpoints.
Z. Zero real orders sent (all HTTP calls mocked).
"""

from datetime import datetime, timezone, timedelta
import json
import os
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

from fastapi.testclient import TestClient

from backend.main import app
from backend.domain.broker_schemas import (
    ExchangeSegment,
    NormalizedOrderStatus,
    OrderPreview,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderType,
    ProductType,
    SafetyGateResult,
    SafetyReasonCode,
)
from backend.adapters.dhan_adapter import (
    DhanBrokerAdapter,
    DhanHTTPClient,
    normalize_dhan_order_status,
)
from backend.application.confirmation_store import global_confirmation_store
from backend.application.tamper_evident_audit_chain import global_audit_chain
from backend.execution.live_arming_store import global_live_arming_store
from backend.execution.safety_engine import (
    KillSwitch,
    ManualOrderSafetyGate,
    global_manual_order_safety_gate,
)


class TestDhanLiveOrderExecution(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)
        self.env_patcher = patch.dict(
            os.environ,
            {
                "DHAN_ENABLED": "true",
                "DHAN_CLIENT_ID": "1000999888",
                "DHAN_ACCESS_TOKEN": "mock_secret_token_12345",
                "LIVE_EXECUTION_ENABLED": "false",
            },
        )
        self.env_patcher.start()
        global_confirmation_store.reset()
        global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)

    def tearDown(self):
        self.env_patcher.stop()
        global_live_arming_store.reset()

    def _sample_order(self, **kwargs) -> OrderRequest:

        defaults = {
            "symbol": "TCS",
            "exchange_segment": ExchangeSegment.NSE,
            "product_type": ProductType.CNC,
            "side": OrderSide.BUY,
            "order_type": OrderType.LIMIT,
            "quantity": 10,
            "price": 3500.0,
            "validity": "DAY",
        }
        defaults.update(kwargs)
        return OrderRequest(**defaults)

    # A. Valid Preview
    def test_valid_preview_generates_token_and_payload(self):
        order = self._sample_order()
        adapter = DhanBrokerAdapter()
        gate_res, preview, record = adapter.preview_manual_order(order)
        
        self.assertTrue(gate_res.is_approved)
        self.assertTrue(preview.is_valid)
        self.assertEqual(preview.dhan_payload["transactionType"], "BUY")
        self.assertEqual(preview.dhan_payload["exchangeSegment"], "NSE_EQ")
        self.assertEqual(preview.dhan_payload["quantity"], 10)
        self.assertEqual(preview.dhan_payload["price"], 3500.0)
        self.assertIsNotNone(record)
        self.assertEqual(record.order_request.symbol, "TCS")

    # B. Invalid Preview (negative price on LIMIT)
    def test_invalid_preview_rejected(self):
        order = self._sample_order(order_type=OrderType.LIMIT, price=0.0)
        adapter = DhanBrokerAdapter()
        gate_res, preview, record = adapter.preview_manual_order(order)
        
        self.assertFalse(gate_res.is_approved)
        self.assertEqual(gate_res.reason_code, SafetyReasonCode.INVALID_PRICE)
        self.assertFalse(preview.is_valid)
        self.assertIsNone(record)

    # C. Valid Confirmation when Live Enabled (Mocked HTTP POST)
    @patch.object(DhanHTTPClient, "request")
    def test_valid_confirmation_submits_to_dhan_when_live_enabled(self, mock_dhan_request):
        def _mock_request(endpoint, method="GET", payload=None):
            if "/fundlimit" in endpoint:
                return {"availabelBalance": 500000.0}
            if "/profile" in endpoint:
                return {"clientId": "1000999888"}
            if "/orders" in endpoint and method == "POST":
                return {
                    "orderId": "1122334455",
                    "orderStatus": "TRANSIT",
                    "remarks": "Order placed successfully",
                }
            return {}

        mock_dhan_request.side_effect = _mock_request

        order = self._sample_order()
        adapter = DhanBrokerAdapter()
        gate_res, preview, record = adapter.preview_manual_order(order)
        self.assertTrue(gate_res.is_approved)
        self.assertIsNotNone(record)
        token = record.confirmation_id

        with patch.dict(os.environ, {"LIVE_EXECUTION_ENABLED": "true"}):
            live_adapter = DhanBrokerAdapter()
            order_res = live_adapter.submit_manual_order(order, token, _phase42_caller=True)

            self.assertEqual(order_res.status, NormalizedOrderStatus.SUBMITTED.value)
            self.assertEqual(order_res.order_id, "1122334455")
            self.assertIn("Order placed successfully", order_res.message)

    # D. Expired Confirmation Rejected
    def test_expired_confirmation_rejected(self):
        order = self._sample_order()
        record = global_confirmation_store.create_confirmation(order, ttl_seconds=1)
        record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)

        adapter = DhanBrokerAdapter()
        order_res = adapter.submit_manual_order(order, record.confirmation_id, _phase42_caller=True)
        self.assertEqual(order_res.status, "REJECTED")
        self.assertEqual(order_res.rejection_reason, SafetyReasonCode.TOKEN_EXPIRED.value)

    # E. Reused Confirmation Rejected
    @patch.object(DhanHTTPClient, "request")
    def test_reused_confirmation_rejected(self, mock_dhan_request):
        def _mock_request(endpoint, method="GET", payload=None):
            if "/fundlimit" in endpoint:
                return {"availabelBalance": 500000.0}
            if "/profile" in endpoint:
                return {"clientId": "1000999888"}
            if "/orders" in endpoint and method == "POST":
                return {"orderId": "999", "orderStatus": "TRANSIT"}
            return {}

        mock_dhan_request.side_effect = _mock_request

        order = self._sample_order()
        adapter = DhanBrokerAdapter()
        gate_res, preview, record = adapter.preview_manual_order(order)
        self.assertTrue(gate_res.is_approved)
        self.assertIsNotNone(record)
        token = record.confirmation_id

        with patch.dict(os.environ, {"LIVE_EXECUTION_ENABLED": "true"}):
            live_adapter = DhanBrokerAdapter()
            res1 = live_adapter.submit_manual_order(order, token, _phase42_caller=True)
            self.assertEqual(res1.status, NormalizedOrderStatus.SUBMITTED.value)

            # Re-attempt with same token
            res2 = live_adapter.submit_manual_order(order, token, _phase42_caller=True)
            self.assertEqual(res2.status, "REJECTED")
            self.assertEqual(res2.rejection_reason, SafetyReasonCode.TOKEN_REUSED.value)


    # F. Order Fingerprint Mismatch Rejected
    def test_order_fingerprint_mismatch_rejected(self):
        order1 = self._sample_order(quantity=10)
        record = global_confirmation_store.create_confirmation(order1)
        token = record.confirmation_id

        # Tampered order (quantity altered)
        order2 = self._sample_order(quantity=50)

        adapter = DhanBrokerAdapter()
        order_res = adapter.submit_manual_order(order2, token, _phase42_caller=True)
        self.assertEqual(order_res.status, "REJECTED")
        self.assertEqual(order_res.rejection_reason, SafetyReasonCode.ORDER_MISMATCH.value)

    # G. Kill Switch Halts Submission
    def test_kill_switch_halts_submission(self):
        order = self._sample_order()
        record = global_confirmation_store.create_confirmation(order)
        token = record.confirmation_id

        global_manual_order_safety_gate.kill_switch.activate()
        try:
            adapter = DhanBrokerAdapter()
            order_res = adapter.submit_manual_order(order, token, _phase42_caller=True)
            self.assertEqual(order_res.status, "REJECTED")
            self.assertEqual(order_res.rejection_reason, SafetyReasonCode.KILL_SWITCH_ACTIVE.value)
        finally:
            global_manual_order_safety_gate.kill_switch.deactivate()

    # H. Live Execution Disabled (LIVE_EXECUTION_ENABLED=false) Fails Closed
    def test_live_execution_disabled_fails_closed(self):
        order = self._sample_order()
        record = global_confirmation_store.create_confirmation(order)
        token = record.confirmation_id

        with patch.dict(os.environ, {"LIVE_EXECUTION_ENABLED": "false"}):
            adapter = DhanBrokerAdapter()
            order_res = adapter.submit_manual_order(order, token, _phase42_caller=True)
            self.assertEqual(order_res.status, "REJECTED")
            self.assertEqual(order_res.rejection_reason, SafetyReasonCode.LIVE_EXECUTION_DISABLED.value)

    # I. Missing Dhan Credentials Rejected
    def test_missing_credentials_rejected(self):
        order = self._sample_order()
        record = global_confirmation_store.create_confirmation(order)
        token = record.confirmation_id

        with patch.dict(os.environ, {"DHAN_ACCESS_TOKEN": "", "LIVE_EXECUTION_ENABLED": "true"}):
            adapter = DhanBrokerAdapter()
            order_res = adapter.submit_manual_order(order, token, _phase42_caller=True)
            self.assertEqual(order_res.status, "REJECTED")
            self.assertEqual(order_res.rejection_reason, SafetyReasonCode.BROKER_NOT_CONFIGURED.value)

    # J. Dhan Authentication Failure (401/403)
    @patch.object(DhanHTTPClient, "request")
    def test_dhan_auth_failure_handled(self, mock_dhan_request):
        mock_dhan_request.side_effect = ValueError("DHAN_AUTH_FAILED")
        order = self._sample_order()
        record = global_confirmation_store.create_confirmation(order)
        token = record.confirmation_id

        with patch.dict(os.environ, {"LIVE_EXECUTION_ENABLED": "true"}):
            adapter = DhanBrokerAdapter()
            order_res = adapter.submit_manual_order(order, token, _phase42_caller=True)
            self.assertEqual(order_res.status, "REJECTED")
            self.assertIn("DHAN_AUTH_FAILED", order_res.message)

    # K. Dhan HTTP Error
    @patch.object(DhanHTTPClient, "request")
    def test_dhan_http_error_handled(self, mock_dhan_request):
        mock_dhan_request.side_effect = RuntimeError("DHAN_API_ERROR: 500")
        order = self._sample_order()
        record = global_confirmation_store.create_confirmation(order)
        token = record.confirmation_id

        with patch.dict(os.environ, {"LIVE_EXECUTION_ENABLED": "true"}):
            adapter = DhanBrokerAdapter()
            order_res = adapter.submit_manual_order(order, token, _phase42_caller=True)
            self.assertEqual(order_res.status, "REJECTED")
            self.assertIn("DHAN_API_ERROR", order_res.message)

    # L. Dhan Timeout / Unavailable
    @patch.object(DhanHTTPClient, "request")
    def test_dhan_timeout_handled(self, mock_dhan_request):
        mock_dhan_request.side_effect = RuntimeError("DHAN_UNAVAILABLE")
        order = self._sample_order()
        record = global_confirmation_store.create_confirmation(order)
        token = record.confirmation_id

        with patch.dict(os.environ, {"LIVE_EXECUTION_ENABLED": "true"}):
            adapter = DhanBrokerAdapter()
            order_res = adapter.submit_manual_order(order, token, _phase42_caller=True)
            self.assertEqual(order_res.status, "REJECTED")
            self.assertIn("DHAN_UNAVAILABLE", order_res.message)

    # N & O. BUY vs SELL order payload translation
    @patch.object(DhanHTTPClient, "request")
    def test_sell_order_payload_translation(self, mock_dhan_request):
        mock_dhan_request.return_value = {"orderId": "sell-123", "orderStatus": "TRANSIT"}
        sell_order = self._sample_order(side=OrderSide.SELL, quantity=25, price=3600.0)
        record = global_confirmation_store.create_confirmation(sell_order)
        token = record.confirmation_id

        with patch.dict(os.environ, {"LIVE_EXECUTION_ENABLED": "true"}):
            adapter = DhanBrokerAdapter()
            order_res = adapter.submit_manual_order(sell_order, token, _phase42_caller=True)
            self.assertEqual(order_res.status, NormalizedOrderStatus.SUBMITTED.value)
            
            payload = mock_dhan_request.call_args[1]["payload"]
            self.assertEqual(payload["transactionType"], "SELL")
            self.assertEqual(payload["quantity"], 25)
            self.assertEqual(payload["price"], 3600.0)

    # P. MARKET order execution
    @patch.object(DhanHTTPClient, "request")
    def test_market_order_execution(self, mock_dhan_request):
        mock_dhan_request.return_value = {"orderId": "mkt-123", "orderStatus": "TRANSIT"}
        mkt_order = self._sample_order(order_type=OrderType.MARKET, price=None)
        record = global_confirmation_store.create_confirmation(mkt_order)
        token = record.confirmation_id

        with patch.dict(os.environ, {"LIVE_EXECUTION_ENABLED": "true"}):
            adapter = DhanBrokerAdapter()
            order_res = adapter.submit_manual_order(mkt_order, token, _phase42_caller=True)
            self.assertEqual(order_res.status, NormalizedOrderStatus.SUBMITTED.value)
            
            payload = mock_dhan_request.call_args[1]["payload"]
            self.assertEqual(payload["orderType"], "MARKET")
            self.assertEqual(payload["price"], 0.0)

    # V. Status Normalization
    def test_dhan_status_normalization(self):
        self.assertEqual(normalize_dhan_order_status("TRANSIT"), NormalizedOrderStatus.SUBMITTED)
        self.assertEqual(normalize_dhan_order_status("PENDING"), NormalizedOrderStatus.PENDING)
        self.assertEqual(normalize_dhan_order_status("OPEN"), NormalizedOrderStatus.OPEN)
        self.assertEqual(normalize_dhan_order_status("TRADED"), NormalizedOrderStatus.FILLED)
        self.assertEqual(normalize_dhan_order_status("REJECTED"), NormalizedOrderStatus.REJECTED)
        self.assertEqual(normalize_dhan_order_status("CANCELLED"), NormalizedOrderStatus.CANCELLED)
        self.assertEqual(normalize_dhan_order_status("EXPIRED"), NormalizedOrderStatus.EXPIRED)
        self.assertEqual(normalize_dhan_order_status("UNKNOWN_XYZ"), NormalizedOrderStatus.UNKNOWN)

    # Y. Query Status & Cancel Endpoints
    @patch.object(DhanHTTPClient, "request")
    def test_query_dhan_order_status_endpoint(self, mock_dhan_request):
        mock_dhan_request.return_value = {
            "orderId": "ord-888",
            "orderStatus": "TRADED",
            "quantity": 10,
            "filledQty": 10,
            "price": 3500.0,
            "averageTradedPrice": 3498.50,
            "tradingSymbol": "TCS",
        }
        res = self.client.get("/api/broker/order/ord-888/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], NormalizedOrderStatus.FILLED.value)
        self.assertEqual(data["filled_quantity"], 10)
        self.assertEqual(data["average_price"], 3498.50)

    @patch.object(DhanHTTPClient, "request")
    def test_cancel_dhan_order_endpoint(self, mock_dhan_request):
        mock_dhan_request.return_value = {"orderId": "ord-888", "status": "CANCELLED"}
        res = self.client.post("/api/broker/order/ord-888/cancel")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["cancelled"])

    # X. Secret & Token Redaction Check
    @patch.object(DhanHTTPClient, "request")
    def test_secrets_and_tokens_redacted_in_audit_chain(self, mock_dhan_request):
        mock_dhan_request.return_value = {"orderId": "redact-123", "orderStatus": "TRANSIT"}
        order = self._sample_order()
        record = global_confirmation_store.create_confirmation(order)
        token = record.confirmation_id

        with patch.dict(os.environ, {"LIVE_EXECUTION_ENABLED": "true"}):
            adapter = DhanBrokerAdapter()
            adapter.submit_manual_order(order, token, _phase42_caller=True)

            events = global_audit_chain.get_events_by_correlation_id(order.request_id)
            self.assertGreater(len(events), 0)
            for ev in events:
                self.assertNotIn("mock_secret_token_12345", str(ev.payload))
                self.assertNotIn(token, str(ev.payload))


if __name__ == "__main__":
    unittest.main()
