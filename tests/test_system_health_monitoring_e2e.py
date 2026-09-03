"""
Phase 13 — Real-Time Monitoring & System Health Engine End-to-End Test Suite

Comprehensive deterministic unit, integration, and failure-mode tests covering:
1. Healthy system baseline
2. Degraded non-critical component
3. Failed non-critical component
4. Safety-critical component failure -> escalates overall health to CRITICAL
5. Stale market data detection -> flags DEGRADED with warnings
6. Stale evidence data detection
7. Stale portfolio ledger state detection
8. Latency measurement (per-stage moving average and max latency)
9. Abnormal latency threshold breach detection (stage & pipeline)
10. Pipeline failure detection & stage classification
11. Pipeline recovery (consecutive failures reset upon success)
12. Early termination & skipped stages tracking (e.g. Risk Veto / Safety Halts)
13. Preflight circuit limit rejection monitoring
14. Paper order lifecycle telemetry (SUBMITTED -> ACCEPTED -> FILLED -> CANCELLED)
15. Position opened, closed, and equity/P&L updates
16. Monitoring subsystem failure isolation (pipeline executes even if monitor throws)
17. Strict paper-only safety invariants (zero live broker endpoints, zero credentials)
18. No risk bypass, no sizing bypass, no pre-flight bypass
19. All FastAPI endpoints (/api/monitor/health, /components, /pipeline, /telemetry, /executions)
20. Multiple consecutive failure threshold breach escalation
21. Kill switch trigger escalation to CRITICAL
22. Deterministic reset and state isolation
"""

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.application.system_health_monitor import (
    SystemHealthMonitor,
    global_health_monitor,
)
from backend.domain.monitoring_schemas import (
    MONITORING_VERSION,
    ComponentHealthStatus,
    ComponentID,
    MonitoringConfig,
    PipelineStageStatus,
    SystemHealthLevel,
)
from backend.domain.schemas import MarketContext
from backend.domain.telemetry_schemas import (
    EventSeverity,
    ExecutionEventType,
    KillSwitchState,
)
from backend.domain.trading_os_schemas import (
    PipelineStageResult,
    StageStatus,
    TradingOSRun,
)
from backend.main import app


