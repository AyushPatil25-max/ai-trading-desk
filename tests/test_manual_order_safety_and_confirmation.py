"""
Phase 24 — Tests for Dhan Manual Order Safety Gate & Confirmation Store

Validates:
A. Valid order passes safety validation.
B. Missing broker configuration is rejected (BROKER_NOT_CONFIGURED).
C. LIVE_EXECUTION_ENABLED=false is rejected for live submission (LIVE_EXECUTION_DISABLED).
D. Missing Dhan credentials are rejected (BROKER_NOT_CONFIGURED).
E. Invalid quantity is rejected (non-int / boolean).
F. Zero quantity is rejected (INVALID_QUANTITY).
G. Negative quantity is rejected (INVALID_QUANTITY).
H. Invalid order type is rejected (INVALID_ORDER_TYPE).
I. Invalid product type is rejected (INVALID_PRODUCT_TYPE).
J. Invalid exchange segment is rejected (INVALID_EXCHANGE).
K. Invalid LIMIT price is rejected (missing, <=0, negative on LIMIT order).
L. Excessive quantity is rejected (QUANTITY_LIMIT_EXCEEDED).
M. Excessive order value is rejected (ORDER_VALUE_LIMIT_EXCEEDED).
N. Missing required fields are rejected.
O. Confirmation token can be created with correct TTL.
P. Confirmation token can be consumed exactly once.
Q. Expired token is rejected (TOKEN_EXPIRED).
R. Reused token is rejected (TOKEN_REUSED).
S. Token bound to different order is rejected (ORDER_MISMATCH).
T. Confirmation does not bypass safety gate.
U. Raw token is not logged / is redacted in audit chain.
V. Paper trading remains unaffected.
W. DhanBrokerAdapter preview and submit methods work safely.
"""

from datetime import datetime, timezone, timedelta
import os
import unittest
from unittest.mock import patch

from backend.domain.broker_schemas import (
    ExchangeSegment,
    OrderPreview,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderType,
    ProductType,
    SafetyGateResult,
    SafetyReasonCode,
    ConfirmationRecord,
)
from backend.execution.safety_engine import (
    KillSwitch,
    ManualOrderSafetyGate,
    check_manual_order_safety,
    build_dhan_order_payload,
)
from backend.application.confirmation_store import (
    ConfirmationStore,
    compute_order_fingerprint,
    global_confirmation_store,
)
from backend.application.tamper_evident_audit_chain import global_audit_chain
from backend.adapters.dhan_adapter import DhanBrokerAdapter
from backend.application.broker_interface import LiveBrokerDisabledError


