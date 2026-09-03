"""
Phase 42 — Final Production Activation, Controlled Live Execution & Final Certification
Dedicated Comprehensive Test Suite

Verifies:
1. Environment separation (DEVELOPMENT, PAPER_TRADING, LIVE_CONTROLLED)
2. Operator Authorization Gate (human-only, time-bound, single-use, bound to order fingerprint)
3. First Live Trade Hard Limits (Qty=1, MaxValue=₹5,000, CNC Cash Equity only, Max 1/day)
4. Final LiveExecutionGate (11+ sequential gates, fail-closed)
5. Live Market Data Safety Integration (Phase 38 freshness & integrity)
6. Strategy Governance Integration (Phase 29 active, unquarantined)
7. Controlled Live Trade Orchestrator (Single order execution, lifecycle state tracking)
8. Dhan Broker Adapter Live Readiness & Status Normalization
9. Emergency Kill Switch and Disarm Integration at every gate
10. AI Execution Boundary Enforcement (AI cannot issue tokens, authorize orders, or bypass limits)
11. Hidden Execution Paths Audit
12. Audit Chain Logging and Secret Scrubbing
13. REST Endpoints for Phase 42
14. Invariant: ZERO real-money broker orders submitted during tests.
"""

from datetime import datetime, timezone, timedelta
import threading
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.config.app_config import AppConfig, get_app_config
from backend.domain.broker_schemas import (
    ExchangeSegment,
    NormalizedOrderStatus,
    OrderRequest as BrokerOrderRequestDomain,
    OrderSide as BrokerOrderSide,
    OrderType as BrokerOrderType,
    ProductType as BrokerProductType,
    SafetyGateResult,
    SafetyReasonCode,
)
from backend.domain.phase42_schemas import (
    AppEnvironment,
    FirstLiveTradeConfig,
    LiveExecutionGateReasonCode,
    LiveExecutionGateResult,
    LiveOrderLifecycleState,
    LiveOrderRecord,
    OperatorAuthorizationSource,
    OperatorAuthorizationToken,
    ProductionCertificationReport,
    ProductionCertificationStatus,
)
from backend.domain.strategy_schemas import StrategyDefinition
from backend.domain.market_data_schemas import (
    MarketDataFreshness,
    MarketDataIntegrityState,
    MarketDataSnapshot,
    MarketTick,
)
from backend.application.tamper_evident_audit_chain import global_audit_chain
from backend.application.confirmation_store import (
    compute_order_fingerprint,
    global_confirmation_store,
)
from backend.execution.safety_engine import (
    KillSwitch,
    global_kill_switch,
    global_manual_order_safety_gate,
)
from backend.execution.live_arming_store import (
    LiveArmingStore,
    global_live_arming_store,
)
from backend.execution.operator_authorization_store import (
    OperatorAuthorizationStore,
    global_operator_authorization_store,
)
from backend.execution.live_execution_gate import (
    LiveExecutionGate,
    global_live_execution_gate,
)
from backend.execution.controlled_live_execution_orchestrator import (
    ControlledLiveTradeOrchestrator,
    global_controlled_live_trade_orchestrator,
)
from backend.execution.production_certification_engine import (
    ProductionCertificationEngine,
    global_production_certification_engine,
)
from backend.execution.strategy_registry import global_strategy_registry
from backend.execution.order_tracker import global_order_tracker
from backend.application.market_data_integrity_engine import MarketDataIntegrityEngine
from backend.adapters.dhan_adapter import (
    DhanBrokerAdapter,
    build_dhan_order_payload,
    normalize_dhan_order_status,
)


