"""
Phase 15 — Broker Integration & Sandbox Connectivity Comprehensive End-to-End Test Suite

Verifies all 35 required criteria:
1. Provider selection
2. Environment selection
3. PAPER routing
4. SANDBOX routing
5. LIVE rejection
6. Missing credential handling
7. Credential secrecy
8. Sandbox connectivity
9. Account synchronization
10. Position synchronization
11. Open order synchronization
12. Order submission
13. Order status
14. Cancellation
15. Fill processing
16. Idempotent order submission
17. Timeout handling
18. Authentication failure handling
19. Rate limiting handling
20. Broker unavailable handling
21. Unknown execution state handling
22. Reconciliation report generation
23. Position mismatch detection
24. Order mismatch detection
25. Risk Engine enforcement
26. Position Sizing enforcement
27. Pre-Flight enforcement
28. LLM cannot execute orders
29. Dashboard broker status
30. Telemetry integration
31. Production endpoint usage prohibited
32. Production credentials prohibited
33. LIVE environment remains blocked
34. Existing PaperBrokerAdapter remains functional
35. Phase 1–14 regression compatibility
"""

from datetime import datetime, timezone
import unittest
from fastapi.testclient import TestClient

from backend.domain.broker_schemas import (
    BrokerAccountState,
    BrokerConfig,
    BrokerConnectionState,
    BrokerEnvironment,
    BrokerMode,
    BrokerRoutingMode,
    DiscrepancyType,
    PROHIBITED_PRODUCTION_DOMAINS,
)
from backend.domain.paper_broker_schemas import PaperOrderStatus
from backend.domain.preflight_schemas import (
    ExecutionAuthorizationSnapshot,
    PreflightOrderType,
    PreflightSide,
)
from backend.domain.telemetry_schemas import ExecutionEventType
from backend.application.broker_interface import (
    BrokerFactory,
    ConfigurationSafetyError,
    LiveBrokerDisabledError,
)
from backend.application.broker_manager import BrokerManager, global_broker_manager
from backend.application.broker_reconciliation import (
    BrokerReconciliationEngine,
    global_reconciliation_engine,
)
from backend.application.execution_guard import ExecutionGuard, global_execution_guard
from backend.application.execution_telemetry_engine import ExecutionTelemetryEngine
from backend.application.paper_broker_adapter import PaperBrokerAdapter, global_paper_broker
from backend.application.sandbox_broker_adapter import SandboxBrokerAdapter
from backend.application.sandbox_client import (
    MockSandboxClient,
    RestSandboxClient,
    SandboxAuthenticationError,
    SandboxBrokerUnavailableError,
    SandboxRateLimitError,
    SandboxTimeoutError,
    SandboxUnknownSubmissionStateError,
)
from backend.domain.trading_os_schemas import TradingOSRun
from backend.main import app


