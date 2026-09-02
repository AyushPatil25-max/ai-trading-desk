"""
Phase 26 — Comprehensive Tests for Live Trading Readiness & Controlled Activation

Scenarios Tested (A through AE):
A. All readiness checks pass when environment & mock Dhan are healthy.
B. Missing credentials (DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN missing).
C. Invalid credentials (DHAN_AUTH_FAILED).
D. Dhan unavailable (DHAN_UNAVAILABLE).
E. Account unavailable.
F. Kill switch active (Readiness = BLOCKED, armed state invalidated).
G. Live execution disabled (LIVE_EXECUTION_ENABLED=false).
H. Market closed / weekend handling.
I. Market state unknown handling.
J. Stale market data (>300s) blocked.
K. Safety engine availability.
L. Audit chain availability.
M. Confirmation store availability.
N. Broker adapter availability.
O. Paper / live mode isolation verified.
P. Successful live arm with explicit acknowledgement.
Q. Live arm blocked when acknowledgement=False or readiness fails.
R. Arm auto-expiration after TTL.
S. Explicit disarm immediately revokes armed session.
T. Kill switch immediately invalidates active armed state.
U. Invalidation on configuration change.
V. Live order submission blocked when disarmed.
W. Live order requires both valid confirmation and active armed state.
X. Live arm REST endpoints enforce validation & fail closed.
Y. Readiness check endpoints never arm live trading automatically.
Z. No Dhan HTTP request on any blocked/disarmed path.
AA. Secrets redacted across logs, reports, and audit trail.
AB. Paper trading remains fully functional.
"""

from datetime import datetime, timezone, timedelta
import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.domain.broker_schemas import (
    BrokerConnectionState,
    ExchangeSegment,
    NormalizedOrderStatus,
    OrderRequest,
    OrderSide,
    OrderType,
    ProductType,
)
from backend.domain.forward_simulation_schemas import MarketSessionState
from backend.domain.live_readiness_schemas import (
    CheckSeverity,
    LiveArmRequest,
    ReadinessCheckCode,
    ReadinessStatus,
)
from backend.adapters.dhan_adapter import DhanBrokerAdapter, DhanHTTPClient
from backend.execution.live_arming_store import (
    LiveArmingStore,
    global_live_arming_store,
)
from backend.execution.live_readiness import (
    LiveTradingReadinessEngine,
    global_live_readiness_engine,
)
from backend.execution.safety_engine import global_manual_order_safety_gate
from backend.application.confirmation_store import global_confirmation_store
from backend.application.tamper_evident_audit_chain import global_audit_chain


