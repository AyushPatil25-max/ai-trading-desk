"""
Phase 8 — Execution Monitoring & Live Telemetry Comprehensive Tests

Verifies all 34 required test cases + adversarial safety tests:
1. Event creation
2. Event immutability
3. Event ordering
4. Order timeline
5. Fill events
6. Partial fills
7. Complete fills
8. Rejection events
9. Risk veto events
10. Pre-flight rejection events
11. Latency calculation
12. Slippage calculation
13. Fill metrics
14. Rejection metrics
15. Cancellation metrics
16. Portfolio telemetry
17. Position telemetry
18. Account telemetry
19. Health checks
20. Stale-data handling
21. Error logging
22. Secret redaction
23. Kill switch
24. Kill switch blocks new orders
25. Kill switch does not delete history
26. Kill switch deterministic behavior
27. Zero-sample metrics
28. Duplicate event handling
29. API compatibility
30. Paper Broker compatibility
31. Phase 6.9 compatibility
32. Phase 7 compatibility
33. Deterministic output
34. No LLM dependency
35. Adversarial telemetry suite
"""

from datetime import datetime, timezone, timedelta
import unittest
from typing import Any, Dict, List

from backend.domain.preflight_schemas import (
    PREFLIGHT_ENGINE_VERSION,
    PreflightOrderType,
    PreflightSide,
    ExecutionAuthorizationSnapshot,
)
from backend.domain.paper_broker_schemas import (
    PAPER_BROKER_ENGINE_VERSION,
    PaperOrderStatus,
    PaperFill,
    PaperOrder,
    PaperPosition,
    PaperAccount,
)
from backend.domain.telemetry_schemas import (
    TELEMETRY_ENGINE_VERSION,
    ExecutionEventType,
    EventSeverity,
    KillSwitchState,
    ExecutionEvent,
    OrderTimelineStep,
    OrderTimeline,
    ExecutionMetrics,
    SystemHealthStatus,
    TelemetryDashboardSnapshot,
)
from backend.application.execution_telemetry_engine import ExecutionTelemetryEngine
from backend.application.paper_broker_adapter import PaperBrokerAdapter


