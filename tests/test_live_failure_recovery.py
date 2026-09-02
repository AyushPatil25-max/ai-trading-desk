"""
Phase 27 — Live Trading Operational Verification & Failure Recovery Test Suite

Comprehensive tests for:
1. Live failure recovery engine with retry, backoff, and idempotent execution
2. In-memory order tracking and duplicate detection
3. Kill switch emergency recovery purge
4. Broker order book reconciliation
5. Account state caching and synchronization
6. Live REST API endpoints (/live/reconcile, /live/status)
7. Strict fail-closed safety and secret sanitization
"""

from datetime import datetime, timezone
import os
import unittest
from unittest.mock import MagicMock, patch

from backend.domain.broker_schemas import (
    ExchangeSegment,
    NormalizedOrderStatus,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderType,
    ProductType,
    BrokerAccountState,
    BrokerPosition,
)
from backend.domain.observability_schemas import EventCategory, EventSeverity
from backend.application.tamper_evident_audit_chain import global_audit_chain
from backend.application.confirmation_store import global_confirmation_store, compute_order_fingerprint
from backend.execution.safety_engine import KillSwitch, global_manual_order_safety_gate
from backend.execution.live_arming_store import global_live_arming_store
from backend.execution.order_tracker import InMemoryOrderTracker, global_order_tracker
from backend.execution.live_failure_recovery import (
    LiveFailureRecoveryEngine,
    is_transient_error,
    global_live_failure_engine,
)
from backend.execution.reconciliation_service import (
    ReconciliationService,
    global_reconciliation_service,
)
from backend.execution.account_sync_service import (
    AccountSyncService,
    global_account_sync_service,
)
from backend.adapters.dhan_adapter import DhanBrokerAdapter
from backend.application.broker_interface import LiveBrokerDisabledError


def make_test_order(
    symbol: str = "TCS",
    side: OrderSide = OrderSide.BUY,
    quantity: float = 10,
    price: float = 3500.0,
    request_id: str = "test-req-001",
) -> OrderRequest:
    return OrderRequest(
        request_id=request_id,
        symbol=symbol,
        exchange_segment=ExchangeSegment.NSE,
        product_type=ProductType.CNC,
        side=side,
        order_type=OrderType.LIMIT,
        quantity=quantity,
        price=price,
        trigger_price=None,
        validity="DAY",
    )


class TestTransientErrorClassification(unittest.TestCase):
    """Test deterministic classification of transient vs permanent errors."""

    def test_transient_error_detection(self):
        self.assertTrue(is_transient_error(RuntimeError("DHAN_UNAVAILABLE")))
        self.assertTrue(is_transient_error(TimeoutError("Request timed out")))
        self.assertTrue(is_transient_error(ConnectionResetError("Connection reset by peer")))
        self.assertTrue(is_transient_error(RuntimeError("503 Service Unavailable")))
        self.assertTrue(is_transient_error(RuntimeError("502 Bad Gateway")))

    def test_permanent_error_detection(self):
        self.assertFalse(is_transient_error(ValueError("DHAN_AUTH_FAILED")))
        self.assertFalse(is_transient_error(RuntimeError("401 Unauthorized")))
        self.assertFalse(is_transient_error(RuntimeError("403 Forbidden")))
        self.assertFalse(is_transient_error(RuntimeError("400 Bad Request")))
        self.assertFalse(is_transient_error(RuntimeError("SAFETY_REJECTED: Limit exceeded")))
        self.assertFalse(is_transient_error(RuntimeError("KILL_SWITCH is active")))
        self.assertFalse(is_transient_error(RuntimeError("DUPLICATE order rejected")))
        self.assertFalse(is_transient_error(None))


class TestOrderTracker(unittest.TestCase):
    """Test in-memory order tracking and duplicate protection."""

    def setUp(self):
        global_order_tracker.clear()

    def tearDown(self):
        global_order_tracker.clear()

    def test_record_and_detect_duplicate(self):
        order = make_test_order()
        fp = compute_order_fingerprint(order)

        self.assertFalse(global_order_tracker.is_duplicate(order))

        global_order_tracker.record_success(fp, "dhan-12345", {"symbol": "TCS"})
        self.assertTrue(global_order_tracker.is_duplicate(order))
        self.assertTrue(global_order_tracker.is_duplicate(fp))

        rec = global_order_tracker.lookup(fp)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["broker_order_id"], "dhan-12345")

        rec_by_id = global_order_tracker.lookup_by_order_id("dhan-12345")
        self.assertIsNotNone(rec_by_id)
        self.assertEqual(rec_by_id["fingerprint"], fp)

    def test_order_tracker_remove_and_clear(self):
        order = make_test_order()
        fp = compute_order_fingerprint(order)
        global_order_tracker.record_success(fp, "dhan-12345")

        self.assertEqual(global_order_tracker.get_stats()["total_tracked"], 1)

        removed = global_order_tracker.remove(fp)
        self.assertTrue(removed)
        self.assertFalse(global_order_tracker.is_duplicate(order))
        self.assertIsNone(global_order_tracker.lookup_by_order_id("dhan-12345"))

        global_order_tracker.record_success(fp, "dhan-999")
        global_order_tracker.clear()
        self.assertEqual(global_order_tracker.get_stats()["total_tracked"], 0)