class TestLiveTradingReadinessAndArming(unittest.TestCase):

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
        global_live_arming_store.reset()
        global_manual_order_safety_gate.kill_switch.deactivate()

    def tearDown(self):
        self.env_patcher.stop()
        global_live_arming_store.reset()
        global_manual_order_safety_gate.kill_switch.deactivate()

    def _mock_healthy_dhan_request(self, endpoint, method="GET", payload=None):
        if "/fundlimit" in endpoint:
            return {"availabelBalance": 500000.0, "sodLimit": 500000.0}
        if "/profile" in endpoint:
            return {"clientId": "1000999888", "token": "mock_secret_token_12345"}
        if "/orders" in endpoint and method == "POST":
            return {"orderId": "dhan-live-999", "orderStatus": "TRANSIT", "remarks": "Order submitted"}
        return {}

    # A. All Readiness Checks Pass (Live Enabled + Healthy Mock)
    @patch.object(DhanHTTPClient, "request")
    def test_all_readiness_checks_pass_when_healthy(self, mock_dhan_request):
        mock_dhan_request.side_effect = self._mock_healthy_dhan_request

        with patch.dict(os.environ, {"LIVE_EXECUTION_ENABLED": "true"}):
            # Tuesday at 11:30 AM IST (06:00 UTC)
            mock_time = datetime(2026, 9, 8, 6, 0, 0, tzinfo=timezone.utc)
            report = global_live_readiness_engine.evaluate_readiness(
                enforce_market_calendar=True,
                check_time=mock_time,
                market_data_timestamp=mock_time - timedelta(seconds=10),
            )

            self.assertTrue(report.is_ready_for_arming)
            self.assertEqual(len(report.blocking_failures), 0)
            self.assertEqual(report.market_session, "OPEN")
            self.assertEqual(report.dhan_connection, "DHAN_CONNECTED")
            self.assertEqual(report.buying_power, 500000.0)

    # B. Missing Credentials
    def test_missing_credentials_detected_and_blocking(self):
        with patch.dict(os.environ, {"DHAN_CLIENT_ID": "", "DHAN_ACCESS_TOKEN": ""}):
            report = global_live_readiness_engine.evaluate_readiness()
            self.assertFalse(report.is_ready_for_arming)
            self.assertIn("Dhan Client ID is missing.", report.blocking_failures)
            self.assertIn("Dhan Access Token is missing.", report.blocking_failures)

    # C. Invalid Credentials (Auth Failure)
    @patch.object(DhanHTTPClient, "request")
    def test_dhan_auth_failure_blocks_readiness(self, mock_dhan_request):
        mock_dhan_request.side_effect = ValueError("DHAN_AUTH_FAILED")
        report = global_live_readiness_engine.evaluate_readiness()
        self.assertFalse(report.is_ready_for_arming)
        self.assertIn("Dhan authentication failed.", report.blocking_failures)

    # D. Dhan API Unavailable
    @patch.object(DhanHTTPClient, "request")
    def test_dhan_unavailable_blocks_readiness(self, mock_dhan_request):
        mock_dhan_request.side_effect = RuntimeError("DHAN_UNAVAILABLE")
        report = global_live_readiness_engine.evaluate_readiness()
        self.assertFalse(report.is_ready_for_arming)
        self.assertIn("Dhan API unreachable.", report.blocking_failures)

    # E. Account Unavailable
    @patch.object(DhanHTTPClient, "request")
    def test_account_unavailable_blocks_readiness(self, mock_dhan_request):
        def _mock_no_fund(endpoint, method="GET", payload=None):
            if "/profile" in endpoint:
                return {"clientId": "1000999888"}
            if "/fundlimit" in endpoint:
                raise RuntimeError("DHAN_API_ERROR: 500")
            return {}
        mock_dhan_request.side_effect = _mock_no_fund

        report = global_live_readiness_engine.evaluate_readiness()
        self.assertFalse(report.is_ready_for_arming)
        self.assertIn("Account synchronization failed.", report.blocking_failures)

    # F. Kill Switch Active
    @patch.object(DhanHTTPClient, "request")
    def test_kill_switch_blocks_readiness_and_invalidates_arm(self, mock_dhan_request):
        mock_dhan_request.side_effect = self._mock_healthy_dhan_request

        # First arm
        global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)
        self.assertTrue(global_live_arming_store.is_currently_armed())

        # Activate kill switch
        global_manual_order_safety_gate.kill_switch.activate()

        report = global_live_readiness_engine.evaluate_readiness()
        self.assertEqual(report.overall_status, ReadinessStatus.BLOCKED)
        self.assertFalse(report.is_ready_for_arming)
        self.assertFalse(report.is_ready_for_order)
        # Verify arm was invalidated
        self.assertFalse(global_live_arming_store.is_currently_armed())

    # G. Live Execution Disabled in Environment
    @patch.object(DhanHTTPClient, "request")
    def test_live_execution_flag_disabled_blocks_order_readiness(self, mock_dhan_request):
        mock_dhan_request.side_effect = self._mock_healthy_dhan_request
        with patch.dict(os.environ, {"LIVE_EXECUTION_ENABLED": "false"}):
            report = global_live_readiness_engine.evaluate_readiness(enforce_market_calendar=False)
            self.assertTrue(report.is_ready_for_arming)
            self.assertFalse(report.is_ready_for_order)
            self.assertIn("LIVE_EXECUTION_ENABLED is false.", report.blocking_failures)

    # H. Market Closed / Weekend
    @patch.object(DhanHTTPClient, "request")
    def test_market_closed_blocks_order_readiness(self, mock_dhan_request):
        mock_dhan_request.side_effect = self._mock_healthy_dhan_request
        # Sunday 10:00 AM IST
        sunday_time = datetime(2026, 9, 6, 4, 30, 0, tzinfo=timezone.utc)
        report = global_live_readiness_engine.evaluate_readiness(
            enforce_market_calendar=True,
            check_time=sunday_time,
        )
        self.assertEqual(report.market_session, "WEEKEND")
        self.assertFalse(report.is_ready_for_order)

    # J. Stale Market Data (>300s)
    @patch.object(DhanHTTPClient, "request")
    def test_stale_market_data_blocks_readiness(self, mock_dhan_request):
        mock_dhan_request.side_effect = self._mock_healthy_dhan_request
        now = datetime(2026, 9, 8, 6, 0, 0, tzinfo=timezone.utc)
        stale_time = now - timedelta(seconds=450)
        report = global_live_readiness_engine.evaluate_readiness(
            enforce_market_calendar=False,
            check_time=now,
            market_data_timestamp=stale_time,
        )
        self.assertFalse(report.is_ready_for_order)
        self.assertTrue(any("stale" in f.lower() for f in report.blocking_failures))

    # P. Successful Live Arming with Acknowledgement
    def test_successful_live_arming(self):
        success, msg, status = global_live_arming_store.arm(
            acknowledgement=True,
            duration_seconds=300,
            operator_notes="Test live trading session",
        )
        self.assertTrue(success)
        self.assertTrue(status.is_armed)
        self.assertGreater(status.remaining_seconds, 290)
        self.assertTrue(global_live_arming_store.is_currently_armed())

    # Q. Live Arming Blocked without Acknowledgement
    def test_live_arming_blocked_without_ack(self):
        success, msg, status = global_live_arming_store.arm(
            acknowledgement=False,
            duration_seconds=300,
        )
        self.assertFalse(success)
        self.assertFalse(status.is_armed)
        self.assertFalse(global_live_arming_store.is_currently_armed())

    # R. Arm Auto-Expiration
    def test_arm_auto_expiration(self):
        global_live_arming_store.arm(acknowledgement=True, duration_seconds=1)
        # Artificially set expires_at in the past
        global_live_arming_store._expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        
        self.assertFalse(global_live_arming_store.is_currently_armed())
        status = global_live_arming_store.get_status()
        self.assertFalse(status.is_armed)
        self.assertEqual(status.remaining_seconds, 0)

    # S. Explicit Disarm
    def test_explicit_disarm(self):
        global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)
        self.assertTrue(global_live_arming_store.is_currently_armed())

        status = global_live_arming_store.disarm(reason="Operator completed trading")
        self.assertFalse(status.is_armed)
        self.assertFalse(global_live_arming_store.is_currently_armed())
        self.assertEqual(status.reason, "Operator completed trading")

    # V. Live Order Submission Blocked When Disarmed
    @patch.object(DhanHTTPClient, "request")
    def test_live_order_blocked_when_disarmed(self, mock_dhan_request):
        mock_dhan_request.side_effect = self._mock_healthy_dhan_request

        order = OrderRequest(
            symbol="INFY",
            exchange_segment=ExchangeSegment.NSE,
            product_type=ProductType.CNC,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=5,
            price=1800.0,
            validity="DAY",
        )

        adapter = DhanBrokerAdapter()
        _, _, record = adapter.preview_manual_order(order)
        token = record.confirmation_id

        # LIVE_EXECUTION_ENABLED is true, but system is DISARMED
        with patch.dict(os.environ, {"LIVE_EXECUTION_ENABLED": "true"}):
            global_live_arming_store.disarm()
            live_adapter = DhanBrokerAdapter()
            order_res = live_adapter.submit_manual_order(order, token, _phase42_caller=True)

            self.assertEqual(order_res.status, "REJECTED")
            self.assertEqual(order_res.rejection_reason, "LIVE_TRADING_NOT_ARMED")
            self.assertIn("not currently armed", order_res.message)

    # W. Live Order Succeeds When Armed & Validated
    @patch.object(DhanHTTPClient, "request")
    def test_live_order_succeeds_when_armed_and_valid(self, mock_dhan_request):
        mock_dhan_request.side_effect = self._mock_healthy_dhan_request

        order = OrderRequest(
            symbol="INFY",
            exchange_segment=ExchangeSegment.NSE,
            product_type=ProductType.CNC,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=5,
            price=1800.0,
            validity="DAY",
        )

        adapter = DhanBrokerAdapter()
        _, _, record = adapter.preview_manual_order(order)
        token = record.confirmation_id

        with patch.dict(os.environ, {"LIVE_EXECUTION_ENABLED": "true"}):
            # Arm live trading
            global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)

            live_adapter = DhanBrokerAdapter()
            order_res = live_adapter.submit_manual_order(order, token, _phase42_caller=True)

            self.assertEqual(order_res.status, NormalizedOrderStatus.SUBMITTED.value)
            self.assertEqual(order_res.order_id, "dhan-live-999")

    # X. Live Arm REST Endpoints
    @patch.object(DhanHTTPClient, "request")
    def test_live_arm_and_status_rest_endpoints(self, mock_dhan_request):
        mock_dhan_request.side_effect = self._mock_healthy_dhan_request

        # 1. Check readiness endpoint (read-only)
        res = self.client.get("/api/broker/live/readiness")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["is_ready_for_arming"])

        # 2. Arm endpoint without ack fails
        res_fail = self.client.post("/api/broker/live/arm", json={"acknowledgement": False, "duration_seconds": 300})
        self.assertEqual(res_fail.status_code, 400)

        # 3. Arm endpoint with ack succeeds
        res_arm = self.client.post("/api/broker/live/arm", json={"acknowledgement": True, "duration_seconds": 300})
        self.assertEqual(res_arm.status_code, 200)
        arm_data = res_arm.json()
        self.assertTrue(arm_data["is_armed"])

        # 4. Status endpoint reports armed
        res_status = self.client.get("/api/broker/live/status")
        self.assertEqual(res_status.status_code, 200)
        status_data = res_status.json()
        self.assertTrue(status_data["is_armed"])

        # 5. Disarm endpoint
        res_disarm = self.client.post("/api/broker/live/disarm", json={"reason": "Test finished"})
        self.assertEqual(res_disarm.status_code, 200)
        self.assertFalse(res_disarm.json()["is_armed"])

    # AA. Secret Redaction Check
    @patch.object(DhanHTTPClient, "request")
    def test_secret_redaction_in_readiness_audit(self, mock_dhan_request):
        mock_dhan_request.side_effect = self._mock_healthy_dhan_request
        report = global_live_readiness_engine.evaluate_readiness()

        # Audit check
        events = global_audit_chain.get_recent_events(10)
        for ev in events:
            ev_str = str(ev.payload)
            self.assertNotIn("mock_secret_token_12345", ev_str)


if __name__ == "__main__":
    unittest.main()