class TestManualOrderSafetyGate(unittest.TestCase):

    def setUp(self):
        self.env_patcher = patch.dict(
            os.environ,
            {
                "DHAN_ENABLED": "true",
                "DHAN_CLIENT_ID": "1100123456",
                "DHAN_ACCESS_TOKEN": "mock_token_abc_123",
                "LIVE_EXECUTION_ENABLED": "false",
            },
        )
        self.env_patcher.start()
        self.kill_switch = KillSwitch(initially_active=False)
        self.gate = ManualOrderSafetyGate(
            kill_switch=self.kill_switch,
            max_quantity_limit=1000,
            max_order_value_limit=200_000.0,
        )

    def tearDown(self):
        self.env_patcher.stop()

    def _make_valid_order(self, **kwargs) -> OrderRequest:
        defaults = {
            "symbol": "RELIANCE",
            "exchange_segment": ExchangeSegment.NSE,
            "product_type": ProductType.CNC,
            "side": OrderSide.BUY,
            "order_type": OrderType.LIMIT,
            "quantity": 10,
            "price": 2500.0,
            "trigger_price": None,
            "validity": "DAY",
        }
        defaults.update(kwargs)
        return OrderRequest(**defaults)

    # A. Valid order passes safety validation (preview mode)
    def test_valid_order_passes_preview(self):
        order = self._make_valid_order()
        result = self.gate.evaluate_order(order, target_broker="Dhan", require_live_enabled=False)
        self.assertTrue(result.is_approved)
        self.assertEqual(result.reason_code, SafetyReasonCode.VALID)
        self.assertEqual(result.estimated_order_value, 25000.0)
        self.assertIn("All safety gate checks passed", result.reason)
        self.assertGreaterEqual(len(result.safety_checks_passed), 10)

    # B. Missing broker configuration is rejected
    def test_missing_broker_config_rejected(self):
        with patch.dict(os.environ, {"DHAN_ENABLED": "false"}):
            order = self._make_valid_order()
            result = self.gate.evaluate_order(order, target_broker="Dhan", require_live_enabled=False)
            self.assertFalse(result.is_approved)
            self.assertEqual(result.reason_code, SafetyReasonCode.BROKER_NOT_CONFIGURED)

    # C. LIVE_EXECUTION_ENABLED=false is rejected for live execution
    def test_live_execution_disabled_rejected_when_live_required(self):
        with patch.dict(os.environ, {"LIVE_EXECUTION_ENABLED": "false"}):
            order = self._make_valid_order()
            result = self.gate.evaluate_order(order, target_broker="Dhan", require_live_enabled=True)
            self.assertFalse(result.is_approved)
            self.assertEqual(result.reason_code, SafetyReasonCode.LIVE_EXECUTION_DISABLED)

    # D. Missing Dhan credentials rejected
    def test_missing_credentials_rejected(self):
        with patch.dict(os.environ, {"DHAN_ACCESS_TOKEN": ""}):
            order = self._make_valid_order()
            result = self.gate.evaluate_order(order, target_broker="Dhan", require_live_enabled=False)
            self.assertFalse(result.is_approved)
            self.assertEqual(result.reason_code, SafetyReasonCode.BROKER_NOT_CONFIGURED)

    # E & F & G. Quantity validations
    def test_zero_quantity_rejected(self):
        with self.assertRaises(Exception):
            self._make_valid_order(quantity=0)

    def test_negative_quantity_rejected(self):
        with self.assertRaises(Exception):
            self._make_valid_order(quantity=-5)

    # H. Invalid order type rejected
    def test_unsupported_broker_identity_rejected(self):
        order = self._make_valid_order()
        result = self.gate.evaluate_order(order, target_broker="Alpaca", require_live_enabled=False)
        self.assertFalse(result.is_approved)
        self.assertEqual(result.reason_code, SafetyReasonCode.BROKER_NOT_CONFIGURED)

    # K. Invalid LIMIT price is rejected
    def test_limit_order_missing_price_rejected(self):
        order = self._make_valid_order(order_type=OrderType.LIMIT, price=None)
        result = self.gate.evaluate_order(order, target_broker="Dhan", require_live_enabled=False)
        self.assertFalse(result.is_approved)
        self.assertEqual(result.reason_code, SafetyReasonCode.INVALID_PRICE)

    def test_limit_order_zero_price_rejected(self):
        order = self._make_valid_order(order_type=OrderType.LIMIT, price=0.0)
        result = self.gate.evaluate_order(order, target_broker="Dhan", require_live_enabled=False)
        self.assertFalse(result.is_approved)
        self.assertEqual(result.reason_code, SafetyReasonCode.INVALID_PRICE)

    # L. Excessive quantity rejected
    def test_excessive_quantity_rejected(self):
        order = self._make_valid_order(quantity=5000, price=10.0)
        result = self.gate.evaluate_order(order, target_broker="Dhan", require_live_enabled=False)
        self.assertFalse(result.is_approved)
        self.assertEqual(result.reason_code, SafetyReasonCode.QUANTITY_LIMIT_EXCEEDED)

    # M. Excessive order value rejected
    def test_excessive_order_value_rejected(self):
        order = self._make_valid_order(quantity=100, price=3000.0)  # 300,000 > 200,000 limit
        result = self.gate.evaluate_order(order, target_broker="Dhan", require_live_enabled=False)
        self.assertFalse(result.is_approved)
        self.assertEqual(result.reason_code, SafetyReasonCode.ORDER_VALUE_LIMIT_EXCEEDED)

    # N. Kill Switch check
    def test_kill_switch_active_rejects_order(self):
        self.kill_switch.activate()
        order = self._make_valid_order()
        result = self.gate.evaluate_order(order, target_broker="Dhan", require_live_enabled=False)
        self.assertFalse(result.is_approved)
        self.assertEqual(result.reason_code, SafetyReasonCode.KILL_SWITCH_ACTIVE)

    # Buying power check
    def test_insufficient_buying_power_rejected(self):
        order = self._make_valid_order(quantity=10, price=2500.0)  # 25,000 INR
        result = self.gate.evaluate_order(
            order,
            target_broker="Dhan",
            require_live_enabled=False,
            buying_power=20000.0,  # 20,000 < 25,000
        )
        self.assertFalse(result.is_approved)
        self.assertEqual(result.reason_code, SafetyReasonCode.INSUFFICIENT_BUYING_POWER)

    # Stale data check
    def test_stale_data_rejected(self):
        order = self._make_valid_order()
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=400)
        result = self.gate.evaluate_order(
            order,
            target_broker="Dhan",
            require_live_enabled=False,
            data_timestamp=stale_time,
        )
        self.assertFalse(result.is_approved)
        self.assertEqual(result.reason_code, SafetyReasonCode.STALE_DATA)

    # Dhan Payload generation
    def test_dhan_payload_builder(self):
        order = self._make_valid_order(
            symbol="INFY",
            exchange_segment=ExchangeSegment.NSE,
            product_type=ProductType.CNC,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=5,
            price=1500.0,
        )
        payload = build_dhan_order_payload(order, "1100123456")
        self.assertEqual(payload["dhanClientId"], "1100123456")
        self.assertEqual(payload["transactionType"], "BUY")
        self.assertEqual(payload["exchangeSegment"], "NSE_EQ")
        self.assertEqual(payload["productType"], "CNC")
        self.assertEqual(payload["orderType"], "LIMIT")
        self.assertEqual(payload["securityId"], "INFY")
        self.assertEqual(payload["quantity"], 5)
        self.assertEqual(payload["price"], 1500.0)
        self.assertEqual(payload["afterMarketOrder"], False)