class TestLiveFailureRecoveryEngine(unittest.TestCase):
    """Test retry, backoff, and recovery flows."""

    def setUp(self):
        global_order_tracker.clear()
        global_live_failure_engine.clear_reset()

    def tearDown(self):
        global_order_tracker.clear()
        global_live_failure_engine.clear_reset()

    def test_immediate_success_no_retry(self):
        engine = LiveFailureRecoveryEngine(max_retries=3, backoff_seconds=0.0)
        order = make_test_order()

        mock_submit = MagicMock(return_value=OrderResult(
            order_id="dhan-success-001",
            request_id=order.request_id,
            broker_name="DhanBroker",
            symbol=order.symbol,
            side=order.side.value,
            quantity=order.quantity,
            order_type=order.order_type.value,
            product_type=order.product_type.value,
            exchange_segment=order.exchange_segment.value,
            status=NormalizedOrderStatus.SUBMITTED.value,
            message="Success",
        ))

        res = engine.execute_with_recovery(order, mock_submit)
        self.assertEqual(res.status, NormalizedOrderStatus.SUBMITTED.value)
        self.assertEqual(res.order_id, "dhan-success-001")
        self.assertEqual(mock_submit.call_count, 1)
        self.assertTrue(global_order_tracker.is_duplicate(order))

    def test_transient_failure_then_retry_success(self):
        engine = LiveFailureRecoveryEngine(max_retries=3, backoff_seconds=0.0)
        order = make_test_order(request_id="test-retry-002")

        # Fails once with DHAN_UNAVAILABLE then succeeds
        mock_submit = MagicMock(side_effect=[
            RuntimeError("DHAN_UNAVAILABLE"),
            OrderResult(
                order_id="dhan-success-002",
                request_id=order.request_id,
                broker_name="DhanBroker",
                symbol=order.symbol,
                side=order.side.value,
                quantity=order.quantity,
                order_type=order.order_type.value,
                product_type=order.product_type.value,
                exchange_segment=order.exchange_segment.value,
                status=NormalizedOrderStatus.SUBMITTED.value,
                message="Success on retry",
            )
        ])

        res = engine.execute_with_recovery(order, mock_submit)
        self.assertEqual(res.status, NormalizedOrderStatus.SUBMITTED.value)
        self.assertEqual(res.order_id, "dhan-success-002")
        self.assertEqual(mock_submit.call_count, 2)
        self.assertEqual(engine.get_status()["total_retries_succeeded"], 1)

    def test_retry_exhaustion_on_persistent_transient_failure(self):
        engine = LiveFailureRecoveryEngine(max_retries=2, backoff_seconds=0.0)
        order = make_test_order(request_id="test-exhaust-003")

        mock_submit = MagicMock(side_effect=RuntimeError("DHAN_UNAVAILABLE"))

        res = engine.execute_with_recovery(order, mock_submit)
        self.assertEqual(res.status, NormalizedOrderStatus.REJECTED.value)
        self.assertEqual(res.rejection_reason, "RETRY_EXHAUSTED")
        self.assertEqual(mock_submit.call_count, 3)  # Initial + 2 retries
        self.assertEqual(engine.get_status()["total_retries_exceeded"], 1)

    def test_permanent_failure_no_retry(self):
        engine = LiveFailureRecoveryEngine(max_retries=3, backoff_seconds=0.0)
        order = make_test_order(request_id="test-perm-004")

        mock_submit = MagicMock(side_effect=ValueError("DHAN_AUTH_FAILED"))

        with self.assertRaises(ValueError):
            engine.execute_with_recovery(order, mock_submit)

        self.assertEqual(mock_submit.call_count, 1)

    def test_pre_retry_broker_reconciliation_prevents_duplicate_submission(self):
        engine = LiveFailureRecoveryEngine(max_retries=3, backoff_seconds=0.0)
        order = make_test_order(request_id="test-recon-pre-retry")

        # Simulate initial attempt timing out on network AFTER broker received order
        mock_submit = MagicMock(side_effect=RuntimeError("DHAN_UNAVAILABLE"))
        mock_reconcile = MagicMock(return_value={
            "orderId": "dhan-already-received-111",
            "orderStatus": "OPEN",
            "status": "OPEN",
        })

        res = engine.execute_with_recovery(
            order=order,
            submit_fn=mock_submit,
            reconcile_check_fn=mock_reconcile,
        )

        self.assertEqual(res.status, NormalizedOrderStatus.OPEN.value)
        self.assertEqual(res.order_id, "dhan-already-received-111")
        self.assertEqual(mock_submit.call_count, 1)  # Only 1 submission occurred!
        self.assertEqual(mock_reconcile.call_count, 1)

    def test_engine_reset_aborts_retries(self):
        engine = LiveFailureRecoveryEngine(max_retries=3, backoff_seconds=0.0)
        order = make_test_order()

        engine.reset()
        mock_submit = MagicMock()

        res = engine.execute_with_recovery(order, mock_submit)
        self.assertEqual(res.status, NormalizedOrderStatus.REJECTED.value)
        self.assertEqual(res.rejection_reason, "RECOVERY_ENGINE_RESET")
        self.assertEqual(mock_submit.call_count, 0)