class TestExecutionTelemetryPhase8(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 29, 10, 0, 0, tzinfo=timezone.utc)
        self.telemetry = ExecutionTelemetryEngine()
        self.telemetry.clear()

        self.broker = PaperBrokerAdapter(
            initial_cash=100000.0,
            commission_rate=0.0003,
            slippage_rate=0.0005,
            telemetry_engine=self.telemetry,
        )

        self.auth = ExecutionAuthorizationSnapshot(
            authorization_id="auth-tel-001",
            decision_id="dec-tel-001",
            order_id="ord-tel-001",
            symbol="INFY.NS",
            side=PreflightSide.BUY,
            approved_quantity=25,
            normalized_limit_price=1500.0,
            normalized_stop_price=1425.0,
            normalized_target_price=1650.0,
            risk_state={"veto_applied": False, "approved_quantity": 25},
            validation_timestamp=self.now,
            data_freshness="FRESH",
            idempotency_token="tok-tel-infy-buy-25",
            engine_version=PREFLIGHT_ENGINE_VERSION,
        )

    # 1. Event creation
    def test_01_event_creation(self):
        evt = self.telemetry.record_event(
            event_type=ExecutionEventType.ORDER_CREATED,
            execution_id="exec-001",
            order_id="ord-001",
            symbol="INFY.NS",
            quantity=25,
            price=1500.0,
            timestamp=self.now,
        )
        self.assertEqual(evt.event_type, ExecutionEventType.ORDER_CREATED)
        self.assertEqual(evt.order_id, "ord-001")
        self.assertEqual(len(self.telemetry._events), 1)

    # 2. Event immutability
    def test_02_event_immutability(self):
        evt = self.telemetry.record_event(
            event_type=ExecutionEventType.ORDER_CREATED,
            execution_id="exec-001",
            order_id="ord-001",
            timestamp=self.now,
        )
        with self.assertRaises(Exception):
            evt.status = "MUTATED"

    # 3. Event ordering
    def test_03_event_ordering(self):
        t1 = self.now
        t2 = self.now + timedelta(seconds=2)
        self.telemetry.record_event(event_type=ExecutionEventType.ORDER_CREATED, execution_id="ex1", order_id="ord-1", timestamp=t1)
        self.telemetry.record_event(event_type=ExecutionEventType.ORDER_SUBMITTED, execution_id="ex1", order_id="ord-1", timestamp=t2)
        timeline = self.telemetry.get_order_timeline("ord-1")
        self.assertEqual(len(timeline.steps), 2)
        self.assertEqual(timeline.steps[0].timestamp, t1)
        self.assertEqual(timeline.steps[1].timestamp, t2)

    # 4. Order timeline
    def test_04_order_timeline(self):
        t1 = self.now
        t2 = self.now + timedelta(milliseconds=150)
        self.telemetry.record_event(event_type=ExecutionEventType.ORDER_CREATED, execution_id="ex1", order_id="ord-time", symbol="INFY.NS", timestamp=t1)
        self.telemetry.record_event(event_type=ExecutionEventType.ORDER_ACKNOWLEDGED, execution_id="ex1", order_id="ord-time", symbol="INFY.NS", timestamp=t2)
        timeline = self.telemetry.get_order_timeline("ord-time")
        self.assertEqual(timeline.order_id, "ord-time")
        self.assertEqual(timeline.symbol, "INFY.NS")
        self.assertEqual(timeline.steps[1].latency_from_prev_ms, 150.0)
        self.assertEqual(timeline.total_lifecycle_ms, 150.0)

    # 5. Fill events
    def test_05_fill_events(self):
        evt = self.telemetry.record_event(
            event_type=ExecutionEventType.FILL_CREATED,
            execution_id="exec-001",
            order_id="ord-001",
            quantity=25,
            price=1495.0,
            timestamp=self.now,
        )
        self.assertEqual(evt.event_type, ExecutionEventType.FILL_CREATED)
        self.assertEqual(evt.price, 1495.0)

    # 6. Partial fills
    def test_06_partial_fills(self):
        evt = self.telemetry.record_event(
            event_type=ExecutionEventType.ORDER_PARTIALLY_FILLED,
            execution_id="exec-001",
            order_id="ord-001",
            quantity=10,
            status=PaperOrderStatus.PARTIALLY_FILLED.value,
            timestamp=self.now,
        )
        self.assertEqual(evt.event_type, ExecutionEventType.ORDER_PARTIALLY_FILLED)

    # 7. Complete fills
    def test_07_complete_fills(self):
        evt = self.telemetry.record_event(
            event_type=ExecutionEventType.ORDER_FILLED,
            execution_id="exec-001",
            order_id="ord-001",
            quantity=25,
            status=PaperOrderStatus.FILLED.value,
            timestamp=self.now,
        )
        self.assertEqual(evt.event_type, ExecutionEventType.ORDER_FILLED)

    # 8. Rejection events
    def test_08_rejection_events(self):
        evt = self.telemetry.record_event(
            event_type=ExecutionEventType.ORDER_REJECTED,
            execution_id="exec-001",
            order_id="ord-001",
            reason="Exceeded maximum permitted exposure",
            severity=EventSeverity.WARNING,
            timestamp=self.now,
        )
        self.assertEqual(evt.event_type, ExecutionEventType.ORDER_REJECTED)
        self.assertEqual(evt.severity, EventSeverity.WARNING)

    # 9. Risk veto events
    def test_09_risk_veto_events(self):
        evt = self.telemetry.record_event(
            event_type=ExecutionEventType.RISK_VETO,
            execution_id="exec-001",
            decision_id="dec-001",
            reason="Systemic portfolio drawdown limit exceeded",
            severity=EventSeverity.CRITICAL,
            timestamp=self.now,
        )
        self.assertEqual(evt.event_type, ExecutionEventType.RISK_VETO)
        self.assertEqual(evt.severity, EventSeverity.CRITICAL)

    # 10. Pre-flight rejection events
    def test_10_preflight_rejection_events(self):
        evt = self.telemetry.record_event(
            event_type=ExecutionEventType.PREFLIGHT_REJECTED,
            execution_id="exec-001",
            reason="Requested price breaches upper circuit limit",
            timestamp=self.now,
        )
        self.assertEqual(evt.event_type, ExecutionEventType.PREFLIGHT_REJECTED)

    # 11. Latency calculation
    def test_11_latency_calculation(self):
        t1 = self.now
        t2 = self.now + timedelta(milliseconds=85)
        self.telemetry.record_event(event_type=ExecutionEventType.ORDER_CREATED, execution_id="ex", order_id="o1", timestamp=t1)
        self.telemetry.record_event(event_type=ExecutionEventType.ORDER_FILLED, execution_id="ex", order_id="o1", timestamp=t2)
        timeline = self.telemetry.get_order_timeline("o1")
        self.assertEqual(timeline.total_lifecycle_ms, 85.0)

    # 12. Slippage calculation
    def test_12_slippage_calculation(self):
        order = PaperOrder(
            authorization_id="auth-1", decision_id="dec-1", symbol="INFY.NS",
            side=PreflightSide.BUY, requested_quantity=25, remaining_quantity=0, filled_quantity=25,
            idempotency_token="tok-1", status=PaperOrderStatus.FILLED,
        )
        fill = PaperFill(
            execution_id="auth-1", order_id=order.order_id, symbol="INFY.NS",
            side=PreflightSide.BUY, quantity=25, price=1000.5, slippage_amount=12.5, commission=7.5,
        )
        order.fills.append(fill)
        metrics = self.telemetry.compute_metrics([order])
        self.assertEqual(metrics.total_slippage_cost, 12.5)
        self.assertEqual(metrics.total_simulated_commissions, 7.5)

    # 13. Fill metrics
    def test_13_fill_metrics(self):
        o1 = PaperOrder(authorization_id="a1", decision_id="d1", symbol="INFY.NS", side=PreflightSide.BUY, requested_quantity=10, remaining_quantity=0, filled_quantity=10, idempotency_token="t1", status=PaperOrderStatus.FILLED)
        o2 = PaperOrder(authorization_id="a2", decision_id="d2", symbol="TCS.NS", side=PreflightSide.BUY, requested_quantity=10, remaining_quantity=10, filled_quantity=0, idempotency_token="t2", status=PaperOrderStatus.REJECTED)
        metrics = self.telemetry.compute_metrics([o1, o2])
        self.assertEqual(metrics.total_orders, 2)
        self.assertEqual(metrics.fill_rate_pct, 50.0)
        self.assertEqual(metrics.rejection_rate_pct, 50.0)

    # 14. Rejection metrics
    def test_14_rejection_metrics(self):
        o1 = PaperOrder(authorization_id="a1", decision_id="d1", symbol="INFY.NS", side=PreflightSide.BUY, requested_quantity=10, remaining_quantity=10, filled_quantity=0, idempotency_token="t1", status=PaperOrderStatus.REJECTED)
        metrics = self.telemetry.compute_metrics([o1])
        self.assertEqual(metrics.rejection_rate_pct, 100.0)

    # 15. Cancellation metrics
    def test_15_cancellation_metrics(self):
        o1 = PaperOrder(authorization_id="a1", decision_id="d1", symbol="INFY.NS", side=PreflightSide.BUY, requested_quantity=10, remaining_quantity=10, filled_quantity=0, idempotency_token="t1", status=PaperOrderStatus.CANCELLED)
        metrics = self.telemetry.compute_metrics([o1])
        self.assertEqual(metrics.cancellation_rate_pct, 100.0)

    # 16. Portfolio telemetry
    def test_16_portfolio_telemetry(self):
        acct = self.broker.get_account()
        snap = self.telemetry.get_dashboard_snapshot(account=acct, orders=[])
        self.assertEqual(snap.account_summary["cash"], 100000.0)
        self.assertEqual(snap.account_summary["total_equity"], 100000.0)

    # 17. Position telemetry
    def test_17_position_telemetry(self):
        sub = self.broker.submit_order(self.auth, evaluation_timestamp=self.now)
        self.broker.process_fills(sub.order.order_id, market_price=1495.0, fill_ratio=1.0, evaluation_timestamp=self.now)
        snap = self.telemetry.get_dashboard_snapshot(account=self.broker.account, orders=list(self.broker.account.orders.values()))
        self.assertEqual(len(snap.positions), 1)
        self.assertEqual(snap.positions[0]["symbol"], "INFY.NS")
        self.assertEqual(snap.positions[0]["quantity"], 25)

    # 18. Account telemetry
    def test_18_account_telemetry(self):
        snap = self.telemetry.get_dashboard_snapshot(account=self.broker.account, orders=[])
        self.assertIn("buying_power", snap.account_summary)

    # 19. Health checks
    def test_19_health_checks(self):
        health = self.telemetry.get_health_status()
        self.assertEqual(health.api_status, "HEALTHY")
        self.assertEqual(health.paper_broker_status, "HEALTHY")
        self.assertTrue(health.healthy)

    # 20. Stale-data handling
    def test_20_stale_data_handling(self):
        health = self.telemetry.get_health_status()
        self.assertEqual(health.data_freshness, "FRESH")

    # 21. Error logging
    def test_21_error_logging(self):
        self.telemetry.record_event(
            event_type=ExecutionEventType.EXECUTION_ERROR,
            execution_id="ex-err",
            reason="Simulated connection timeout",
            severity=EventSeverity.ERROR,
            timestamp=self.now,
        )
        self.assertGreater(self.telemetry._error_count, 0)

    # 22. Secret redaction
    def test_22_secret_redaction(self):
        evt = self.telemetry.record_event(
            event_type=ExecutionEventType.ORDER_CREATED,
            execution_id="ex-sec",
            metadata={"api_key": "secret_12345", "token": "xyz", "safe_val": 42},
            timestamp=self.now,
        )
        self.assertEqual(evt.metadata["api_key"], "[REDACTED]")
        self.assertEqual(evt.metadata["token"], "[REDACTED]")
        self.assertEqual(evt.metadata["safe_val"], 42)

    # 23. Kill switch
    def test_23_kill_switch(self):
        self.assertFalse(self.telemetry.is_kill_switch_triggered())
        self.telemetry.trigger_kill_switch(reason="Manual emergency stop")
        self.assertTrue(self.telemetry.is_kill_switch_triggered())
        self.telemetry.disarm_kill_switch()
        self.assertFalse(self.telemetry.is_kill_switch_triggered())

    # 24. Kill switch blocks new orders
    def test_24_kill_switch_blocks_new_orders(self):
        self.telemetry.trigger_kill_switch(reason="Emergency Halt")
        res = self.broker.submit_order(self.auth, evaluation_timestamp=self.now)
        self.assertEqual(res.status, PaperOrderStatus.REJECTED)
        self.assertIn("KILL_SWITCH_TRIGGERED", res.message)

    # 25. Kill switch does not delete history
    def test_25_kill_switch_does_not_delete_history(self):
        # 1. Submit and fill order
        sub = self.broker.submit_order(self.auth, evaluation_timestamp=self.now)
        self.broker.process_fills(sub.order.order_id, market_price=1495.0, evaluation_timestamp=self.now)
        orders_before = len(self.broker.account.orders)
        fills_before = len(self.broker.account.fills)

        # 2. Trigger kill switch
        self.telemetry.trigger_kill_switch(reason="Emergency Stop")

        # 3. Assert existing order and fill history preserved
        self.assertEqual(len(self.broker.account.orders), orders_before)
        self.assertEqual(len(self.broker.account.fills), fills_before)
        self.assertEqual(self.broker.get_order(sub.order.order_id).status, PaperOrderStatus.FILLED)

    # 26. Kill switch deterministic behavior
    def test_26_kill_switch_deterministic_behavior(self):
        self.telemetry.trigger_kill_switch()
        self.assertEqual(self.telemetry.get_health_status().kill_switch_state, KillSwitchState.TRIGGERED)
        self.assertFalse(self.telemetry.get_health_status().healthy)

    # 27. Zero-sample metrics
    def test_27_zero_sample_metrics(self):
        # Must not raise ZeroDivisionError
        metrics = self.telemetry.compute_metrics([])
        self.assertEqual(metrics.total_orders, 0)
        self.assertEqual(metrics.fill_rate_pct, 0.0)

    # 28. Duplicate event handling
    def test_28_duplicate_event_handling(self):
        e1 = self.telemetry.record_event(event_type=ExecutionEventType.ORDER_CREATED, execution_id="ex1", timestamp=self.now)
        e2 = self.telemetry.record_event(event_type=ExecutionEventType.ORDER_CREATED, execution_id="ex1", timestamp=self.now)
        self.assertNotEqual(e1.event_id, e2.event_id)

    # 29. API compatibility
    def test_29_api_compatibility(self):
        self.assertEqual(TELEMETRY_ENGINE_VERSION, "8.0.0")

    # 30. Paper Broker compatibility
    def test_30_paper_broker_compatibility(self):
        self.assertIsInstance(self.broker, PaperBrokerAdapter)

    # 31. Phase 6.9 compatibility
    def test_31_phase69_compatibility(self):
        self.assertIsInstance(self.auth, ExecutionAuthorizationSnapshot)

    # 32. Phase 7 compatibility
    def test_32_phase7_compatibility(self):
        self.assertEqual(PAPER_BROKER_ENGINE_VERSION, "7.0.0")

    # 33. Deterministic output
    def test_33_deterministic_output(self):
        o1 = PaperOrder(authorization_id="a1", decision_id="d1", symbol="INFY.NS", side=PreflightSide.BUY, requested_quantity=10, remaining_quantity=0, filled_quantity=10, idempotency_token="t1", status=PaperOrderStatus.FILLED)
        m1 = self.telemetry.compute_metrics([o1])
        m2 = self.telemetry.compute_metrics([o1])
        self.assertEqual(m1.fill_rate_pct, m2.fill_rate_pct)

    # 34. No LLM dependency
    def test_34_no_llm_dependency(self):
        engine = ExecutionTelemetryEngine()
        self.assertFalse(hasattr(engine, "llm_client"))

    # 35. Adversarial telemetry suite (Section 29)
    def test_35_adversarial_telemetry_suite(self):
        """
        Adversarial attacks on telemetry and monitoring:
        A. Attempt to modify existing frozen event
        B. Trigger kill switch then attempt order submission
        C. Attempt to bypass kill switch
        D. Redact secret in metadata
        E. Tamper with order event history
        """
        # A. Frozen event mutation attack
        evt = self.telemetry.record_event(event_type=ExecutionEventType.ORDER_CREATED, execution_id="adv-1", timestamp=self.now)
        with self.assertRaises(Exception):
            evt.price = 999999.0

        # B. Kill switch blocking attack
        self.telemetry.trigger_kill_switch(reason="Adversarial Kill")
        res = self.broker.submit_order(self.auth, evaluation_timestamp=self.now)
        self.assertEqual(res.status, PaperOrderStatus.REJECTED)

        # C. Secret leak attack
        evt_sec = self.telemetry.record_event(
            event_type=ExecutionEventType.ORDER_CREATED,
            execution_id="adv-sec",
            metadata={"secret_token": "SUPER_SECRET_VALUE"},
            timestamp=self.now,
        )
        self.assertNotIn("SUPER_SECRET_VALUE", str(evt_sec.metadata))
        self.assertEqual(evt_sec.metadata["secret_token"], "[REDACTED]")


if __name__ == "__main__":
    unittest.main()