class TestBrokerSandboxIntegrationE2E(unittest.TestCase):
    """Full end-to-end verification of Phase 15 Broker Sandbox Integration."""

    def setUp(self):
        self.telemetry = ExecutionTelemetryEngine()
        self.mock_client = MockSandboxClient(initial_cash=100000.0, provider_name="MockSandboxProvider")
        self.sandbox_adapter = SandboxBrokerAdapter(
            client=self.mock_client,
            provider_name="MockSandboxProvider",
            telemetry_engine=self.telemetry,
        )
        self.paper_adapter = PaperBrokerAdapter(initial_cash=100000.0, telemetry_engine=self.telemetry)
        self.guard = ExecutionGuard(telemetry_engine=self.telemetry)
        self.manager = BrokerManager(
            paper_adapter=self.paper_adapter,
            sandbox_adapter=self.sandbox_adapter,
            execution_guard=self.guard,
            telemetry_engine=self.telemetry,
        )
        self.reconciliation = BrokerReconciliationEngine(telemetry_engine=self.telemetry)
        self.client = TestClient(app)

    def _make_valid_auth(
        self,
        symbol: str = "TCS.NS",
        quantity: int = 10,
        token: str = "tok-12345",
        side: PreflightSide = PreflightSide.BUY,
        price: float = 3500.0,
        risk_veto: bool = False,
        circuit_checked: bool = True,
        stale_quote: bool = False,
    ) -> ExecutionAuthorizationSnapshot:
        return ExecutionAuthorizationSnapshot(
            authorization_id="auth-test-001",
            decision_id="dec-test-001",
            order_id="ord-test-001",
            symbol=symbol,
            side=side,
            approved_quantity=quantity,
            normalized_limit_price=price,
            normalized_stop_price=price * 0.95,
            normalized_target_price=price * 1.10,
            circuit_limit_checked=circuit_checked,
            data_freshness="STALE" if stale_quote else "FRESH",
            idempotency_token=token,
            validation_timestamp=datetime.now(timezone.utc),
            risk_state={"veto_applied": risk_veto, "reason": "Portfolio max drawdown reached" if risk_veto else None},
        )

    # 1. Provider selection
    def test_01_provider_selection(self):
        cfg = BrokerConfig(broker_provider="TestCustomProvider", broker_environment=BrokerEnvironment.PAPER)
        self.assertEqual(cfg.broker_provider, "TestCustomProvider")

    # 2. Environment selection
    def test_02_environment_selection(self):
        cfg_paper = BrokerConfig(broker_environment=BrokerEnvironment.PAPER)
        self.assertEqual(cfg_paper.broker_environment, BrokerEnvironment.PAPER)
        cfg_sbx = BrokerConfig(broker_environment=BrokerEnvironment.SANDBOX)
        self.assertEqual(cfg_sbx.broker_environment, BrokerEnvironment.SANDBOX)

    # 3. PAPER routing
    def test_03_paper_routing(self):
        self.manager.configure(BrokerConfig(broker_environment=BrokerEnvironment.PAPER))
        self.assertEqual(self.manager.get_active_environment(), BrokerEnvironment.PAPER)
        self.assertEqual(self.manager.get_routing_mode(), BrokerRoutingMode.INTERNAL_PAPER)
        adapter = self.manager.get_active_adapter()
        self.assertIsInstance(adapter, PaperBrokerAdapter)

    # 4. SANDBOX routing
    def test_04_sandbox_routing(self):
        self.manager.configure(BrokerConfig(broker_environment=BrokerEnvironment.SANDBOX))
        self.assertEqual(self.manager.get_active_environment(), BrokerEnvironment.SANDBOX)
        self.assertEqual(self.manager.get_routing_mode(), BrokerRoutingMode.EXTERNAL_SANDBOX)
        adapter = self.manager.get_active_adapter()
        self.assertIsInstance(adapter, SandboxBrokerAdapter)

    # 5. LIVE rejection
    def test_05_live_rejection(self):
        with self.assertRaises(ValueError) as ctx:
            BrokerConfig(broker_environment=BrokerEnvironment.LIVE)
        self.assertIn("LIVE_BROKER_PROHIBITED", str(ctx.exception))

    # 6. Missing credential handling
    def test_06_missing_credential_handling(self):
        with self.assertRaises(ValueError) as ctx:
            BrokerConfig(
                broker_provider="alpaca_sandbox",
                broker_environment=BrokerEnvironment.SANDBOX,
                api_key=None,
                api_secret=None,
            )
        self.assertIn("MISSING_CREDENTIALS", str(ctx.exception))

    # 7. Credential secrecy
    def test_07_credential_secrecy(self):
        cfg = BrokerConfig(
            broker_provider="mock_sandbox",
            broker_environment=BrokerEnvironment.SANDBOX,
            api_key="super_secret_key_123",
            api_secret="super_secret_token_abc",
        )
        rep = repr(cfg)
        self.assertNotIn("super_secret_key_123", rep)
        self.assertNotIn("super_secret_token_abc", rep)
        self.assertIn("***REDACTED***", rep)

        safe_dict = cfg.to_safe_dict()
        self.assertEqual(safe_dict["api_key"], "***REDACTED***")
        self.assertEqual(safe_dict["api_secret"], "***REDACTED***")

    # 8. Sandbox connectivity
    def test_08_sandbox_connectivity(self):
        self.assertEqual(self.sandbox_adapter.get_connection_state(), BrokerConnectionState.CONNECTED)
        self.mock_client.simulate_auth_failure = True
        self.assertEqual(self.sandbox_adapter.get_connection_state(), BrokerConnectionState.ERROR)
        self.mock_client.simulate_auth_failure = False
        self.mock_client.simulate_unavailable = True
        self.assertEqual(self.sandbox_adapter.get_connection_state(), BrokerConnectionState.DISCONNECTED)

    # 9. Account synchronization
    def test_09_account_synchronization(self):
        acct = self.sandbox_adapter.get_account_state()
        self.assertEqual(acct.mode, BrokerMode.SANDBOX)
        self.assertEqual(acct.cash, 100000.0)
        self.assertEqual(acct.total_equity, 100000.0)
        self.assertFalse(acct.is_live)

    # 10. Position synchronization
    def test_10_position_synchronization(self):
        auth = self._make_valid_auth(symbol="INFY.NS", quantity=5, token="tok-pos-001")
        res = self.sandbox_adapter.submit_order(auth)
        self.assertEqual(res.status, PaperOrderStatus.FILLED)
        positions = self.sandbox_adapter.get_positions()
        self.assertIn("INFY.NS", positions)
        self.assertEqual(positions["INFY.NS"].quantity, 5)

    # 11. Open order synchronization
    def test_11_open_order_synchronization(self):
        auth = self._make_valid_auth(symbol="WIPRO.NS", quantity=10, token="tok-ord-sync")
        res = self.sandbox_adapter.submit_order(auth)
        orders = self.sandbox_adapter.list_orders()
        self.assertGreaterEqual(len(orders), 1)
        found = self.sandbox_adapter.get_order(res.order.order_id)
        self.assertIsNotNone(found)
        self.assertEqual(found.symbol, "WIPRO.NS")

    # 12. Order submission
    def test_12_order_submission(self):
        auth = self._make_valid_auth(symbol="TCS.NS", quantity=2, token="tok-submit-01")
        res = self.sandbox_adapter.submit_order(auth)
        self.assertEqual(res.status, PaperOrderStatus.FILLED)
        self.assertEqual(res.order.requested_quantity, 2)
        self.assertEqual(res.order.filled_quantity, 2)

    # 13. Order status
    def test_13_order_status(self):
        auth = self._make_valid_auth(symbol="TCS.NS", quantity=1, token="tok-status-01")
        res = self.sandbox_adapter.submit_order(auth)
        self.assertIn(res.order.status, [PaperOrderStatus.FILLED, PaperOrderStatus.ACKNOWLEDGED])

    # 14. Cancellation
    def test_14_order_cancellation(self):
        # Insert a pending order manually into mock client
        self.mock_client.orders["ord-to-cancel"] = {
            "order_id": "ord-to-cancel",
            "symbol": "TCS.NS",
            "side": "BUY",
            "quantity": 10,
            "status": "OPEN",
        }
        res = self.sandbox_adapter.cancel_order("ord-to-cancel")
        self.assertTrue(res)

    # 15. Fill processing
    def test_15_fill_processing(self):
        auth = self._make_valid_auth(symbol="RELIANCE.NS", quantity=4, token="tok-fill-01")
        res = self.sandbox_adapter.submit_order(auth)
        self.assertEqual(len(res.new_fills), 1)
        fill = res.new_fills[0]
        self.assertEqual(fill.quantity, 4)
        self.assertEqual(fill.price, 3500.0)

    # 16. Idempotent order submission
    def test_16_idempotent_order_submission(self):
        auth = self._make_valid_auth(symbol="TCS.NS", quantity=3, token="tok-idemp-unique")
        res1 = self.sandbox_adapter.submit_order(auth)
        self.assertEqual(res1.status, PaperOrderStatus.FILLED)

        # Resubmit with identical token
        res2 = self.sandbox_adapter.submit_order(auth)
        self.assertEqual(res1.order.order_id, res2.order.order_id)
        self.assertIn("Idempotent duplicate", res2.message)
        # Position should only reflect 3 shares, not 6
        positions = self.sandbox_adapter.get_positions()
        self.assertEqual(positions["TCS.NS"].quantity, 3)

    # 17. Timeout handling
    def test_17_timeout_handling(self):
        self.mock_client.simulate_timeout = True
        auth = self._make_valid_auth(symbol="TCS.NS", quantity=1, token="tok-timeout")
        res = self.sandbox_adapter.submit_order(auth)
        self.assertEqual(res.status, PaperOrderStatus.REJECTED)
        self.assertIn("TIMEOUT", res.order.rejection_reason)

    # 18. Authentication failure handling
    def test_18_authentication_failure_handling(self):
        self.mock_client.simulate_auth_failure = True
        auth = self._make_valid_auth(symbol="TCS.NS", quantity=1, token="tok-auth-fail")
        res = self.sandbox_adapter.submit_order(auth)
        self.assertEqual(res.status, PaperOrderStatus.REJECTED)
        self.assertIn("AUTH_FAILURE", res.order.rejection_reason)

    # 19. Rate limiting handling
    def test_19_rate_limiting_handling(self):
        self.mock_client.simulate_rate_limit = True
        auth = self._make_valid_auth(symbol="TCS.NS", quantity=1, token="tok-rate-limit")
        res = self.sandbox_adapter.submit_order(auth)
        self.assertEqual(res.status, PaperOrderStatus.REJECTED)
        self.assertIn("RATE_LIMITED", res.order.rejection_reason)

    # 20. Broker unavailable handling
    def test_20_broker_unavailable_handling(self):
        self.mock_client.simulate_unavailable = True
        auth = self._make_valid_auth(symbol="TCS.NS", quantity=1, token="tok-unavail")
        res = self.sandbox_adapter.submit_order(auth)
        self.assertEqual(res.status, PaperOrderStatus.REJECTED)
        self.assertIn("BROKER_UNAVAILABLE", res.order.rejection_reason)

    # 21. Unknown execution state handling
    def test_21_unknown_execution_state_handling(self):
        self.mock_client.simulate_unknown_submission = True
        auth = self._make_valid_auth(symbol="TCS.NS", quantity=1, token="tok-uncertain")
        res = self.sandbox_adapter.submit_order(auth)
        self.assertEqual(res.status, PaperOrderStatus.REJECTED)
        self.assertEqual(res.order.rejection_reason, "UNKNOWN_SUBMISSION_STATE")
        self.assertTrue(self.sandbox_adapter._reconciliation_needed)

    # 22. Reconciliation report generation
    def test_22_reconciliation_report_generation(self):
        report = self.reconciliation.reconcile(adapter=self.sandbox_adapter)
        self.assertIsNotNone(report.reconciliation_id)
        self.assertTrue(report.is_reconciled)
        self.assertEqual(report.discrepancy_count, 0)

    # 23. Position mismatch detection
    def test_23_position_mismatch_detection(self):
        # Expect 10 shares of TCS.NS, but sandbox currently has 0
        report = self.reconciliation.reconcile(
            expected_positions={"TCS.NS": 10},
            adapter=self.sandbox_adapter,
        )
        self.assertFalse(report.is_reconciled)
        self.assertGreaterEqual(report.discrepancy_count, 1)
        types = [d.discrepancy_type for d in report.discrepancies]
        self.assertIn(DiscrepancyType.POSITION_MISMATCH, types)

    # 24. Order mismatch detection
    def test_24_order_mismatch_detection(self):
        # Create a mock TradingOSRun with an order that doesn't exist in sandbox
        dummy_run = TradingOSRun(
            run_id="run-mismatch-01",
            context_id="ctx-01",
            symbol="TCS.NS",
            paper_order={
                "order_id": "ord-phantom-999",
                "symbol": "TCS.NS",
                "requested_quantity": 5,
                "status": "FILLED",
            },
        )
        report = self.reconciliation.reconcile(
            trading_os_runs=[dummy_run],
            adapter=self.sandbox_adapter,
        )
        self.assertFalse(report.is_reconciled)
        types = [d.discrepancy_type for d in report.discrepancies]
        self.assertIn(DiscrepancyType.MISSING_ORDER_IN_BROKER, types)

    # 25. Risk Engine enforcement
    def test_25_risk_engine_enforcement(self):
        auth = self._make_valid_auth(symbol="TCS.NS", quantity=5, token="tok-risk-veto", risk_veto=True)
        self.manager.configure(BrokerConfig(broker_environment=BrokerEnvironment.SANDBOX))
        res = self.manager.route_order(auth)
        self.assertEqual(res.status, PaperOrderStatus.REJECTED)
        self.assertIn("RISK_VETO_ACTIVE", res.message)

    # 26. Position Sizing enforcement
    def test_26_position_sizing_enforcement(self):
        # Zero quantity
        auth = self._make_valid_auth(symbol="TCS.NS", quantity=0, token="tok-size-zero")
        self.manager.configure(BrokerConfig(broker_environment=BrokerEnvironment.SANDBOX))
        res = self.manager.route_order(auth)
        self.assertEqual(res.status, PaperOrderStatus.REJECTED)
        self.assertIn("INVALID_POSITION_SIZE", res.message)

    # 27. Pre-Flight enforcement
    def test_27_preflight_enforcement(self):
        auth = self._make_valid_auth(symbol="TCS.NS", quantity=5, token="tok-preflight-stale", stale_quote=True)
        self.manager.configure(BrokerConfig(broker_environment=BrokerEnvironment.SANDBOX))
        res = self.manager.route_order(auth)
        self.assertEqual(res.status, PaperOrderStatus.REJECTED)
        self.assertIn("PREFLIGHT_REJECTION", res.message)

    # 28. LLM cannot execute orders
    def test_28_llm_cannot_execute_orders(self):
        self.manager.configure(BrokerConfig(broker_environment=BrokerEnvironment.SANDBOX))
        # Non-snapshot raw dict payload
        raw_llm_payload = {"action": "BUY", "symbol": "TCS.NS", "quantity": 100}
        outcome = self.guard.validate_authorization(raw_llm_payload)
        self.assertFalse(outcome.is_authorized)
        self.assertIn("INVALID_AUTHORIZATION", outcome.rejection_reason)

    # 29. Dashboard broker status
    def test_29_dashboard_broker_status_apis(self):
        resp = self.client.get("/api/broker/manager/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn(data["active_environment"], ["PAPER", "SANDBOX"])
        self.assertTrue(data["is_live_blocked"])

        rec_resp = self.client.post("/api/broker/reconcile")
        self.assertEqual(rec_resp.status_code, 200)
        rec_data = rec_resp.json()
        self.assertIn("is_reconciled", rec_data)

    # 30. Telemetry integration
    def test_30_telemetry_integration(self):
        auth = self._make_valid_auth(symbol="TCS.NS", quantity=1, token="tok-telem-test")
        self.sandbox_adapter.submit_order(auth)
        ev_types = [e.event_type for e in self.telemetry._events]
        self.assertIn(ExecutionEventType.SANDBOX_ORDER_SUBMITTED, ev_types)
        self.assertIn(ExecutionEventType.SANDBOX_ORDER_FILLED, ev_types)

    # 31. Production endpoint usage prohibited
    def test_31_production_endpoint_usage_prohibited(self):
        for prod_domain in PROHIBITED_PRODUCTION_DOMAINS:
            with self.assertRaises(ValueError) as ctx:
                BrokerConfig(
                    broker_provider="test",
                    broker_environment=BrokerEnvironment.SANDBOX,
                    base_url=f"https://{prod_domain}/v1",
                    api_key="k",
                    api_secret="s",
                )
            self.assertIn("PRODUCTION_ENDPOINT_PROHIBITED", str(ctx.exception))

    # 32. Production credentials prohibited
    def test_32_production_credentials_prohibited(self):
        # Live broker factory rejects live broker modes
        with self.assertRaises(ConfigurationSafetyError):
            BrokerFactory.get_adapter("zerodha")
        with self.assertRaises(ConfigurationSafetyError):
            BrokerFactory.get_adapter("live")

    # 33. LIVE environment remains blocked
    def test_33_live_environment_remains_blocked(self):
        self.assertTrue(self.manager.get_status_summary().is_live_blocked)
        outcome = self.guard.validate_authorization(
            self._make_valid_auth(),
            target_adapter_is_live=True,
        )
        self.assertFalse(outcome.is_authorized)
        self.assertIn("LIVE_BROKER_PROHIBITED", outcome.rejection_reason)

    # 34. Existing PaperBrokerAdapter remains functional
    def test_34_existing_paper_broker_adapter_remains_functional(self):
        p_auth = self._make_valid_auth(symbol="TCS.NS", quantity=2, token="tok-paper-indep")
        p_res = self.paper_adapter.submit_order(p_auth)
        self.assertEqual(p_res.status, PaperOrderStatus.ACKNOWLEDGED)
        fill_res = self.paper_adapter.process_fills(p_res.order.order_id, market_price=3500.0)
        self.assertEqual(fill_res.status, PaperOrderStatus.FILLED)
        self.assertEqual(self.paper_adapter.account.positions["TCS.NS"].quantity, 2)

    # 35. Phase 1–14 regression compatibility
    def test_35_phase_1_14_regression_compatibility(self):
        # Verify BrokerFactory default is paper adapter
        default_adapter = BrokerFactory.get_adapter()
        self.assertIsInstance(default_adapter, PaperBrokerAdapter)
        caps = default_adapter.get_capabilities()
        self.assertEqual(caps.mode, BrokerMode.PAPER)
        self.assertFalse(caps.is_live)


if __name__ == "__main__":
    unittest.main()