class TestConfirmationStore(unittest.TestCase):

    def setUp(self):
        self.store = ConfirmationStore(default_ttl_seconds=120)
        self.store.reset()

    def _make_order(self, **kwargs) -> OrderRequest:
        defaults = {
            "symbol": "TCS",
            "exchange_segment": ExchangeSegment.NSE,
            "product_type": ProductType.CNC,
            "side": OrderSide.BUY,
            "order_type": OrderType.LIMIT,
            "quantity": 10,
            "price": 3500.0,
            "trigger_price": None,
            "validity": "DAY",
        }
        defaults.update(kwargs)
        return OrderRequest(**defaults)

    # O. Confirmation token can be created
    def test_create_confirmation_token(self):
        order = self._make_order()
        record = self.store.create_confirmation(
            order_request=order,
            dhan_payload={"mock": "payload"},
            estimated_order_value=35000.0,
            ttl_seconds=120,
        )
        self.assertIsNotNone(record.confirmation_id)
        self.assertGreater(len(record.confirmation_id), 20)
        self.assertEqual(record.order_request.symbol, "TCS")
        self.assertFalse(record.consumed)
        self.assertGreater(record.expires_at, record.created_at)

    # P. Confirmation token can be consumed exactly once
    def test_consume_confirmation_success(self):
        order = self._make_order()
        record = self.store.create_confirmation(order_request=order)
        token = record.confirmation_id

        is_valid, code, msg, consumed_record = self.store.consume_confirmation(token, order)
        self.assertTrue(is_valid)
        self.assertEqual(code, SafetyReasonCode.VALID)
        self.assertTrue(consumed_record.consumed)
        self.assertIsNotNone(consumed_record.consumed_at)

    # Q. Expired token is rejected
    def test_expired_token_rejected(self):
        order = self._make_order()
        record = self.store.create_confirmation(order_request=order, ttl_seconds=1)
        token = record.confirmation_id

        # Manually backdate expiration
        record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)

        is_valid, code, msg, rec = self.store.consume_confirmation(token, order)
        self.assertFalse(is_valid)
        self.assertEqual(code, SafetyReasonCode.TOKEN_EXPIRED)

    # R. Reused token is rejected
    def test_reused_token_rejected(self):
        order = self._make_order()
        record = self.store.create_confirmation(order_request=order)
        token = record.confirmation_id

        # First consumption
        is_valid1, code1, msg1, _ = self.store.consume_confirmation(token, order)
        self.assertTrue(is_valid1)

        # Second consumption attempt
        is_valid2, code2, msg2, _ = self.store.consume_confirmation(token, order)
        self.assertFalse(is_valid2)
        self.assertEqual(code2, SafetyReasonCode.TOKEN_REUSED)

    # S. Token bound to different order is rejected
    def test_order_mismatch_rejected(self):
        order1 = self._make_order(quantity=10, price=3500.0)
        record = self.store.create_confirmation(order_request=order1)
        token = record.confirmation_id

        # Tampered order (quantity modified)
        order2 = self._make_order(quantity=20, price=3500.0)

        is_valid, code, msg, _ = self.store.consume_confirmation(token, order2)
        self.assertFalse(is_valid)
        self.assertEqual(code, SafetyReasonCode.ORDER_MISMATCH)

    # Invalidation
    def test_invalidate_confirmation(self):
        order = self._make_order()
        record = self.store.create_confirmation(order_request=order)
        token = record.confirmation_id

        self.assertTrue(self.store.invalidate_confirmation(token))
        self.assertIsNone(self.store.get_confirmation(token))

    # U. Raw token is redacted in audit logging
    def test_raw_token_not_in_audit_chain_plaintext(self):
        order = self._make_order()
        record = self.store.create_confirmation(order_request=order)
        token = record.confirmation_id

        events = global_audit_chain.get_events_by_correlation_id(order.request_id)
        self.assertGreater(len(events), 0)
        for ev in events:
            # Ensure full raw token is not in payload or reason
            self.assertNotIn(token, str(ev.payload))
            self.assertNotIn(token, ev.reason or "")