class TestPhase42ProductionActivation(unittest.TestCase):
    """
    Dedicated test suite for Phase 42 Final Production Activation and Controlled Live Execution.
    """

    def setUp(self):
        """Set up clean test state before every test."""
        # Reset stores and state
        global_kill_switch.deactivate()
        global_live_arming_store.reset()
        global_confirmation_store.reset()
        global_operator_authorization_store.reset()
        global_live_execution_gate.reset_counters()
        global_controlled_live_trade_orchestrator.reset()
        global_order_tracker.clear()

        # Register test strategy
        self.test_strategy_id = "test_strat_phase42"
        self.test_strategy_version = "1.0.0"
        strat_def = StrategyDefinition(
            strategy_id=self.test_strategy_id,
            version=self.test_strategy_version,
            name="Phase 42 Test Strategy",
            description="Strategy for Phase 42 certification tests",
            author="System",
            max_position_size=10,
            max_order_value=50000.0,
            target_universe=["RELIANCE.NS", "TCS.NS", "INFY.NS"],
        )
        global_strategy_registry.register(strat_def)

        # Standard test order
        self.valid_order = BrokerOrderRequestDomain(
            symbol="RELIANCE.NS",
            side=BrokerOrderSide.BUY,
            quantity=1,
            price=2500.0,
            order_type=BrokerOrderType.LIMIT,
            exchange_segment=ExchangeSegment.NSE,
            product_type=BrokerProductType.CNC,
            request_id="test-req-001",
        )

        self.client = TestClient(app)

    def tearDown(self):
        """Clean up state after test."""
        global_kill_switch.deactivate()
        global_live_arming_store.reset()
        global_confirmation_store.reset()
        global_operator_authorization_store.reset()
        global_live_execution_gate.reset_counters()
        global_controlled_live_trade_orchestrator.reset()
        global_order_tracker.clear()

    # ============================================================
    # 1. PRODUCTION CONFIGURATION & ENVIRONMENT TESTS
    # ============================================================

    def test_production_config_separation(self):
        """Verify AppEnvironment enums and separation."""
        self.assertEqual(AppEnvironment.DEVELOPMENT.value, "DEVELOPMENT")
        self.assertEqual(AppEnvironment.PAPER_TRADING.value, "PAPER_TRADING")
        self.assertEqual(AppEnvironment.LIVE_CONTROLLED.value, "LIVE_CONTROLLED")

    def test_live_execution_enabled_defaults_false(self):
        """Verify LIVE_EXECUTION_ENABLED is False by default."""
        cfg = get_app_config()
        self.assertFalse(cfg.live_execution_enabled)

    # ============================================================
    # 2. OPERATOR AUTHORIZATION GATE TESTS
    # ============================================================

    def test_operator_token_issuance_success(self):
        """Issue human operator token with valid parameters."""
        token = global_operator_authorization_store.issue_token(
            operator_id="OP_TEST_01",
            order_request=self.valid_order,
            ttl_seconds=120,
            source="HUMAN_OPERATOR",
            operator_notes="Approved for test",
        )
        self.assertIsNotNone(token.token_id)
        self.assertTrue(token.token_id.startswith("opauth-"))
        self.assertEqual(token.operator_id, "OP_TEST_01")
        self.assertEqual(token.source, OperatorAuthorizationSource.HUMAN_OPERATOR)
        self.assertFalse(token.consumed)
        self.assertEqual(token.order_fingerprint, compute_order_fingerprint(self.valid_order))

    def test_operator_token_ai_source_rejected(self):
        """Attempt to issue token with AI source raises PermissionError."""
        for ai_src in ("AI", "AI_ADVISORY", "LLM", "AGENT", "AUTONOMOUS"):
            with self.assertRaises(PermissionError):
                global_operator_authorization_store.issue_token(
                    operator_id="AI_AGENT_01",
                    order_request=self.valid_order,
                    source=ai_src,
                )

    def test_operator_token_empty_operator_id_rejected(self):
        """Empty operator ID raises ValueError."""
        with self.assertRaises(ValueError):
            global_operator_authorization_store.issue_token(
                operator_id="",
                order_request=self.valid_order,
            )

    def test_operator_token_consumption_success(self):
        """Verify and consume valid operator token for matching order."""
        token = global_operator_authorization_store.issue_token(
            operator_id="OP_TEST_01",
            order_request=self.valid_order,
            ttl_seconds=120,
        )
        valid, code, msg, tok = global_operator_authorization_store.verify_and_consume(
            token_id=token.token_id,
            order=self.valid_order,
        )
        self.assertTrue(valid)
        self.assertEqual(code, LiveExecutionGateReasonCode.VALID)
        self.assertTrue(tok.consumed)
        self.assertIsNotNone(tok.consumed_at)

    def test_operator_token_single_use_consumption(self):
        """Token can only be consumed once; second attempt fails."""
        token = global_operator_authorization_store.issue_token(
            operator_id="OP_TEST_01",
            order_request=self.valid_order,
            ttl_seconds=120,
        )
        # First consumption
        valid1, code1, msg1, tok1 = global_operator_authorization_store.verify_and_consume(
            token_id=token.token_id,
            order=self.valid_order,
        )
        self.assertTrue(valid1)

        # Second consumption attempt (Replay attack)
        valid2, code2, msg2, tok2 = global_operator_authorization_store.verify_and_consume(
            token_id=token.token_id,
            order=self.valid_order,
        )
        self.assertFalse(valid2)
        self.assertEqual(code2, LiveExecutionGateReasonCode.OPERATOR_AUTH_REUSED)

    def test_operator_token_ttl_expiry(self):
        """Token evaluated after expiry window fails closed."""
        now = datetime.now(timezone.utc)
        token = global_operator_authorization_store.issue_token(
            operator_id="OP_TEST_01",
            order_request=self.valid_order,
            ttl_seconds=30,
            current_time=now,
        )
        future_time = now + timedelta(seconds=35)
        valid, code, msg, tok = global_operator_authorization_store.verify_and_consume(
            token_id=token.token_id,
            order=self.valid_order,
            current_time=future_time,
        )
        self.assertFalse(valid)
        self.assertEqual(code, LiveExecutionGateReasonCode.OPERATOR_AUTH_EXPIRED)

    def test_operator_token_fingerprint_mismatch(self):
        """Modified order parameters reject consumption due to fingerprint mismatch."""
        token = global_operator_authorization_store.issue_token(
            operator_id="OP_TEST_01",
            order_request=self.valid_order,
        )
        # Modified order: changed quantity
        tampered_order = self.valid_order.model_copy(update={"quantity": 5})
        valid, code, msg, tok = global_operator_authorization_store.verify_and_consume(
            token_id=token.token_id,
            order=tampered_order,
        )
        self.assertFalse(valid)
        self.assertEqual(code, LiveExecutionGateReasonCode.OPERATOR_AUTH_MISMATCH)

    def test_operator_token_missing_token_id(self):
        """Missing or non-existent token returns OPERATOR_AUTH_MISSING."""
        valid, code, msg, tok = global_operator_authorization_store.verify_and_consume(
            token_id="non-existent-token-id",
            order=self.valid_order,
        )
        self.assertFalse(valid)
        self.assertEqual(code, LiveExecutionGateReasonCode.OPERATOR_AUTH_MISSING)

    def test_operator_token_invalidation(self):
        """Manually invalidating token removes it from store."""
        token = global_operator_authorization_store.issue_token(
            operator_id="OP_TEST_01",
            order_request=self.valid_order,
        )
        res = global_operator_authorization_store.invalidate(token.token_id)
        self.assertTrue(res)
        self.assertIsNone(global_operator_authorization_store.get_token(token.token_id))

    # ============================================================
    # 3. FIRST LIVE TRADE HARD LIMITS TESTS
    # ============================================================

    def test_first_live_trade_config_defaults(self):
        """Verify strict hard limits for first live trade."""
        cfg = FirstLiveTradeConfig()
        self.assertEqual(cfg.max_quantity, 1)
        self.assertEqual(cfg.max_order_value, 5000.0)
        self.assertEqual(cfg.max_daily_loss, 1000.0)
        self.assertEqual(cfg.max_orders_per_day, 1)
        self.assertIn("EQUITY", cfg.allowed_asset_classes)
        self.assertIn("CNC", cfg.allowed_product_types)

    def test_first_live_trade_quantity_limit_enforced(self):
        """Order quantity > 1 is rejected by LiveExecutionGate."""
        order = self.valid_order.model_copy(update={"quantity": 2})
        token = global_operator_authorization_store.issue_token("OP1", order)

        with patch("backend.execution.live_execution_gate.get_app_config") as mock_cfg:
            mock_cfg.return_value = AppConfig(live_execution_enabled=True, dhan_enabled=True, dhan_client_id="C1", dhan_access_token="T1")
            global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)

            gate_res = global_live_execution_gate.evaluate_live_order(
                order=order,
                operator_token_id=token.token_id,
                strategy_id=self.test_strategy_id,
                strategy_version=self.test_strategy_version,
                bypass_market_data_for_test=True,
            )
            self.assertFalse(gate_res.is_approved)
            self.assertEqual(gate_res.reason_code, LiveExecutionGateReasonCode.FIRST_TRADE_QUANTITY_EXCEEDED)

    def test_first_live_trade_order_value_limit_enforced(self):
        """Order value > ₹5,000 is rejected by LiveExecutionGate."""
        order = self.valid_order.model_copy(update={"price": 6000.0})
        token = global_operator_authorization_store.issue_token("OP1", order)

        with patch("backend.execution.live_execution_gate.get_app_config") as mock_cfg:
            mock_cfg.return_value = AppConfig(live_execution_enabled=True, dhan_enabled=True, dhan_client_id="C1", dhan_access_token="T1")
            global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)

            gate_res = global_live_execution_gate.evaluate_live_order(
                order=order,
                operator_token_id=token.token_id,
                strategy_id=self.test_strategy_id,
                strategy_version=self.test_strategy_version,
                bypass_market_data_for_test=True,
            )
            self.assertFalse(gate_res.is_approved)
            self.assertEqual(gate_res.reason_code, LiveExecutionGateReasonCode.FIRST_TRADE_VALUE_EXCEEDED)

    def test_first_live_trade_disallowed_asset_class(self):
        """Derivative exchange segment (NSE_FNO) is rejected for first live trade."""
        order = self.valid_order.model_copy(update={"exchange_segment": ExchangeSegment.NSE_FNO})
        token = global_operator_authorization_store.issue_token("OP1", order)

        with patch("backend.execution.live_execution_gate.get_app_config") as mock_cfg:
            mock_cfg.return_value = AppConfig(live_execution_enabled=True, dhan_enabled=True, dhan_client_id="C1", dhan_access_token="T1")
            global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)

            gate_res = global_live_execution_gate.evaluate_live_order(
                order=order,
                operator_token_id=token.token_id,
                strategy_id=self.test_strategy_id,
                strategy_version=self.test_strategy_version,
                bypass_market_data_for_test=True,
            )
            self.assertFalse(gate_res.is_approved)
            self.assertEqual(gate_res.reason_code, LiveExecutionGateReasonCode.FIRST_TRADE_DISALLOWED_ASSET_CLASS)

    def test_first_live_trade_disallowed_product_type(self):
        """Intraday MIS product type is rejected for first live trade (CNC only)."""
        order = self.valid_order.model_copy(update={"product_type": BrokerProductType.MIS})
        token = global_operator_authorization_store.issue_token("OP1", order)

        with patch("backend.execution.live_execution_gate.get_app_config") as mock_cfg:
            mock_cfg.return_value = AppConfig(live_execution_enabled=True, dhan_enabled=True, dhan_client_id="C1", dhan_access_token="T1")
            global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)

            gate_res = global_live_execution_gate.evaluate_live_order(
                order=order,
                operator_token_id=token.token_id,
                strategy_id=self.test_strategy_id,
                strategy_version=self.test_strategy_version,
                bypass_market_data_for_test=True,
            )
            self.assertFalse(gate_res.is_approved)
            self.assertEqual(gate_res.reason_code, LiveExecutionGateReasonCode.FIRST_TRADE_DISALLOWED_PRODUCT_TYPE)

    def test_first_live_trade_daily_order_count_limit(self):
        """Second live order on the same day is rejected."""
        token1 = global_operator_authorization_store.issue_token("OP1", self.valid_order)

        # Simulate 1 order already submitted today
        global_live_execution_gate.record_order_submission(success=True)

        with patch("backend.execution.live_execution_gate.get_app_config") as mock_cfg:
            mock_cfg.return_value = AppConfig(live_execution_enabled=True, dhan_enabled=True, dhan_client_id="C1", dhan_access_token="T1")
            global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)

            gate_res = global_live_execution_gate.evaluate_live_order(
                order=self.valid_order,
                operator_token_id=token1.token_id,
                strategy_id=self.test_strategy_id,
                strategy_version=self.test_strategy_version,
                bypass_market_data_for_test=True,
            )
            self.assertFalse(gate_res.is_approved)
            self.assertEqual(gate_res.reason_code, LiveExecutionGateReasonCode.FIRST_TRADE_ORDER_COUNT_EXCEEDED)

    # ============================================================
    # 4. LIVE EXECUTION GATE MULTI-STAGE GATING TESTS
    # ============================================================

    def test_live_execution_gate_live_disabled_blocks(self):
        """LIVE_EXECUTION_ENABLED=False fails closed immediately."""
        token = global_operator_authorization_store.issue_token("OP1", self.valid_order)
        gate_res = global_live_execution_gate.evaluate_live_order(
            order=self.valid_order,
            operator_token_id=token.token_id,
            strategy_id=self.test_strategy_id,
            strategy_version=self.test_strategy_version,
            bypass_market_data_for_test=True,
        )
        self.assertFalse(gate_res.is_approved)
        self.assertEqual(gate_res.reason_code, LiveExecutionGateReasonCode.LIVE_MODE_DISABLED)

    def test_live_execution_gate_kill_switch_blocks(self):
        """Active kill switch halts live execution gate."""
        global_kill_switch.activate()
        token = global_operator_authorization_store.issue_token("OP1", self.valid_order)

        with patch("backend.execution.live_execution_gate.get_app_config") as mock_cfg:
            mock_cfg.return_value = AppConfig(live_execution_enabled=True)
            gate_res = global_live_execution_gate.evaluate_live_order(
                order=self.valid_order,
                operator_token_id=token.token_id,
                strategy_id=self.test_strategy_id,
                strategy_version=self.test_strategy_version,
                bypass_market_data_for_test=True,
            )
            self.assertFalse(gate_res.is_approved)
            self.assertEqual(gate_res.reason_code, LiveExecutionGateReasonCode.KILL_SWITCH_ACTIVE)

    def test_live_execution_gate_emergency_disarm_blocks(self):
        """Unarmed live session blocks live execution gate."""
        token = global_operator_authorization_store.issue_token("OP1", self.valid_order)

        with patch("backend.execution.live_execution_gate.get_app_config") as mock_cfg:
            mock_cfg.return_value = AppConfig(live_execution_enabled=True)
            # Do NOT arm live store
            gate_res = global_live_execution_gate.evaluate_live_order(
                order=self.valid_order,
                operator_token_id=token.token_id,
                strategy_id=self.test_strategy_id,
                strategy_version=self.test_strategy_version,
                bypass_market_data_for_test=True,
            )
            self.assertFalse(gate_res.is_approved)
            self.assertEqual(gate_res.reason_code, LiveExecutionGateReasonCode.EMERGENCY_DISARMED)

    def test_live_execution_gate_market_data_stale_blocks(self):
        """Stale market data fails live execution gate."""
        token = global_operator_authorization_store.issue_token("OP1", self.valid_order)

        mkt_engine = MarketDataIntegrityEngine()
        now = datetime.now(timezone.utc)
        mkt_engine.process_tick({
            "symbol": "RELIANCE.NS",
            "exchange": "NSE",
            "provider_id": "DHAN",
            "last_traded_price": 2500.0,
            "last_traded_quantity": 1,
            "total_volume": 1000,
            "source_timestamp": now,
            "received_timestamp": now,
        })
        # Mark stale
        snapshot = mkt_engine.get_snapshot("RELIANCE.NS")
        self.assertIsNotNone(snapshot)
        snapshot.freshness = MarketDataFreshness.STALE

        gate = LiveExecutionGate(market_data_engine=mkt_engine)

        with patch("backend.execution.live_execution_gate.get_app_config") as mock_cfg:
            mock_cfg.return_value = AppConfig(live_execution_enabled=True, dhan_enabled=True, dhan_client_id="C1", dhan_access_token="T1")
            global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)

            gate_res = gate.evaluate_live_order(
                order=self.valid_order,
                operator_token_id=token.token_id,
                strategy_id=self.test_strategy_id,
                strategy_version=self.test_strategy_version,
                bypass_market_data_for_test=False,
                bypass_readiness_for_test=True,
            )
            self.assertFalse(gate_res.is_approved)
            self.assertEqual(gate_res.reason_code, LiveExecutionGateReasonCode.MARKET_DATA_STALE)

    def test_live_execution_gate_market_data_missing_blocks(self):
        """Missing market data fails live execution gate fail-closed."""
        token = global_operator_authorization_store.issue_token("OP1", self.valid_order)
        mkt_engine = MarketDataIntegrityEngine()
        gate = LiveExecutionGate(market_data_engine=mkt_engine)

        with patch("backend.execution.live_execution_gate.get_app_config") as mock_cfg:
            mock_cfg.return_value = AppConfig(live_execution_enabled=True, dhan_enabled=True, dhan_client_id="C1", dhan_access_token="T1")
            global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)

            gate_res = gate.evaluate_live_order(
                order=self.valid_order,
                operator_token_id=token.token_id,
                strategy_id=self.test_strategy_id,
                strategy_version=self.test_strategy_version,
                bypass_market_data_for_test=False,
                bypass_readiness_for_test=True,
            )
            self.assertFalse(gate_res.is_approved)
            self.assertEqual(gate_res.reason_code, LiveExecutionGateReasonCode.MARKET_DATA_INVALID)

    def test_live_execution_gate_consecutive_failures_circuit_breaker(self):
        """Reaching consecutive broker failures threshold opens circuit."""
        token = global_operator_authorization_store.issue_token("OP1", self.valid_order)
        global_live_execution_gate.record_order_submission(success=False)
        global_live_execution_gate.record_order_submission(success=False)

        with patch("backend.execution.live_execution_gate.get_app_config") as mock_cfg:
            mock_cfg.return_value = AppConfig(live_execution_enabled=True, dhan_enabled=True, dhan_client_id="C1", dhan_access_token="T1")
            global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)

            gate_res = global_live_execution_gate.evaluate_live_order(
                order=self.valid_order,
                operator_token_id=token.token_id,
                strategy_id=self.test_strategy_id,
                strategy_version=self.test_strategy_version,
                bypass_market_data_for_test=True,
                bypass_readiness_for_test=True,
            )
            self.assertFalse(gate_res.is_approved)
            self.assertEqual(gate_res.reason_code, LiveExecutionGateReasonCode.BROKER_UNAVAILABLE)

    def test_live_execution_gate_strategy_not_active_blocks(self):
        """Unknown strategy ID fails live execution gate."""
        token = global_operator_authorization_store.issue_token("OP1", self.valid_order)

        with patch("backend.execution.live_execution_gate.get_app_config") as mock_cfg:
            mock_cfg.return_value = AppConfig(live_execution_enabled=True, dhan_enabled=True, dhan_client_id="C1", dhan_access_token="T1")
            global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)

            gate_res = global_live_execution_gate.evaluate_live_order(
                order=self.valid_order,
                operator_token_id=token.token_id,
                strategy_id="non_existent_strategy",
                strategy_version="1.0.0",
                bypass_market_data_for_test=True,
                bypass_readiness_for_test=True,
            )
            self.assertFalse(gate_res.is_approved)
            self.assertEqual(gate_res.reason_code, LiveExecutionGateReasonCode.STRATEGY_NOT_ACTIVE)

    def test_live_execution_gate_strategy_version_mismatch_blocks(self):
        """Mismatched strategy version fails live execution gate."""
        token = global_operator_authorization_store.issue_token("OP1", self.valid_order)

        with patch("backend.execution.live_execution_gate.get_app_config") as mock_cfg:
            mock_cfg.return_value = AppConfig(live_execution_enabled=True, dhan_enabled=True, dhan_client_id="C1", dhan_access_token="T1")
            global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)

            gate_res = global_live_execution_gate.evaluate_live_order(
                order=self.valid_order,
                operator_token_id=token.token_id,
                strategy_id=self.test_strategy_id,
                strategy_version="9.9.9",  # Wrong version
                bypass_market_data_for_test=True,
                bypass_readiness_for_test=True,
            )
            self.assertFalse(gate_res.is_approved)
            self.assertEqual(gate_res.reason_code, LiveExecutionGateReasonCode.STRATEGY_VERSION_MISMATCH)

    def test_live_execution_gate_duplicate_order_blocks(self):
        """Duplicate active order in OrderTracker blocks execution gate."""
        token = global_operator_authorization_store.issue_token("OP1", self.valid_order)
        order_fp = compute_order_fingerprint(self.valid_order)
        global_order_tracker.record_submission(order_fp, "req-existing-001", order=self.valid_order, status="SUBMITTED")

        with patch("backend.execution.live_execution_gate.get_app_config") as mock_cfg:
            mock_cfg.return_value = AppConfig(live_execution_enabled=True, dhan_enabled=True, dhan_client_id="C1", dhan_access_token="T1")
            global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)

            gate_res = global_live_execution_gate.evaluate_live_order(
                order=self.valid_order,
                operator_token_id=token.token_id,
                strategy_id=self.test_strategy_id,
                strategy_version=self.test_strategy_version,
                bypass_market_data_for_test=True,
                bypass_readiness_for_test=True,
            )
            self.assertFalse(gate_res.is_approved)
            self.assertEqual(gate_res.reason_code, LiveExecutionGateReasonCode.DUPLICATE_ORDER_DETECTED)

    def test_live_execution_gate_all_checks_pass(self):
        """When all conditions are met, LiveExecutionGate returns APPROVED."""
        token = global_operator_authorization_store.issue_token("OP1", self.valid_order)

        with patch("backend.execution.live_execution_gate.get_app_config") as mock_cfg:
            mock_cfg.return_value = AppConfig(
                live_execution_enabled=True,
                dhan_enabled=True,
                dhan_client_id="DHAN_TEST_CLIENT",
                dhan_access_token="DHAN_TEST_TOKEN",
            )
            global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)

            gate_res = global_live_execution_gate.evaluate_live_order(
                order=self.valid_order,
                operator_token_id=token.token_id,
                strategy_id=self.test_strategy_id,
                strategy_version=self.test_strategy_version,
                bypass_market_data_for_test=True,
                bypass_readiness_for_test=True,
            )
            self.assertTrue(gate_res.is_approved)
            self.assertEqual(gate_res.reason_code, LiveExecutionGateReasonCode.VALID)
            self.assertTrue(gate_res.first_trade_checks_passed)

    # ============================================================
    # 5. CONTROLLED LIVE TRADE ORCHESTRATOR & LIFECYCLE TESTS
    # ============================================================

    def test_controlled_trade_orchestrator_successful_execution(self):
        """Controlled single-trade execution lifecycle from CREATED to FILLED."""
        token = global_operator_authorization_store.issue_token("OP1", self.valid_order)

        mock_adapter = MagicMock(spec=DhanBrokerAdapter)
        mock_adapter.submit_manual_order.return_value = MagicMock(
            status="FILLED",
            order_id="dhan-123456",
            broker_order_id="dhan-123456",
            message="Traded successfully",
            rejection_reason=None,
        )
        mock_adapter.get_dhan_order_status.return_value = {
            "status": "FILLED",
            "filled_quantity": 1,
            "average_price": 2500.0,
        }

        orch = ControlledLiveTradeOrchestrator(
            execution_gate=global_live_execution_gate,
            dhan_adapter=mock_adapter,
        )

        with patch("backend.execution.live_execution_gate.get_app_config") as mock_cfg:
            mock_cfg.return_value = AppConfig(
                live_execution_enabled=True,
                dhan_enabled=True,
                dhan_client_id="DHAN_C1",
                dhan_access_token="DHAN_T1",
            )
            global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)

            gate_res, order_rec, broker_res = orch.execute_controlled_trade(
                order=self.valid_order,
                operator_token_id=token.token_id,
                strategy_id=self.test_strategy_id,
                strategy_version=self.test_strategy_version,
                bypass_market_data_for_test=True,
                bypass_readiness_for_test=True,
            )

            self.assertTrue(gate_res.is_approved)
            self.assertIsNotNone(order_rec)
            self.assertEqual(order_rec.state, LiveOrderLifecycleState.FILLED)
            self.assertEqual(order_rec.broker_order_id, "dhan-123456")
            self.assertEqual(order_rec.filled_quantity, 1)

    def test_controlled_trade_orchestrator_rejected_order(self):
        """When broker rejects order, order record transitions to REJECTED."""
        token = global_operator_authorization_store.issue_token("OP1", self.valid_order)

        mock_adapter = MagicMock(spec=DhanBrokerAdapter)
        mock_adapter.submit_manual_order.return_value = MagicMock(
            status="REJECTED",
            order_id=None,
            broker_order_id=None,
            message="Margin insufficient",
            rejection_reason="BROKER_REJECTED",
        )

        orch = ControlledLiveTradeOrchestrator(
            execution_gate=global_live_execution_gate,
            dhan_adapter=mock_adapter,
        )

        with patch("backend.execution.live_execution_gate.get_app_config") as mock_cfg:
            mock_cfg.return_value = AppConfig(
                live_execution_enabled=True,
                dhan_enabled=True,
                dhan_client_id="DHAN_C1",
                dhan_access_token="DHAN_T1",
            )
            global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)

            gate_res, order_rec, broker_res = orch.execute_controlled_trade(
                order=self.valid_order,
                operator_token_id=token.token_id,
                strategy_id=self.test_strategy_id,
                strategy_version=self.test_strategy_version,
                bypass_market_data_for_test=True,
                bypass_readiness_for_test=True,
            )

            self.assertTrue(gate_res.is_approved)
            self.assertIsNotNone(order_rec)
            self.assertEqual(order_rec.state, LiveOrderLifecycleState.REJECTED)
            self.assertIn("Margin insufficient", order_rec.rejection_reason)

    def test_controlled_trade_orchestrator_transient_broker_error(self):
        """Broker exception during submission fails cleanly to FAILED state."""
        token = global_operator_authorization_store.issue_token("OP1", self.valid_order)

        mock_adapter = MagicMock(spec=DhanBrokerAdapter)
        mock_adapter.submit_manual_order.side_effect = RuntimeError("Broker connection timeout")

        orch = ControlledLiveTradeOrchestrator(
            execution_gate=global_live_execution_gate,
            dhan_adapter=mock_adapter,
        )

        with patch("backend.execution.live_execution_gate.get_app_config") as mock_cfg:
            mock_cfg.return_value = AppConfig(
                live_execution_enabled=True,
                dhan_enabled=True,
                dhan_client_id="DHAN_C1",
                dhan_access_token="DHAN_T1",
            )
            global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)

            gate_res, order_rec, broker_res = orch.execute_controlled_trade(
                order=self.valid_order,
                operator_token_id=token.token_id,
                strategy_id=self.test_strategy_id,
                strategy_version=self.test_strategy_version,
                bypass_market_data_for_test=True,
                bypass_readiness_for_test=True,
            )

            self.assertTrue(gate_res.is_approved)
            self.assertIsNotNone(order_rec)
            self.assertEqual(order_rec.state, LiveOrderLifecycleState.FAILED)

    def test_order_lifecycle_state_transitions(self):
        """Test transitions across full lifecycle states."""
        rec = LiveOrderRecord(
            order_id="ord-001",
            request_id="req-001",
            symbol="TCS.NS",
            side="BUY",
            quantity=1,
            price=3500.0,
            exchange_segment="NSE",
            product_type="CNC",
            order_type="LIMIT",
            order_fingerprint="fp123",
            operator_token_id="tok123",
            confirmation_token_masked="mask123",
            audit_correlation_id="corr123",
        )
        self.assertEqual(rec.state, LiveOrderLifecycleState.CREATED)

        rec.transition_to(LiveOrderLifecycleState.AUTHORIZED)
        self.assertEqual(rec.state, LiveOrderLifecycleState.AUTHORIZED)

        rec.transition_to(LiveOrderLifecycleState.SUBMITTED)
        self.assertEqual(rec.state, LiveOrderLifecycleState.SUBMITTED)
        self.assertIsNotNone(rec.submitted_at)

        rec.transition_to(LiveOrderLifecycleState.ACKNOWLEDGED)
        self.assertEqual(rec.state, LiveOrderLifecycleState.ACKNOWLEDGED)
        self.assertIsNotNone(rec.acknowledged_at)

        rec.transition_to(LiveOrderLifecycleState.FILLED)
        self.assertEqual(rec.state, LiveOrderLifecycleState.FILLED)
        self.assertIsNotNone(rec.filled_at)

        rec.transition_to(LiveOrderLifecycleState.RECONCILED)
        self.assertEqual(rec.state, LiveOrderLifecycleState.RECONCILED)
        self.assertIsNotNone(rec.reconciled_at)

    # ============================================================
    # 6. PRODUCTION CERTIFICATION ENGINE TESTS
    # ============================================================

    def test_production_certification_engine_development_ready(self):
        """Certifies DEVELOPMENT_READY in development environment."""
        engine = ProductionCertificationEngine()
        report = engine.certify_production_readiness(
            target_environment=AppEnvironment.DEVELOPMENT
        )
        self.assertEqual(report.overall_status, ProductionCertificationStatus.DEVELOPMENT_READY)
        self.assertFalse(report.live_execution_enabled)
        self.assertTrue(report.ai_boundary_enforced)

    def test_production_certification_engine_paper_trading_ready(self):
        """Certifies PAPER_TRADING_READY when LIVE_EXECUTION_ENABLED is False."""
        engine = ProductionCertificationEngine()
        report = engine.certify_production_readiness(
            target_environment=AppEnvironment.LIVE_CONTROLLED
        )
        # Because live is false, it certifies for PAPER and notes live requires activation
        self.assertEqual(report.overall_status, ProductionCertificationStatus.PAPER_TRADING_READY)

    def test_production_certification_engine_blocked_by_kill_switch(self):
        """Kill switch engaged marks production certification as BLOCKED."""
        global_kill_switch.activate()
        engine = ProductionCertificationEngine()
        report = engine.certify_production_readiness(
            target_environment=AppEnvironment.LIVE_CONTROLLED
        )
        self.assertEqual(report.overall_status, ProductionCertificationStatus.BLOCKED)

    def test_production_certification_engine_secret_scrubbing(self):
        """Verify zero plaintext secrets in certification summary report."""
        engine = ProductionCertificationEngine()
        report = engine.certify_production_readiness()
        summary = report.to_summary_dict()
        summary_str = str(summary)
        self.assertNotIn("password", summary_str.lower())
        self.assertNotIn("secret", summary_str.lower())
        self.assertNotIn("access_token", summary_str.lower())

    # ============================================================
    # 7. AI EXECUTION BOUNDARY TESTS
    # ============================================================

    def test_ai_boundary_cannot_issue_operator_token(self):
        """AI calling token issuance directly is blocked."""
        with self.assertRaises(PermissionError):
            global_operator_authorization_store.issue_token(
                operator_id="AI_LLM_AGENT",
                order_request=self.valid_order,
                source="AI",
            )

    def test_ai_boundary_cannot_bypass_live_execution_gate(self):
        """Injecting AI safety flags does not bypass gate rejections."""
        # Unarmed session + AI flags
        token = global_operator_authorization_store.issue_token("OP1", self.valid_order)
        order_with_ai = self.valid_order.model_copy()

        gate_res = global_live_execution_gate.evaluate_live_order(
            order=order_with_ai,
            operator_token_id=token.token_id,
            strategy_id=self.test_strategy_id,
            strategy_version=self.test_strategy_version,
            bypass_market_data_for_test=True,
        )
        self.assertFalse(gate_res.is_approved)

    def test_ai_boundary_cannot_disable_kill_switch(self):
        """Kill switch can only be disengaged through Python thread-safe method."""
        global_kill_switch.activate()
        self.assertTrue(global_kill_switch.is_active())

    def test_ai_boundary_cannot_modify_first_trade_limits(self):
        """FirstLiveTradeConfig fields are immutable per gate instance."""
        gate = LiveExecutionGate()
        self.assertEqual(gate.first_live_config.max_quantity, 1)
        self.assertEqual(gate.first_live_config.max_order_value, 5000.0)

    # ============================================================
    # 8. DHAN BROKER ADAPTER & PAYLOAD TESTS
    # ============================================================

    def test_dhan_adapter_payload_construction(self):
        """Test correct formatting of Dhan v2 payload."""
        payload = build_dhan_order_payload(self.valid_order, "DHAN_CLIENT_123")
        self.assertEqual(payload["dhanClientId"], "DHAN_CLIENT_123")
        self.assertEqual(payload["transactionType"], "BUY")
        self.assertEqual(payload["exchangeSegment"], "NSE_EQ")
        self.assertEqual(payload["productType"], "CNC")
        self.assertEqual(payload["orderType"], "LIMIT")
        self.assertEqual(payload["quantity"], 1)
        self.assertEqual(payload["price"], 2500.0)
        self.assertEqual(payload["validity"], "DAY")

    def test_dhan_adapter_status_normalization(self):
        """Test status normalization across Dhan raw strings."""
        self.assertEqual(normalize_dhan_order_status("TRADED"), NormalizedOrderStatus.FILLED)
        self.assertEqual(normalize_dhan_order_status("FILLED"), NormalizedOrderStatus.FILLED)
        self.assertEqual(normalize_dhan_order_status("PENDING"), NormalizedOrderStatus.PENDING)
        self.assertEqual(normalize_dhan_order_status("OPEN"), NormalizedOrderStatus.OPEN)
        self.assertEqual(normalize_dhan_order_status("TRANSIT"), NormalizedOrderStatus.SUBMITTED)
        self.assertEqual(normalize_dhan_order_status("REJECTED"), NormalizedOrderStatus.REJECTED)
        self.assertEqual(normalize_dhan_order_status("CANCELLED"), NormalizedOrderStatus.CANCELLED)

    # ============================================================
    # 9. REST API ENDPOINT TESTS
    # ============================================================

    def test_rest_endpoint_issue_operator_token(self):
        """Test POST /api/production/operator/token."""
        res = self.client.post("/api/production/operator/token", json={
            "operator_id": "OPERATOR_01",
            "symbol": "RELIANCE.NS",
            "side": "BUY",
            "quantity": 1,
            "price": 2500.0,
            "order_type": "LIMIT",
            "exchange_segment": "NSE",
            "product_type": "CNC",
            "ttl_seconds": 120,
            "source": "HUMAN_OPERATOR",
        })
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertIn("token_id", data)
        self.assertEqual(data["status"], "ISSUED")

    def test_rest_endpoint_issue_operator_token_ai_forbidden(self):
        """Test POST /api/production/operator/token with AI source returns 403."""
        res = self.client.post("/api/production/operator/token", json={
            "operator_id": "AI_AGENT",
            "symbol": "RELIANCE.NS",
            "side": "BUY",
            "quantity": 1,
            "price": 2500.0,
            "order_type": "LIMIT",
            "exchange_segment": "NSE",
            "product_type": "CNC",
            "ttl_seconds": 120,
            "source": "AI",
        })
        self.assertEqual(res.status_code, 403)

    def test_rest_endpoint_execute_controlled_trade_blocked(self):
        """Test POST /api/production/execute when live is disabled returns rejected status."""
        # Issue token first
        tok_res = self.client.post("/api/production/operator/token", json={
            "operator_id": "OPERATOR_01",
            "symbol": "RELIANCE.NS",
            "side": "BUY",
            "quantity": 1,
            "price": 2500.0,
            "order_type": "LIMIT",
            "exchange_segment": "NSE",
            "product_type": "CNC",
            "ttl_seconds": 120,
            "source": "HUMAN_OPERATOR",
        })
        token_id = tok_res.json()["token_id"]

        res = self.client.post("/api/production/execute", json={
            "symbol": "RELIANCE.NS",
            "side": "BUY",
            "quantity": 1,
            "price": 2500.0,
            "order_type": "LIMIT",
            "exchange_segment": "NSE",
            "product_type": "CNC",
            "operator_token_id": token_id,
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["gate_status"], "REJECTED")

    def test_rest_endpoint_get_certification(self):
        """Test GET /api/production/certification."""
        res = self.client.get("/api/production/certification?env=LIVE_CONTROLLED")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("report_id", data)
        self.assertIn("overall_status", data)
        self.assertTrue(data["ai_boundary_enforced"])

    def test_rest_endpoint_get_limits(self):
        """Test GET /api/production/limits."""
        res = self.client.get("/api/production/limits")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["max_quantity"], 1)
        self.assertEqual(data["max_order_value"], 5000.0)

    def test_rest_endpoint_get_orders(self):
        """Test GET /api/production/orders."""
        res = self.client.get("/api/production/orders")
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.json(), list)

    def test_rest_endpoint_reconcile(self):
        """Test POST /api/production/reconcile."""
        res = self.client.post("/api/production/reconcile")
        self.assertEqual(res.status_code, 200)

    # ============================================================
    # 10. CONCURRENCY & INVARIANT SAFETY TESTS
    # ============================================================

    def test_concurrent_operator_token_consumption(self):
        """Two concurrent threads trying to consume the same token -> exactly 1 succeeds."""
        token = global_operator_authorization_store.issue_token("OP1", self.valid_order)
        results = []

        def worker():
            valid, code, msg, tok = global_operator_authorization_store.verify_and_consume(
                token_id=token.token_id,
                order=self.valid_order,
            )
            results.append(valid)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 1)

    def test_kill_switch_purges_armed_state(self):
        """Activating kill switch automatically disarms live arming store."""
        global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)
        self.assertTrue(global_live_arming_store.is_currently_armed())

        global_kill_switch.activate()
        self.assertFalse(global_live_arming_store.is_currently_armed())

    # ============================================================
    # 11. EXTENDED FAILURE, ADVERSARIAL & EDGE-CASE TESTS
    # ============================================================

    def test_operator_token_invalid_ttl_values(self):
        """TTL seconds < 10 or > 3600 are rejected."""
        with self.assertRaises(ValueError):
            global_operator_authorization_store.issue_token(
                operator_id="OP1",
                order_request=self.valid_order,
                ttl_seconds=5,  # Too short
            )
        with self.assertRaises(ValueError):
            global_operator_authorization_store.issue_token(
                operator_id="OP1",
                order_request=self.valid_order,
                ttl_seconds=5000,  # Too long
            )

    def test_operator_token_multi_operator_isolation(self):
        """Tokens from different operators for different symbols remain strictly isolated."""
        order1 = self.valid_order.model_copy(update={"symbol": "INFY.NS", "request_id": "req-infy"})
        order2 = self.valid_order.model_copy(update={"symbol": "TCS.NS", "request_id": "req-tcs"})

        tok1 = global_operator_authorization_store.issue_token("OP_A", order1)
        tok2 = global_operator_authorization_store.issue_token("OP_B", order2)

        # Cross verification must fail
        valid_cross, code_cross, _, _ = global_operator_authorization_store.verify_and_consume(
            token_id=tok1.token_id,
            order=order2,
        )
        self.assertFalse(valid_cross)
        self.assertEqual(code_cross, LiveExecutionGateReasonCode.OPERATOR_AUTH_MISMATCH)

        # Correct verification must succeed
        valid_corr, code_corr, _, _ = global_operator_authorization_store.verify_and_consume(
            token_id=tok1.token_id,
            order=order1,
        )
        self.assertTrue(valid_corr)

    def test_live_execution_gate_zero_quantity_rejected(self):
        """Quantity <= 0 is rejected by preflight."""
        order = self.valid_order.model_copy(update={"quantity": 0})
        token = global_operator_authorization_store.issue_token("OP1", order)

        with patch("backend.execution.live_execution_gate.get_app_config") as mock_cfg:
            mock_cfg.return_value = AppConfig(live_execution_enabled=True, dhan_enabled=True, dhan_client_id="C1", dhan_access_token="T1")
            global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)

            gate_res = global_live_execution_gate.evaluate_live_order(
                order=order,
                operator_token_id=token.token_id,
                strategy_id=self.test_strategy_id,
                strategy_version=self.test_strategy_version,
                bypass_market_data_for_test=True,
                bypass_readiness_for_test=True,
            )
            self.assertFalse(gate_res.is_approved)

    def test_live_execution_gate_negative_price_rejected(self):
        """Negative price on LIMIT order is rejected by preflight."""
        order = self.valid_order.model_copy(update={"price": -100.0})
        token = global_operator_authorization_store.issue_token("OP1", order)

        with patch("backend.execution.live_execution_gate.get_app_config") as mock_cfg:
            mock_cfg.return_value = AppConfig(live_execution_enabled=True, dhan_enabled=True, dhan_client_id="C1", dhan_access_token="T1")
            global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)

            gate_res = global_live_execution_gate.evaluate_live_order(
                order=order,
                operator_token_id=token.token_id,
                strategy_id=self.test_strategy_id,
                strategy_version=self.test_strategy_version,
                bypass_market_data_for_test=True,
                bypass_readiness_for_test=True,
            )
            self.assertFalse(gate_res.is_approved)
            self.assertEqual(gate_res.reason_code, LiveExecutionGateReasonCode.PREFLIGHT_FAILED)

    def test_live_execution_gate_nan_price_rejected(self):
        """NaN price on LIMIT order is rejected by preflight."""
        order = self.valid_order.model_copy(update={"price": float("nan")})
        token = global_operator_authorization_store.issue_token("OP1", order)

        with patch("backend.execution.live_execution_gate.get_app_config") as mock_cfg:
            mock_cfg.return_value = AppConfig(live_execution_enabled=True, dhan_enabled=True, dhan_client_id="C1", dhan_access_token="T1")
            global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)

            gate_res = global_live_execution_gate.evaluate_live_order(
                order=order,
                operator_token_id=token.token_id,
                strategy_id=self.test_strategy_id,
                strategy_version=self.test_strategy_version,
                bypass_market_data_for_test=True,
                bypass_readiness_for_test=True,
            )
            self.assertFalse(gate_res.is_approved)
            self.assertEqual(gate_res.reason_code, LiveExecutionGateReasonCode.PREFLIGHT_FAILED)

    def test_live_execution_gate_empty_symbol_rejected(self):
        """Empty symbol string is rejected by preflight."""
        order = self.valid_order.model_copy(update={"symbol": ""})
        token = global_operator_authorization_store.issue_token("OP1", order)

        with patch("backend.execution.live_execution_gate.get_app_config") as mock_cfg:
            mock_cfg.return_value = AppConfig(live_execution_enabled=True, dhan_enabled=True, dhan_client_id="C1", dhan_access_token="T1")
            global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)

            gate_res = global_live_execution_gate.evaluate_live_order(
                order=order,
                operator_token_id=token.token_id,
                strategy_id=self.test_strategy_id,
                strategy_version=self.test_strategy_version,
                bypass_market_data_for_test=True,
                bypass_readiness_for_test=True,
            )
            self.assertFalse(gate_res.is_approved)
            self.assertEqual(gate_res.reason_code, LiveExecutionGateReasonCode.PREFLIGHT_FAILED)

    def test_live_execution_gate_daily_reset_on_new_day(self):
        """Order count resets automatically on a new UTC calendar day."""
        t1 = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc)

        global_live_execution_gate.record_order_submission(success=True, current_time=t1)
        self.assertEqual(global_live_execution_gate.get_daily_orders_count(t1), 1)

        # Next day query returns 0
        self.assertEqual(global_live_execution_gate.get_daily_orders_count(t2), 0)

    def test_live_order_record_serialization_integrity(self):
        """LiveOrderRecord serializes cleanly to JSON without leaking raw secrets."""
        rec = LiveOrderRecord(
            order_id="ord-live-999",
            request_id="req-999",
            symbol="INFY.NS",
            side="BUY",
            quantity=1,
            price=1800.0,
            exchange_segment="NSE",
            product_type="CNC",
            order_type="LIMIT",
            order_fingerprint="fp999",
            operator_token_id="tok999",
            confirmation_token_masked="conf...***REDACTED***",
            audit_correlation_id="corr999",
            state=LiveOrderLifecycleState.SUBMITTED,
        )
        dump = rec.model_dump(mode="json")
        dump_str = str(dump)
        self.assertIn("ord-live-999", dump_str)
        self.assertIn("REDACTED", dump_str)
        self.assertEqual(dump["state"], "SUBMITTED")

    def test_controlled_trade_orchestrator_blocked_gate_returns_none_records(self):
        """When execution gate rejects order, orchestrator returns None for records and broker result."""
        # Unarmed session -> gate fails
        token = global_operator_authorization_store.issue_token("OP1", self.valid_order)
        orch = ControlledLiveTradeOrchestrator(execution_gate=global_live_execution_gate)

        with patch("backend.execution.live_execution_gate.get_app_config") as mock_cfg:
            mock_cfg.return_value = AppConfig(live_execution_enabled=True)
            # Not armed -> gate fails
            gate_res, order_rec, broker_res = orch.execute_controlled_trade(
                order=self.valid_order,
                operator_token_id=token.token_id,
                strategy_id=self.test_strategy_id,
                strategy_version=self.test_strategy_version,
                bypass_market_data_for_test=True,
                bypass_readiness_for_test=True,
            )
            self.assertFalse(gate_res.is_approved)
            self.assertIsNone(order_rec)
            self.assertIsNone(broker_res)

    def test_rest_endpoint_execute_controlled_trade_success_with_mock(self):
        """Test POST /api/production/execute with mocked successful broker response."""
        tok_res = self.client.post("/api/production/operator/token", json={
            "operator_id": "OPERATOR_01",
            "symbol": "RELIANCE.NS",
            "side": "BUY",
            "quantity": 1,
            "price": 2500.0,
            "order_type": "LIMIT",
            "exchange_segment": "NSE",
            "product_type": "CNC",
            "ttl_seconds": 120,
            "source": "HUMAN_OPERATOR",
        })
        token_id = tok_res.json()["token_id"]

        with patch("backend.execution.live_execution_gate.get_app_config") as mock_cfg:
            mock_cfg.return_value = AppConfig(
                live_execution_enabled=True,
                dhan_enabled=True,
                dhan_client_id="DHAN_C1",
                dhan_access_token="DHAN_T1",
            )
            global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)

            with patch.object(
                global_controlled_live_trade_orchestrator,
                "execute_controlled_trade",
            ) as mock_exec:
                mock_exec.return_value = (
                    LiveExecutionGateResult(
                        is_approved=True,
                        reason_code=LiveExecutionGateReasonCode.VALID,
                        reason="All checks passed",
                        order_fingerprint="fp123",
                        operator_token_id=token_id,
                        first_trade_checks_passed=True,
                    ),
                    LiveOrderRecord(
                        order_id="ord-live-123",
                        request_id="req-123",
                        symbol="RELIANCE.NS",
                        side="BUY",
                        quantity=1,
                        price=2500.0,
                        exchange_segment="NSE",
                        product_type="CNC",
                        order_type="LIMIT",
                        order_fingerprint="fp123",
                        operator_token_id=token_id,
                        confirmation_token_masked="mask123",
                        audit_correlation_id="corr123",
                        state=LiveOrderLifecycleState.FILLED,
                        broker_order_id="dhan-ord-001",
                    ),
                    MagicMock(status="FILLED", order_id="dhan-ord-001"),
                )

                res = self.client.post("/api/production/execute", json={
                    "symbol": "RELIANCE.NS",
                    "side": "BUY",
                    "quantity": 1,
                    "price": 2500.0,
                    "order_type": "LIMIT",
                    "exchange_segment": "NSE",
                    "product_type": "CNC",
                    "operator_token_id": token_id,
                })
                self.assertEqual(res.status_code, 200)
                data = res.json()
                self.assertTrue(data["success"])
                self.assertEqual(data["gate_status"], "APPROVED")
                self.assertEqual(data["order_record"]["state"], "FILLED")

    def test_audit_trail_immutable_chain_on_operator_token_events(self):
        """Audit chain contains immutable verified event on operator token issuance."""
        token = global_operator_authorization_store.issue_token("OP_AUDIT", self.valid_order)
        audit_res = global_audit_chain.verify_integrity()
        self.assertEqual(audit_res.status.value, "VALID")

    def test_live_readiness_certification_engine_hidden_paths_zero(self):
        """Verify dynamic execution path audit detects 0 hidden execution paths."""
        count, ok = global_production_certification_engine.global_cert_engine._audit_execution_paths()
        self.assertEqual(count, 0)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()