class TestKillSwitchRecoveryIntegration(unittest.TestCase):
    """Test emergency kill switch integration with recovery engine and order tracker."""

    def setUp(self):
        global_order_tracker.clear()
        global_live_failure_engine.clear_reset()

    def tearDown(self):
        global_order_tracker.clear()
        global_live_failure_engine.clear_reset()

    def test_kill_switch_activation_purges_recovery_and_tracker(self):
        order = make_test_order()
        fp = compute_order_fingerprint(order)
        global_order_tracker.record_success(fp, "dhan-ks-001")

        self.assertEqual(global_order_tracker.get_stats()["total_tracked"], 1)

        # Activate kill switch
        ks = KillSwitch()
        ks.activate()

        self.assertTrue(ks.is_active())
        self.assertEqual(global_order_tracker.get_stats()["total_tracked"], 0)
        self.assertTrue(global_live_failure_engine.get_status()["is_reset"])
        self.assertFalse(global_live_arming_store.get_status().is_armed)


class TestReconciliationService(unittest.TestCase):
    """Test broker order book reconciliation."""

    def setUp(self):
        global_order_tracker.clear()

    def tearDown(self):
        global_order_tracker.clear()

    def test_reconciliation_resolves_completed_orders(self):
        order = make_test_order(request_id="recon-req-101")
        fp = compute_order_fingerprint(order)
        global_order_tracker.record_success(fp, "dhan-ord-101", {"request_id": "recon-req-101"}, status="SUBMITTED")

        mock_adapter = MagicMock()
        mock_adapter.get_order_book.return_value = [
            {
                "orderId": "dhan-ord-101",
                "correlationId": "recon-req-101",
                "orderStatus": "TRADED",
                "filledQty": 10,
            }
        ]

        service = ReconciliationService()
        report = service.run_once(adapter=mock_adapter)

        self.assertTrue(report["success"])
        self.assertEqual(report["matched_count"], 1)
        self.assertEqual(report["resolved_count"], 1)

        rec = global_order_tracker.lookup(fp)
        self.assertEqual(rec["status"], NormalizedOrderStatus.FILLED.value)

    def test_reconciliation_fails_closed_on_error(self):
        mock_adapter = MagicMock()
        mock_adapter.get_order_book.side_effect = RuntimeError("DHAN_UNAVAILABLE")

        service = ReconciliationService()
        report = service.run_once(adapter=mock_adapter)

        self.assertFalse(report["success"])
        self.assertIn("error", report)


class TestAccountSyncService(unittest.TestCase):
    """Test account balance and position caching."""

    def test_account_sync_updates_cache(self):
        mock_adapter = MagicMock()
        mock_adapter.get_account_state.return_value = BrokerAccountState(
            account_id="DHAN_TEST_USER",
            broker_name="DhanBroker",
            mode="LIVE",
            is_live=True,
            cash=75000.0,
            buying_power=75000.0,
            total_equity=75000.0,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            positions={},
            open_positions_count=0,
        )
        mock_adapter.get_positions.return_value = {
            "TCS": BrokerPosition(
                symbol="TCS",
                quantity=5,
                average_entry_price=3500.0,
                current_price=3550.0,
                market_value=17750.0,
                realized_pnl=0.0,
                unrealized_pnl=250.0,
            )
        }
        mock_adapter.get_holdings.return_value = [{"tradingSymbol": "INFY", "totalQty": 20}]

        service = AccountSyncService()
        report = service.run_once(adapter=mock_adapter)

        self.assertTrue(report["success"])
        self.assertEqual(report["cash"], 75000.0)
        self.assertEqual(report["positions_count"], 1)

        cached_acct = service.get_cached_account()
        self.assertIsNotNone(cached_acct)
        self.assertEqual(cached_acct.cash, 75000.0)

        cached_pos = service.get_cached_positions()
        self.assertIn("TCS", cached_pos)
        self.assertEqual(cached_pos["TCS"].quantity, 5)