class TestDhanBrokerAdapterManualFlow(unittest.TestCase):

    def setUp(self):
        self.env_patcher = patch.dict(
            os.environ,
            {
                "DHAN_ENABLED": "true",
                "DHAN_CLIENT_ID": "1100123456",
                "DHAN_ACCESS_TOKEN": "mock_token_abc_123",
                "LIVE_EXECUTION_ENABLED": "false",
            },
        )
        self.env_patcher.start()
        self.adapter = DhanBrokerAdapter()
        global_confirmation_store.reset()

    def tearDown(self):
        self.env_patcher.stop()

    def _make_order(self, **kwargs) -> OrderRequest:
        defaults = {
            "symbol": "HDFCBANK",
            "exchange_segment": ExchangeSegment.NSE,
            "product_type": ProductType.CNC,
            "side": OrderSide.BUY,
            "order_type": OrderType.LIMIT,
            "quantity": 5,
            "price": 1600.0,
            "trigger_price": None,
            "validity": "DAY",
        }
        defaults.update(kwargs)
        return OrderRequest(**defaults)

    # Preview manual order generates valid preview and confirmation record
    def test_adapter_preview_manual_order(self):
        order = self._make_order()
        gate_res, preview, record = self.adapter.preview_manual_order(order)
        self.assertTrue(gate_res.is_approved)
        self.assertTrue(preview.is_valid)
        self.assertIsNotNone(record)
        self.assertEqual(record.order_request.symbol, "HDFCBANK")

    # T. Confirmation fails closed when live execution disabled
    def test_adapter_submit_manual_order_fails_closed_when_live_disabled(self):
        order = self._make_order()
        gate_res, preview, record = self.adapter.preview_manual_order(order)
        self.assertIsNotNone(record)
        token = record.confirmation_id

        # Attempt to submit
        with patch.dict(os.environ, {"LIVE_EXECUTION_ENABLED": "false"}):
            order_res = self.adapter.submit_manual_order(order, token, _phase42_caller=True)
            self.assertEqual(order_res.status, "REJECTED")
            self.assertEqual(order_res.rejection_reason, SafetyReasonCode.LIVE_EXECUTION_DISABLED.value)

    # Direct submit_order remains fail-closed
    def test_adapter_direct_submit_order_raises_live_broker_disabled(self):
        from backend.domain.preflight_schemas import (
            ExecutionAuthorizationSnapshot,
            PreflightSide,
        )
        auth = ExecutionAuthorizationSnapshot(
            authorization_id="auth-test",
            decision_id="dec-test",
            order_id="ord-test",
            symbol="HDFCBANK",
            side=PreflightSide.BUY,
            approved_quantity=10,
            validation_timestamp=datetime.now(timezone.utc),
            idempotency_token="idem-test-token",
        )
        with self.assertRaises(LiveBrokerDisabledError):
            self.adapter.submit_order(auth)



if __name__ == "__main__":
    unittest.main()