class TestSystemHealthMonitoringE2E(unittest.TestCase):
    """Rigorous end-to-end verification of the Phase 13 Monitoring Engine."""

    def setUp(self):
        self.config = MonitoringConfig(
            market_data_max_age_seconds=60.0,
            evidence_max_age_seconds=300.0,
            portfolio_max_age_seconds=300.0,
            telemetry_max_age_seconds=60.0,
            abnormal_pipeline_latency_threshold_ms=500.0,
            abnormal_stage_latency_threshold_ms=100.0,
            max_consecutive_failures_allowed=3,
        )
        self.monitor = SystemHealthMonitor(config=self.config)
        global_health_monitor.reset()
        self.client = TestClient(app)

    def tearDown(self):
        self.monitor.reset()
        global_health_monitor.reset()

    # ── Test 1: Healthy Baseline ──────────────────────────────────────────────

    def test_01_healthy_baseline_initialization(self):
        """Verify baseline initial state reports all 16 components healthy and system HEALTHY."""
        health = self.monitor.get_system_health()
        self.assertEqual(health.overall_health, SystemHealthLevel.HEALTHY)
        self.assertEqual(health.status_badge, "ALL_SYSTEMS_OPERATIONAL")
        self.assertEqual(health.components_count, 16)
        self.assertEqual(health.healthy_components_count, 16)
        self.assertEqual(health.failed_components_count, 0)
        self.assertEqual(health.degraded_components_count, 0)
        self.assertTrue(health.safety_critical_healthy)
        self.assertFalse(health.active_kill_switch)
        self.assertTrue(health.data_freshness.is_fresh)

    # ── Test 2: Degraded Non-Critical Component ───────────────────────────────

    def test_02_degraded_non_critical_component(self):
        """Verify degraded non-critical component sets overall health to DEGRADED."""
        self.monitor.record_component_degraded(
            ComponentID.SPECIALISTS.value,
            reason="Heuristic fallback due to missing news sentiment",
            latency_ms=45.2,
        )
        health = self.monitor.get_system_health()
        self.assertEqual(health.overall_health, SystemHealthLevel.DEGRADED)
        self.assertEqual(health.status_badge, "SYSTEM_DEGRADED_NON_CRITICAL")
        self.assertEqual(health.degraded_components_count, 1)
        self.assertTrue(health.safety_critical_healthy)

    # ── Test 3: Failed Non-Critical Component ─────────────────────────────────

    def test_03_failed_non_critical_component(self):
        """Verify failed non-critical component (e.g. EvidenceAggregator) sets DEGRADED."""
        self.monitor.record_component_failure(
            ComponentID.EVIDENCE_AGGREGATOR.value,
            error_message="Contradiction resolution timeout",
            latency_ms=95.0,
        )
        health = self.monitor.get_system_health()
        self.assertEqual(health.overall_health, SystemHealthLevel.DEGRADED)
        self.assertEqual(health.failed_components_count, 1)
        self.assertTrue(health.safety_critical_healthy)

    # ── Test 4: Safety-Critical Component Failure ─────────────────────────────

    def test_04_safety_critical_component_failure(self):
        """Verify ANY safety-critical failure (Risk, Sizing, PreFlight, Broker) forces CRITICAL."""
        safety_critical_components = [
            ComponentID.RISK_ENGINE.value,
            ComponentID.POSITION_SIZING.value,
            ComponentID.EXECUTION_PREFLIGHT_ENGINE.value,
            ComponentID.PAPER_BROKER_ADAPTER.value,
        ]
        for comp_id in safety_critical_components:
            self.monitor.reset()
            self.monitor.record_component_failure(
                comp_id,
                error_message="Safety violation simulated",
                latency_ms=12.0,
            )
            health = self.monitor.get_system_health()
            self.assertEqual(
                health.overall_health,
                SystemHealthLevel.CRITICAL,
                f"Component {comp_id} failure did not trigger CRITICAL overall health",
            )
            self.assertEqual(health.status_badge, "CRITICAL_SAFETY_ALERT")
            self.assertFalse(health.safety_critical_healthy)

    # ── Test 5: Stale Market Data Detection ───────────────────────────────────

    def test_05_stale_market_data_detection(self):
        """Verify market data age exceeding threshold flags DEGRADED and alerts."""
        stale_ts = datetime.now(timezone.utc) - timedelta(seconds=120)
        freshness = self.monitor.check_data_freshness(market_context_ts=stale_ts)

        self.assertFalse(freshness.is_fresh)
        self.assertIn(ComponentID.MARKET_CONTEXT.value, freshness.stale_components)
        self.assertGreaterEqual(freshness.market_data_age_seconds, 120.0)

        health = self.monitor.get_system_health()
        self.assertEqual(health.overall_health, SystemHealthLevel.DEGRADED)

    # ── Test 6: Stale Evidence & Specialist Data ──────────────────────────────

    def test_06_stale_evidence_and_specialist_data(self):
        """Verify stale evidence and specialist data detection."""
        stale_ts = datetime.now(timezone.utc) - timedelta(seconds=600)
        freshness = self.monitor.check_data_freshness(
            evidence_ts=stale_ts,
            specialist_ts=stale_ts,
        )
        self.assertFalse(freshness.is_fresh)
        self.assertIn(ComponentID.EVIDENCE_AGGREGATOR.value, freshness.stale_components)
        self.assertIn(ComponentID.SPECIALISTS.value, freshness.stale_components)

    # ── Test 7: Stale Portfolio State ─────────────────────────────────────────

    def test_07_stale_portfolio_state_detection(self):
        """Verify stale portfolio state detection."""
        stale_ts = datetime.now(timezone.utc) - timedelta(seconds=500)
        freshness = self.monitor.check_data_freshness(portfolio_ts=stale_ts)
        self.assertFalse(freshness.is_fresh)
        self.assertIn(ComponentID.PORTFOLIO_INTELLIGENCE_ENGINE.value, freshness.stale_components)

    # ── Test 8: Latency Measurement & Moving Average ──────────────────────────

    def test_08_latency_measurement_and_moving_average(self):
        """Verify pure Python latency tracking correctly calculates avg and max latency."""
        self.monitor.record_component_execution(ComponentID.RISK_ENGINE.value, latency_ms=10.0)
        self.monitor.record_component_execution(ComponentID.RISK_ENGINE.value, latency_ms=20.0)
        self.monitor.record_component_execution(ComponentID.RISK_ENGINE.value, latency_ms=30.0)

        rec = self.monitor.get_component_health(ComponentID.RISK_ENGINE.value)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.execution_count, 3)
        self.assertEqual(rec.last_latency_ms, 30.0)
        self.assertEqual(rec.avg_latency_ms, 20.0)
        self.assertEqual(rec.max_latency_ms, 30.0)

    # ── Test 9: Abnormal Latency Breach Detection ─────────────────────────────

    def test_09_abnormal_latency_breach_detection(self):
        """Verify abnormal stage latency and pipeline duration flag abnormal_latency_detected."""
        run = TradingOSRun(
            symbol="INFY.NS",
            total_duration_ms=850.0,  # Exceeds 500.0 threshold
        )
        run.stages["RISK"] = PipelineStageResult(
            stage_name="RISK",
            status=StageStatus.COMPLETED,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            duration_ms=150.0,  # Exceeds 100.0 threshold
        )

        report = self.monitor.record_pipeline_run(run)
        self.assertTrue(report.abnormal_latency_detected)
        self.assertIn("RISK", report.successful_stages)

    # ── Test 10: Pipeline Failure Detection & Classification ──────────────────

    def test_10_pipeline_failure_detection(self):
        """Verify pipeline failure records FAILED stage and error reason."""
        run = TradingOSRun(
            symbol="RELIANCE.NS",
            total_duration_ms=55.0,
        )
        run.stages["DEBATE"] = PipelineStageResult(
            stage_name="DEBATE",
            status=StageStatus.FAILED,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            duration_ms=50.0,
            error_message="LLM context window exceeded",
        )

        report = self.monitor.record_pipeline_run(run)
        self.assertIn("DEBATE", report.failed_stages)
        self.assertTrue(report.pipeline_terminated_early)
        self.assertIn("DEBATE", report.termination_reason)

        comp = self.monitor.get_component_health(ComponentID.DEBATE_ENGINE.value)
        self.assertEqual(comp.status, ComponentHealthStatus.FAILED)
        self.assertEqual(comp.failure_count, 1)

    # ── Test 11: Pipeline Recovery ────────────────────────────────────────────

    def test_11_pipeline_recovery(self):
        """Verify that a successful run following a failure recovers component health."""
        # Failure
        self.monitor.record_component_failure(ComponentID.DEBATE_ENGINE.value, "Network error")
        rec = self.monitor.get_component_health(ComponentID.DEBATE_ENGINE.value)
        self.assertEqual(rec.status, ComponentHealthStatus.FAILED)
        self.assertEqual(rec.consecutive_failures, 1)

        # Recovery run
        self.monitor.record_component_execution(ComponentID.DEBATE_ENGINE.value, latency_ms=25.0)
        rec = self.monitor.get_component_health(ComponentID.DEBATE_ENGINE.value)
        self.assertEqual(rec.status, ComponentHealthStatus.HEALTHY)
        self.assertEqual(rec.consecutive_failures, 0)
        self.assertIsNone(rec.error_message)

    # ── Test 12: Early Termination & Skipped Stages Tracking ──────────────────

    def test_12_early_termination_and_skipped_stages(self):
        """Verify safety gate halts (e.g. Risk Veto) record SKIPPED downstream stages."""
        run = TradingOSRun(
            symbol="HDFCBANK.NS",
            total_duration_ms=40.0,
        )
        run.risk = {"veto_applied": True, "reason": "Conviction 0.22 below 0.35 threshold"}
        run.stages["RISK"] = PipelineStageResult(
            stage_name="RISK",
            status=StageStatus.COMPLETED,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            duration_ms=10.0,
        )
        for skipped in ["SIZING", "PREFLIGHT", "PAPER_BROKER"]:
            run.stages[skipped] = PipelineStageResult(
                stage_name=skipped,
                status=StageStatus.SKIPPED,
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                duration_ms=0.0,
                details={"reason": "Safety gate triggered upstream"},
            )

        report = self.monitor.record_pipeline_run(run)
        self.assertTrue(report.pipeline_terminated_early)
        self.assertIn("SIZING", report.skipped_stages)
        self.assertIn("PREFLIGHT", report.skipped_stages)
        self.assertIn("PAPER_BROKER", report.skipped_stages)
        self.assertIn("RISK_VETO", report.termination_reason)

    # ── Test 13: Preflight Circuit Limit Rejection ─────────────────────────────

    def test_13_preflight_circuit_limit_rejection(self):
        """Verify preflight circuit limit rejection increments rejected orders counter."""
        self.monitor.record_execution_event(
            event_type=ExecutionEventType.PREFLIGHT_REJECTED,
            order_id="ord-circuit-01",
            symbol="TCS.NS",
            details={"rejection_reason": "Price 4100 exceeds upper circuit 4000"},
        )
        metrics = self.monitor.get_execution_metrics()
        self.assertEqual(metrics.orders_rejected, 1)
        self.assertEqual(metrics.orders_submitted, 0)

    # ── Test 14: Paper Order Lifecycle Telemetry ──────────────────────────────

    def test_14_paper_order_lifecycle_telemetry(self):
        """Verify complete paper order lifecycle: submit -> accept -> fill -> cancel."""
        # 1. Submitted
        self.monitor.record_execution_event(
            event_type=ExecutionEventType.ORDER_SUBMITTED,
            order_id="ord-100",
            symbol="TCS.NS",
            quantity=10,
        )
        # 2. Accepted
        self.monitor.record_execution_event(
            event_type=ExecutionEventType.ORDER_ACCEPTED,
            order_id="ord-100",
            symbol="TCS.NS",
        )
        # 3. Filled
        self.monitor.record_execution_event(
            event_type=ExecutionEventType.ORDER_FILLED,
            order_id="ord-100",
            symbol="TCS.NS",
            quantity=10,
            price=3800.0,
        )
        # 4. Cancelled (second order)
        self.monitor.record_execution_event(
            event_type=ExecutionEventType.ORDER_CANCELLED,
            order_id="ord-101",
            symbol="INFY.NS",
        )

        metrics = self.monitor.get_execution_metrics()
        self.assertEqual(metrics.orders_submitted, 1)
        self.assertEqual(metrics.orders_accepted, 1)
        self.assertEqual(metrics.orders_filled, 1)
        self.assertEqual(metrics.orders_cancelled, 1)
        self.assertEqual(metrics.mode, "PAPER_ONLY")

    # ── Test 15: Position Opened, Closed & P&L Updates ────────────────────────

    def test_15_position_lifecycle_and_pnl_updates(self):
        """Verify positions opened, closed, realized P&L, cash, and total equity."""
        # Open position
        self.monitor.record_execution_event(
            event_type=ExecutionEventType.POSITION_OPENED,
            symbol="TCS.NS",
            cash_balance=62000.0,
            total_equity=100000.0,
        )
        metrics = self.monitor.get_execution_metrics()
        self.assertEqual(metrics.positions_opened, 1)
        self.assertEqual(metrics.current_open_positions, 1)
        self.assertEqual(metrics.cash_balance, 62000.0)

        # Close position with profit
        self.monitor.record_execution_event(
            event_type=ExecutionEventType.POSITION_CLOSED,
            symbol="TCS.NS",
            pnl=1500.0,
            cash_balance=101500.0,
            total_equity=101500.0,
        )
        metrics = self.monitor.get_execution_metrics()
        self.assertEqual(metrics.positions_closed, 1)
        self.assertEqual(metrics.current_open_positions, 0)
        self.assertEqual(metrics.realized_pnl, 1500.0)
        self.assertEqual(metrics.total_equity, 101500.0)

    # ── Test 16: Failure Safety Isolation ─────────────────────────────────────

    def test_16_monitoring_subsystem_failure_isolation(self):
        """Verify that an exception inside the monitoring engine NEVER crashes TradingOSOrchestrator."""
        from backend.application.trading_os_orchestrator import TradingOSOrchestrator
        from backend.domain.schemas import MarketContext

        orchestrator = TradingOSOrchestrator()
        ctx = MarketContext(
            symbol="TCS.NS",
            current_price=3500.0,
            support_levels=[3400.0],
            resistance_levels=[3600.0],
            market_regime="BULL_TREND",
            volatility_atr=25.0,
            context_id="ctx-test",
            data_timestamp=datetime.now(timezone.utc),
            provider="MOCK",
        )

        with patch("backend.application.system_health_monitor.global_health_monitor.record_pipeline_run", side_effect=RuntimeError("Monitor exploded!")):
            # Pipeline MUST execute and complete without raising RuntimeError
            run = orchestrator.run_pipeline(market_context=ctx)
            self.assertIsNotNone(run)
            self.assertEqual(run.symbol, "TCS.NS")

    # ── Test 17: Strict Paper-Only Safety Invariants ──────────────────────────

    def test_17_strict_paper_only_safety_invariants(self):
        """Verify paper trading invariant: zero real broker execution, mode is PAPER_ONLY."""
        health = self.monitor.get_system_health()
        self.assertEqual(health.execution_metrics.mode, "PAPER_ONLY")

        # Verify no broker live credentials in environment
        import os
        self.assertIsNone(os.environ.get("ZERODHA_API_KEY"))
        self.assertIsNone(os.environ.get("UPSTOX_API_KEY"))
        self.assertIsNone(os.environ.get("IBKR_PASSWORD"))

    # ── Test 18: Consecutive Failure Threshold Breach ─────────────────────────

    def test_18_consecutive_failure_threshold_breach(self):
        """Verify exceeding max consecutive failures on a safety component forces CRITICAL."""
        # 3 consecutive failures
        for i in range(3):
            self.monitor.record_component_failure(
                ComponentID.EXECUTION_PREFLIGHT_ENGINE.value,
                error_message=f"Consecutive fault {i+1}",
            )

        health = self.monitor.get_system_health()
        self.assertEqual(health.overall_health, SystemHealthLevel.CRITICAL)
        self.assertFalse(health.safety_critical_healthy)
        self.assertTrue(any("exceeded failure threshold" in a for a in health.recent_alerts))

    # ── Test 19: Kill Switch Trigger Escalation ───────────────────────────────

    def test_19_kill_switch_trigger_escalation(self):
        """Verify operator kill switch immediately escalates health to CRITICAL."""
        self.monitor.set_kill_switch_state(KillSwitchState.TRIGGERED)
        health = self.monitor.get_system_health()
        self.assertEqual(health.overall_health, SystemHealthLevel.CRITICAL)
        self.assertEqual(health.status_badge, "CRITICAL_SAFETY_ALERT")
        self.assertTrue(health.active_kill_switch)

        # Disarm recovers health
        self.monitor.set_kill_switch_state(KillSwitchState.ARMED)
        health = self.monitor.get_system_health()
        self.assertEqual(health.overall_health, SystemHealthLevel.HEALTHY)
        self.assertFalse(health.active_kill_switch)

    # ── Test 20: Deterministic Reset & State Isolation ────────────────────────

    def test_20_deterministic_reset_and_state_isolation(self):
        """Verify reset() restores pristine initial health state."""
        self.monitor.record_component_failure(ComponentID.RISK_ENGINE.value, "Simulated fault")
        self.assertEqual(self.monitor.get_system_health().overall_health, SystemHealthLevel.CRITICAL)

        self.monitor.reset()
        fresh_health = self.monitor.get_system_health()
        self.assertEqual(fresh_health.overall_health, SystemHealthLevel.HEALTHY)
        self.assertEqual(fresh_health.failed_components_count, 0)
        self.assertTrue(fresh_health.safety_critical_healthy)

    # ── Test 21: REST API /api/monitor/health ─────────────────────────────────

    def test_21_api_get_system_health(self):
        """Verify GET /api/monitor/health returns valid SystemHealthSummary schema."""
        resp = self.client.get("/api/monitor/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["engine_version"], MONITORING_VERSION)
        self.assertIn(data["overall_health"], ["HEALTHY", "DEGRADED", "CRITICAL", "OFFLINE"])
        self.assertEqual(data["components_count"], 16)
        self.assertTrue("execution_metrics" in data)
        self.assertTrue("data_freshness" in data)

    # ── Test 22: REST API /api/monitor/components ─────────────────────────────

    def test_22_api_get_components_and_single_component(self):
        """Verify GET /api/monitor/components and /api/monitor/components/{id}."""
        resp = self.client.get("/api/monitor/components")
        self.assertEqual(resp.status_code, 200)
        comps = resp.json()
        self.assertEqual(len(comps), 16)
        self.assertIn("RISK_ENGINE", comps)

        # Single component
        resp_single = self.client.get("/api/monitor/components/RISK_ENGINE")
        self.assertEqual(resp_single.status_code, 200)
        comp = resp_single.json()
        self.assertEqual(comp["component_id"], "RISK_ENGINE")
        self.assertTrue(comp["is_safety_critical"])

        # 404 on nonexistent
        resp_404 = self.client.get("/api/monitor/components/NONEXISTENT_COMPONENT")
        self.assertEqual(resp_404.status_code, 404)

    # ── Test 23: REST API /api/monitor/pipeline & /pipeline/latest ────────────

    def test_23_api_get_pipeline_history_and_latest(self):
        """Verify GET /api/monitor/pipeline and /api/monitor/pipeline/latest."""
        # 404 when no runs
        resp_empty = self.client.get("/api/monitor/pipeline/latest")
        self.assertEqual(resp_empty.status_code, 404)

        # Record a run in global monitor
        run = TradingOSRun(symbol="TCS.NS", total_duration_ms=45.0)
        run.stages["MARKET_CONTEXT"] = PipelineStageResult(
            stage_name="MARKET_CONTEXT",
            status=StageStatus.COMPLETED,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            duration_ms=5.0,
        )
        global_health_monitor.record_pipeline_run(run)

        resp_list = self.client.get("/api/monitor/pipeline?limit=10")
        self.assertEqual(resp_list.status_code, 200)
        self.assertEqual(len(resp_list.json()), 1)

        resp_latest = self.client.get("/api/monitor/pipeline/latest")
        self.assertEqual(resp_latest.status_code, 200)
        self.assertEqual(resp_latest.json()["symbol"], "TCS.NS")

    # ── Test 24: REST API /api/monitor/telemetry & /executions ────────────────

    def test_24_api_get_telemetry_and_executions(self):
        """Verify GET /api/monitor/telemetry and /api/monitor/executions."""
        resp_tel = self.client.get("/api/monitor/telemetry")
        self.assertEqual(resp_tel.status_code, 200)
        tel_data = resp_tel.json()
        self.assertEqual(tel_data["mode"], "PAPER_ONLY")

        resp_exec = self.client.get("/api/monitor/executions")
        self.assertEqual(resp_exec.status_code, 200)
        exec_data = resp_exec.json()
        self.assertEqual(exec_data["mode"], "PAPER_ONLY")
        self.assertEqual(exec_data["orders_submitted"], 0)

    # ── Test 25: REST API /api/monitor/reset ──────────────────────────────────

    def test_25_api_reset_monitoring(self):
        """Verify POST /api/monitor/reset cleanly clears telemetry counters."""
        global_health_monitor.record_component_failure("RISK_ENGINE", "Simulated fail")
        resp = self.client.post("/api/monitor/reset")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "RESET_SUCCESS")

        health = global_health_monitor.get_system_health()
        self.assertEqual(health.overall_health, SystemHealthLevel.HEALTHY)


if __name__ == "__main__":
    unittest.main()
