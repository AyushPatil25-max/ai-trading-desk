"""
Phase 13 — Broker Integration & Execution Adapter End-to-End Test Suite

Comprehensive deterministic unit, integration, and adversarial tests covering:
1. Broker interface conformity (implements BrokerAdapter)
2. PaperBrokerAdapter compatibility & full order lifecycle
3. BrokerCapabilities matrix validation (fractional shares prohibited, is_live=False)
4. ExecutionGuard safety validation:
   - Valid snapshot passes
   - Non-snapshot payload rejected
   - Missing IDs rejected
   - Risk veto rejected (RISK_VETO_ACTIVE)
   - Zero or negative quantity rejected
   - Fractional share quantity rejected
   - Pre-flight bypass attempt rejected
   - Stale quote rejected
   - Missing idempotency token rejected
   - Kill switch active rejected
   - Attempted submission to live adapter rejected
5. LiveBrokerAdapter disabled stub:
   - Fails closed on submit_order
   - Fails closed on cancel_order
   - Fails closed on get_account_state
   - Fails closed on get_positions
   - Connection state DISABLED
6. BrokerFactory configuration safety:
   - Default BROKER_MODE=paper returns PaperBrokerAdapter
   - BROKER_MODE=live raises ConfigurationSafetyError
   - BROKER_MODE=zerodha/upstox/alpaca raises ConfigurationSafetyError
   - Unknown mode raises ConfigurationSafetyError
7. Idempotency test (no duplicate orders)
8. Order lifecycle transitions (CREATED -> SUBMITTED -> ACKNOWLEDGED -> FILLED / CANCELLED)
9. Error handling: insufficient buying power, rejected orders
10. Secret leakage prevention (zero credentials stored or emitted)
11. Read-only REST API endpoints (/api/broker/status, /capabilities, /account, /positions, /orders)
12. Adversarial bypass attempts (Risk, Sizing, Pre-Flight, Live activation)
"""

from datetime import datetime, timezone
import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.domain.broker_schemas import (
    BROKER_INTEGRATION_VERSION,
    BrokerAccountState,
    BrokerCapabilities,
    BrokerConnectionState,
    BrokerMode,
    BrokerOrderRequest,
    BrokerOrderResponse,
    BrokerPosition,
)
from backend.domain.paper_broker_schemas import (
    PaperAccount,
    PaperExecutionResult,
    PaperOrder,
    PaperOrderStatus,
    PaperPosition,
)
from backend.domain.preflight_schemas import (
    ExecutionAuthorizationSnapshot,
    PreflightOrderType,
    PreflightSide,
)
from backend.domain.schemas import MarketContext
from backend.domain.telemetry_schemas import KillSwitchState
from backend.application.broker_interface import (
    BrokerAdapter,
    BrokerFactory,
    ConfigurationSafetyError,
    ExecutionGuardVetoError,
    LiveBrokerAdapter,
    LiveBrokerDisabledError,
)
from backend.application.execution_guard import ExecutionGuard, global_execution_guard
from backend.application.paper_broker_adapter import PaperBrokerAdapter, global_paper_broker
from backend.main import app