class TestDhanBrokerAdapterRecoveryIntegration(unittest.TestCase):
    """Test end-to-end integration of recovery in DhanBrokerAdapter."""

    def setUp(self):
        global_order_tracker.clear()
        global_live_failure_engine.clear_reset()
        global_confirmation_store.clear()

    def tearDown(self):
        global_order_tracker.clear()
        global_live_failure_engine.clear_reset()
        global_confirmation_store.clear()

    def test_live_execution_disabled_blocks_before_recovery(self):
        adapter = DhanBrokerAdapter()
        adapter.live_execution_enabled = False

        order = make_test_order()
        token_record = global_confirmation_store.create_confirmation(order)

        res = adapter.submit_manual_order(order, token_record.confirmation_id, _phase42_caller=True)
        self.assertEqual(res.status, NormalizedOrderStatus.REJECTED.value)
        self.assertIn(res.rejection_reason, ("LIVE_EXECUTION_DISABLED", "LIVE_TRADING_DISABLED", "BROKER_NOT_CONFIGURED"))

        # Also test direct submit_order raises LiveBrokerDisabledError
        with self.assertRaises(LiveBrokerDisabledError):
            adapter.submit_order(MagicMock())

    def test_live_order_recovery_flow_when_armed(self):
        adapter = DhanBrokerAdapter()
        adapter.live_execution_enabled = True
        adapter.client = MagicMock()

        # Arm live trading
        global_live_arming_store.arm(
            acknowledgement="I acknowledge and accept financial risk.",
            duration_seconds=300,
        )

        order = make_test_order(symbol="TCS", quantity=5, price=3500.0)
        token_record = global_confirmation_store.create_confirmation(order)

        # Mock adapter client to fail once then succeed
        adapter.client.request.side_effect = [
            RuntimeError("DHAN_UNAVAILABLE"),
            {"orderId": "dhan-live-999", "orderStatus": "SUBMITTED", "remarks": "Accepted"},
        ]

        with patch("backend.execution.safety_engine.ManualOrderSafetyGate.evaluate_order") as mock_gate:
            from backend.domain.broker_schemas import SafetyGateResult, SafetyReasonCode
            mock_gate.return_value = SafetyGateResult(
                is_approved=True,
                reason_code=SafetyReasonCode.VALID,
                reason="Approved",
                validated_order=order,
                estimated_order_value=17500.0,
                safety_checks_performed=["ALL"],
                safety_checks_passed=["ALL"],
                safety_checks_failed=[],
                evaluated_at=datetime.now(timezone.utc),
            )

            # Use zero backoff for test speed
            with patch("backend.execution.live_failure_recovery.LiveFailureRecoveryEngine.backoff_seconds", 0.0):
                res = adapter.submit_manual_order(order, token_record.confirmation_id, _phase42_caller=True)

            self.assertEqual(res.status, NormalizedOrderStatus.SUBMITTED.value)
            self.assertEqual(res.order_id, "dhan-live-999")
            self.assertTrue(global_order_tracker.is_duplicate(order))

        global_live_arming_store.disarm("Test cleanup")


class TestBrokerLiveRoutes(unittest.TestCase):
    """Test API routes for /live/reconcile and /live/status without secret exposure."""

    def test_live_reconcile_endpoint(self):
        from backend.application.broker_routes import trigger_live_reconciliation
        res = trigger_live_reconciliation()
        self.assertIn("success", res)
        self.assertIn("timestamp", res)

    def test_live_status_endpoint_sanitization(self):
        from backend.application.broker_routes import get_live_status
        status_info = get_live_status()

        self.assertIn("is_live_enabled_in_env", status_info)
        self.assertIn("is_armed", status_info)
        self.assertIn("recovery_engine", status_info)
        self.assertIn("order_tracker", status_info)
        self.assertIn("reconciliation", status_info)
        self.assertIn("account_sync", status_info)

        # Ensure zero credentials or secret tokens are leaked
        serialized = str(status_info)
        self.assertNotIn("access_token", serialized.lower())
        self.assertNotIn("client_id", serialized.lower())
        self.assertNotIn("dhan_access_token", serialized.lower())


if __name__ == "__main__":
    unittest.main()