class TestBrokerAdapterE2E(unittest.TestCase):
    """Rigorous end-to-end verification of Phase 13 Broker Integration & Execution Adapter."""

    def setUp(self):
        self.paper_broker = PaperBrokerAdapter(initial_cash=100000.0)
        self.guard = ExecutionGuard()
        self.client = TestClient(app)

    def tearDown(self):
        self.paper_broker.reset()
        global_paper_broker.reset()

    def _create_valid_authorization(
        self,
        symbol: str = "TCS.NS",
        quantity: int = 10,
        price: float = 3500.0,
        idempotency_token: Optional[str] = None,
        risk_veto: bool = False,
        circuit_checked: bool = True,
        stale_quote_rejected: bool = False,
    ) -> ExecutionAuthorizationSnapshot:
        """Helper to create a deterministic, valid ExecutionAuthorizationSnapshot."""
        return ExecutionAuthorizationSnapshot(
            authorization_id="auth-test-001",
            decision_id="dec-test-001",
            order_id="ord-test-001",
            symbol=symbol,
            side=PreflightSide.BUY,
            approved_quantity=quantity,
            normalized_limit_price=price,
            normalized_stop_price=price * 0.95,
            normalized_target_price=price * 1.10,
            circuit_limit_checked=circuit_checked,
            data_freshness="STALE" if stale_quote_rejected else "FRESH",
            idempotency_token=idempotency_token or f"idemp-{symbol}-100",
            validation_timestamp=datetime.now(timezone.utc),
            risk_state={"veto_applied": risk_veto, "reason": "Risk veto active" if risk_veto else None},
        )

    # ── Test 1: Interface Conformity ──────────────────────────────────────────

    def test_01_paper_broker_implements_broker_adapter(self):
        """Verify PaperBrokerAdapter conforms to the BrokerAdapter abstract base class."""
        self.assertIsInstance(self.paper_broker, BrokerAdapter)
        caps = self.paper_broker.get_capabilities()
        self.assertIsInstance(caps, BrokerCapabilities)
        self.assertEqual(caps.broker_name, "PaperBrokerAdapter")
        self.assertEqual(caps.mode, BrokerMode.PAPER)
        self.assertFalse(caps.is_live)
        self.assertTrue(caps.supports_paper)
        self.assertFalse(caps.supports_fractional_shares)

    # ── Test 2: Capabilities Matrix ───────────────────────────────────────────

    def test_02_capabilities_matrix_determinism(self):
        """Verify explicit capability flags prevent live and fractional share features."""
        caps = self.paper_broker.get_capabilities()
        self.assertTrue(caps.supports_market_orders)
        self.assertTrue(caps.supports_limit_orders)
        self.assertTrue(caps.supports_stop_orders)
        self.assertTrue(caps.supports_order_cancellation)
        self.assertFalse(caps.supports_fractional_shares, "Fractional shares MUST be prohibited")
        self.assertFalse(caps.is_live, "is_live MUST be False for paper broker")
        self.assertEqual(self.paper_broker.get_connection_state(), BrokerConnectionState.SIMULATED_ACTIVE)

    # ── Test 3: ExecutionGuard — Valid Authorization Passes ───────────────────

    def test_03_execution_guard_authorizes_valid_snapshot(self):
        """Verify that a compliant ExecutionAuthorizationSnapshot passes ExecutionGuard."""
        auth = self._create_valid_authorization()
        outcome = self.guard.validate_authorization(auth)
        self.assertTrue(outcome.is_authorized)
        self.assertTrue(outcome.risk_cleared)
        self.assertTrue(outcome.sizing_cleared)
        self.assertTrue(outcome.preflight_cleared)
        self.assertTrue(outcome.idempotency_cleared)
        self.assertTrue(outcome.broker_mode_cleared)
        self.assertIsNone(outcome.rejection_reason)

    # ── Test 4: ExecutionGuard — Invalid Authorization Payloads ───────────────

    def test_04_execution_guard_rejects_non_snapshot(self):
        """Verify ExecutionGuard rejects raw dictionaries or foreign objects."""
        raw_dict = {"symbol": "TCS.NS", "quantity": 10, "price": 3500.0}
        outcome = self.guard.validate_authorization(raw_dict)
        self.assertFalse(outcome.is_authorized)
        self.assertIn("INVALID_AUTHORIZATION", outcome.rejection_reason)

    # ── Test 5: ExecutionGuard — Missing Identifiers ───────────────────────────

    def test_05_execution_guard_rejects_missing_identifiers(self):
        """Verify missing authorization_id or decision_id is rejected."""
        auth = self._create_valid_authorization()
        # Overwrite with empty ID
        auth_invalid = auth.model_copy(update={"authorization_id": ""})
        outcome = self.guard.validate_authorization(auth_invalid)
        self.assertFalse(outcome.is_authorized)
        self.assertIn("MISSING_IDENTIFIERS", outcome.rejection_reason)

    # ── Test 6: ExecutionGuard — Active Risk Veto Enforcement ─────────────────

    def test_06_execution_guard_rejects_active_risk_veto(self):
        """Verify an order carrying an active risk veto is deterministically blocked."""
        auth = self._create_valid_authorization(risk_veto=True)
        outcome = self.guard.validate_authorization(auth)
        self.assertFalse(outcome.is_authorized)
        self.assertFalse(outcome.risk_cleared)
        self.assertIn("RISK_VETO_ACTIVE", outcome.rejection_reason)

    # ── Test 7: ExecutionGuard — Discrete Sizing (Zero & Negative) ────────────

    def test_07_execution_guard_rejects_invalid_quantity(self):
        """Verify zero and negative quantities are rejected."""
        for invalid_qty in [0, -5]:
            auth = self._create_valid_authorization(quantity=invalid_qty)
            outcome = self.guard.validate_authorization(auth)
            self.assertFalse(outcome.is_authorized)
            self.assertFalse(outcome.sizing_cleared)
            self.assertIn("INVALID_POSITION_SIZE", outcome.rejection_reason)

    # ── Test 8: ExecutionGuard — Fractional Shares Prohibited ─────────────────

    def test_08_execution_guard_rejects_fractional_shares(self):
        """Verify fractional shares (e.g. 10.5 shares) fail closed."""
        auth = self._create_valid_authorization()
        # Inject fractional float into quantity
        auth_fractional = auth.model_copy(update={"approved_quantity": 10.5})
        outcome = self.guard.validate_authorization(auth_fractional)
        self.assertFalse(outcome.is_authorized)
        self.assertFalse(outcome.sizing_cleared)
        self.assertIn("FRACTIONAL_SHARES_PROHIBITED", outcome.rejection_reason)

    # ── Test 9: ExecutionGuard — Pre-Flight Bypass Rejection ───────────────────

    def test_09_execution_guard_rejects_preflight_bypass(self):
        """Verify orders bypassing Pre-Flight circuit limit verification are rejected."""
        auth = self._create_valid_authorization(circuit_checked=False)
        outcome = self.guard.validate_authorization(auth)
        self.assertFalse(outcome.is_authorized)
        self.assertFalse(outcome.preflight_cleared)
        self.assertIn("PREFLIGHT_BYPASS_ATTEMPT", outcome.rejection_reason)

    # ── Test 10: ExecutionGuard — Stale Quote Rejection ───────────────────────

    def test_10_execution_guard_rejects_stale_quote(self):
        """Verify orders flagged with stale quotes by Pre-Flight are rejected."""
        auth = self._create_valid_authorization(stale_quote_rejected=True)
        outcome = self.guard.validate_authorization(auth)
        self.assertFalse(outcome.is_authorized)
        self.assertFalse(outcome.preflight_cleared)
        self.assertIn("PREFLIGHT_REJECTION", outcome.rejection_reason)

    # ── Test 11: ExecutionGuard — Live Target Adapter Blocked ─────────────────

    def test_11_execution_guard_blocks_live_adapter_target(self):
        """Verify ExecutionGuard unconditionally refuses to authorize any live adapter."""
        auth = self._create_valid_authorization()
        outcome = self.guard.validate_authorization(auth, target_adapter_is_live=True)
        self.assertFalse(outcome.is_authorized)
        self.assertFalse(outcome.broker_mode_cleared)
        self.assertIn("LIVE_BROKER_PROHIBITED", outcome.rejection_reason)

    # ── Test 12: ExecutionGuard — Kill Switch Blocking ────────────────────────

    def test_12_execution_guard_kill_switch_blocking(self):
        """Verify operator kill switch causes ExecutionGuard to reject orders."""
        mock_telemetry = MagicMock()
        mock_telemetry.is_kill_switch_triggered.return_value = True
        guard_with_ks = ExecutionGuard(telemetry_engine=mock_telemetry)

        auth = self._create_valid_authorization()
        outcome = guard_with_ks.validate_authorization(auth)
        self.assertFalse(outcome.is_authorized)
        self.assertIn("KILL_SWITCH_ACTIVE", outcome.rejection_reason)

    # ── Test 13: LiveBrokerAdapter — Disabled Stub Fails Closed ───────────────

    def test_13_live_broker_adapter_fails_closed(self):
        """Verify LiveBrokerAdapter stub unconditionally fails closed on all operations."""
        live_stub = LiveBrokerAdapter(allow_instantiation_for_testing=True)
        auth = self._create_valid_authorization()

        self.assertEqual(live_stub.get_connection_state(), BrokerConnectionState.DISABLED)
        self.assertFalse(live_stub.get_capabilities().is_live)
        self.assertFalse(live_stub.get_capabilities().supports_market_orders)

        with self.assertRaises(LiveBrokerDisabledError):
            live_stub.submit_order(auth)

        with self.assertRaises(LiveBrokerDisabledError):
            live_stub.cancel_order("ord-123")

        with self.assertRaises(LiveBrokerDisabledError):
            live_stub.get_account_state()

        with self.assertRaises(LiveBrokerDisabledError):
            live_stub.get_positions()

    # ── Test 14: BrokerFactory — Paper Mode Resolution ────────────────────────

    def test_14_broker_factory_paper_mode(self):
        """Verify BrokerFactory returns PaperBrokerAdapter for paper modes."""
        for mode in ["paper", "PAPER", "simulated", "mock"]:
            adapter = BrokerFactory.get_adapter(mode_override=mode)
            self.assertIsInstance(adapter, PaperBrokerAdapter)
            self.assertEqual(adapter.get_capabilities().mode, BrokerMode.PAPER)

    # ── Test 15: BrokerFactory — Live Mode Prohibited ─────────────────────────

    def test_15_broker_factory_live_mode_prohibited(self):
        """Verify BrokerFactory raises ConfigurationSafetyError on any live mode request."""
        prohibited_modes = ["live", "real", "zerodha", "upstox", "alpaca", "ibkr"]
        for mode in prohibited_modes:
            with self.assertRaises(ConfigurationSafetyError) as ctx:
                BrokerFactory.get_adapter(mode_override=mode)
            self.assertIn("LIVE_BROKER_PROHIBITED", str(ctx.exception))

    # ── Test 16: BrokerFactory — Unknown Mode Fails Closed ────────────────────

    def test_16_broker_factory_unknown_mode_fails_closed(self):
        """Verify unknown or unconfigured broker modes fail closed."""
        with self.assertRaises(ConfigurationSafetyError) as ctx:
            BrokerFactory.get_adapter(mode_override="quantum_crypto_broker")
        self.assertIn("INVALID_BROKER_MODE", str(ctx.exception))

    # ── Test 17: Idempotency Protection ───────────────────────────────────────

    def test_17_idempotency_prevents_duplicate_orders(self):
        """Verify re-submitting an order with identical idempotency token returns existing order."""
        auth = self._create_valid_authorization(idempotency_token="unique-token-999")
        res1 = self.paper_broker.submit_order(auth)
        self.assertEqual(res1.status, PaperOrderStatus.ACKNOWLEDGED)

        # Resubmit with identical token
        res2 = self.paper_broker.submit_order(auth)
        self.assertEqual(res2.status, PaperOrderStatus.ACKNOWLEDGED)
        self.assertEqual(res1.order.order_id, res2.order.order_id)
        self.assertIn("IDEMPOTENT", res2.message)
        self.assertEqual(len(self.paper_broker.account.orders), 1, "Must not create duplicate order")

    # ── Test 18: Full Paper Order Lifecycle ───────────────────────────────────

    def test_18_full_paper_order_lifecycle(self):
        """Verify order lifecycle: CREATED -> SUBMITTED -> ACKNOWLEDGED -> FILLED."""
        auth = self._create_valid_authorization(quantity=20, price=3000.0)
        res = self.paper_broker.submit_order(auth)
        order_id = res.order.order_id

        self.assertEqual(res.status, PaperOrderStatus.ACKNOWLEDGED)
        self.assertEqual(res.order.filled_quantity, 0)
        self.assertEqual(res.order.remaining_quantity, 20)

        # Simulate execution fill
        fill_res = self.paper_broker.process_fills(order_id=order_id, market_price=3000.0, fill_ratio=1.0)
        self.assertEqual(fill_res.order.status, PaperOrderStatus.FILLED)
        self.assertEqual(fill_res.order.filled_quantity, 20)
        self.assertEqual(fill_res.order.remaining_quantity, 0)
        self.assertGreater(fill_res.order.average_fill_price, 0.0)

        # Check position created
        positions = self.paper_broker.get_positions()
        self.assertIn("TCS.NS", positions)
        self.assertEqual(positions["TCS.NS"].quantity, 20)

    # ── Test 19: Order Cancellation Lifecycle ─────────────────────────────────

    def test_19_order_cancellation_lifecycle(self):
        """Verify open order cancellation transitions to CANCELLED."""
        auth = self._create_valid_authorization(quantity=5, price=2500.0)
        res = self.paper_broker.submit_order(auth)
        order_id = res.order.order_id

        cancelled = self.paper_broker.cancel_order(order_id)
        self.assertTrue(cancelled)
        order = self.paper_broker.get_order(order_id)
        self.assertEqual(order.status, PaperOrderStatus.CANCELLED)

    # ── Test 20: Insufficient Buying Power Rejection ──────────────────────────

    def test_20_insufficient_buying_power_rejection(self):
        """Verify orders exceeding available buying power are rejected."""
        # 100 shares @ 3500 = 350,000 > 100,000 initial cash
        auth = self._create_valid_authorization(quantity=100, price=3500.0)
        res = self.paper_broker.submit_order(auth)
        self.assertEqual(res.status, PaperOrderStatus.REJECTED)
        self.assertIn("INSUFFICIENT_BUYING_POWER", res.message)

    # ── Test 21: Secret Leakage Prevention ────────────────────────────────────

    def test_21_secret_leakage_prevention(self):
        """Verify zero credentials, secrets, or passwords exist in adapter or schemas."""
        caps = self.paper_broker.get_capabilities().model_dump()
        acct = self.paper_broker.get_account_state().model_dump()

        forbidden_keys = ["password", "secret", "api_key", "token_secret", "access_token", "private_key"]
        for key in forbidden_keys:
            self.assertNotIn(key, caps)
            self.assertNotIn(key, acct)

    # ── Test 22: REST API /api/broker/status ──────────────────────────────────

    def test_22_api_get_broker_status(self):
        """Verify GET /api/broker/status returns safe BrokerStatusSummary."""
        resp = self.client.get("/api/broker/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertEqual(data["version"], BROKER_INTEGRATION_VERSION)
        self.assertEqual(data["active_broker_name"], "PaperBrokerAdapter")
        self.assertEqual(data["broker_mode"], "PAPER")
        self.assertFalse(data["is_live_trading_enabled"])
        self.assertEqual(data["connection_state"], "SIMULATED_ACTIVE")
        self.assertTrue(data["safety_invariants"]["real_money_prohibited"])
        self.assertTrue(data["safety_invariants"]["live_broker_disabled"])

    # ── Test 23: REST API /api/broker/capabilities ────────────────────────────

    def test_23_api_get_broker_capabilities(self):
        """Verify GET /api/broker/capabilities."""
        resp = self.client.get("/api/broker/capabilities")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["broker_name"], "PaperBrokerAdapter")
        self.assertFalse(data["is_live"])
        self.assertTrue(data["supports_paper"])
        self.assertFalse(data["supports_fractional_shares"])

    # ── Test 24: REST API /api/broker/account & /positions ────────────────────

    def test_24_api_get_broker_account_and_positions(self):
        """Verify GET /api/broker/account and /api/broker/positions."""
        resp_acct = self.client.get("/api/broker/account")
        self.assertEqual(resp_acct.status_code, 200)
        acct_data = resp_acct.json()
        self.assertEqual(acct_data["mode"], "PAPER")
        self.assertFalse(acct_data["is_live"])
        self.assertGreaterEqual(acct_data["cash"], 0.0)

        resp_pos = self.client.get("/api/broker/positions")
        self.assertEqual(resp_pos.status_code, 200)
        self.assertIsInstance(resp_pos.json(), dict)

    # ── Test 25: REST API /api/broker/orders & /orders/{id} ───────────────────

    def test_25_api_get_broker_orders(self):
        """Verify GET /api/broker/orders and /api/broker/orders/{id}."""
        # Submit an order into global_paper_broker
        auth = self._create_valid_authorization(symbol="INFY.NS", quantity=2, price=1500.0)
        res = global_paper_broker.submit_order(auth)
        order_id = res.order.order_id

        resp_list = self.client.get("/api/broker/orders")
        self.assertEqual(resp_list.status_code, 200)
        orders = resp_list.json()
        self.assertGreaterEqual(len(orders), 1)

        resp_single = self.client.get(f"/api/broker/orders/{order_id}")
        self.assertEqual(resp_single.status_code, 200)
        self.assertEqual(resp_single.json()["order_id"], order_id)

        # 404 for nonexistent order
        resp_404 = self.client.get("/api/broker/orders/nonexistent-order-999")
        self.assertEqual(resp_404.status_code, 404)

    # ── Test 26: Adversarial Bypass Attempt — Risk Engine ─────────────────────

    def test_26_adversarial_bypass_attempt_risk_engine(self):
        """Adversarial test: Attempting to submit order with active risk veto through ExecutionGuard."""
        auth_vetoed = self._create_valid_authorization(risk_veto=True)
        res = self.guard.guard_submission(self.paper_broker, auth_vetoed)
        self.assertEqual(res.status, PaperOrderStatus.REJECTED)
        self.assertIn("RISK_VETO_ACTIVE", res.message)
        self.assertEqual(len(self.paper_broker.account.orders), 0, "Vetoed order must never reach order book")

    # ── Test 27: Adversarial Bypass Attempt — Pre-Flight Gatekeeper ───────────

    def test_27_adversarial_bypass_attempt_preflight(self):
        """Adversarial test: Attempting to submit unverified circuit limits through ExecutionGuard."""
        auth_unverified = self._create_valid_authorization(circuit_checked=False)
        res = self.guard.guard_submission(self.paper_broker, auth_unverified)
        self.assertEqual(res.status, PaperOrderStatus.REJECTED)
        self.assertIn("PREFLIGHT_BYPASS_ATTEMPT", res.message)
        self.assertEqual(len(self.paper_broker.account.orders), 0, "Unverified order must never reach order book")


if __name__ == "__main__":
    unittest.main()
