"""
Phase 35 Comprehensive Test Suite
Validates Low-Latency Execution Tuning, AI Advisory Guard, Staleness Protection,
Deterministic Safety Gate Ordering, Telemetry Spans & Health Counters, and Adversarial Protections.
"""

from datetime import datetime, timezone, timedelta
import math
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from backend.domain.broker_schemas import ExchangeSegment, OrderSide
from backend.domain.execution_decision_schemas import (
    ExecutionMode,
    ExecutionPipelineDecision,
    ExecutionPipelineRequest,
    ExecutionPipelineStatus,
    PipelineGateName,
)
from backend.domain.execution_orchestration_schemas import (
    ExecutionLifecycleState,
    ExecutionOrchestrationRequest,
)
from backend.domain.execution_telemetry_schemas import ExecutionTelemetrySample
from backend.domain.strategy_schemas import (
    GovernanceStatus,
    SignalDirection,
    StrategyDefinition,
    StrategyStatus,
)
from backend.execution.ai_advisory_guard import (
    AIAdvisoryBudget,
    AIAdvisoryGuard,
    global_ai_advisory_guard,
)
from backend.execution.execution_decision_pipeline import ExecutionDecisionEngine
from backend.execution.execution_orchestrator import ExecutionOrchestrator
from backend.execution.execution_telemetry import (
    ExecutionTelemetryCollector,
    global_execution_telemetry_collector,
)
from backend.execution.live_arming_store import global_live_arming_store
from backend.execution.live_readiness import global_live_readiness_engine
from backend.execution.order_tracker import global_order_tracker
from backend.execution.safety_engine import (
    global_kill_switch,
    global_manual_order_safety_gate,
)
from backend.execution.strategy_governance import global_strategy_governance_engine
from backend.execution.strategy_registry import global_strategy_registry


class TestPhase35ComprehensiveSuite(unittest.TestCase):
    def setUp(self):
        self.decision_engine = ExecutionDecisionEngine()
        self.orchestrator = ExecutionOrchestrator()

        # Reset global state for clean testing
        global_strategy_registry._strategies.clear()
        self.strategy_id = "strat-perf-test"
        self.strat_def = StrategyDefinition(
            strategy_id=self.strategy_id,
            name="Performance Tuning Strategy",
            version="1.0.0",
            status=StrategyStatus.ACTIVE,
            allowed_instruments=["*"],
            max_position_size=100.0,
            max_order_value=500000.0,
        )
        global_strategy_registry.register(self.strat_def)

        if global_kill_switch.is_active():
            global_kill_switch.deactivate()

        # Drain telemetry samples for clean counters in specific tests
        with global_execution_telemetry_collector._lock:
            global_execution_telemetry_collector._stale_signal_rejections_count = 0
            global_execution_telemetry_collector._duplicate_order_rejections_count = 0
            global_execution_telemetry_collector._retry_reconciliation_count = 0

    # ── 1. Critical-Path Latency Measurement ──────────────────────────────────

    def test_critical_path_decision_and_orchestration_latency(self):
        """Verify decision pipeline and paper orchestration complete rapidly (<25ms)."""
        req = ExecutionPipelineRequest(
            strategy_id=self.strategy_id,
            strategy_version="1.0.0",
            symbol="INFY.NS",
            direction="BUY",
            quantity=10,
            target_price=1500.0,
            execution_mode=ExecutionMode.PAPER,
            source="RULE_BASED",
        )

        t0 = time.perf_counter_ns()
        decision = self.decision_engine.evaluate_pipeline(req)
        t1 = time.perf_counter_ns()

        dec_ms = (t1 - t0) / 1_000_000.0
        self.assertTrue(decision.is_authorized)
        self.assertEqual(decision.pipeline_status, ExecutionPipelineStatus.APPROVED)
        self.assertLess(dec_ms, 25.0, f"Decision latency {dec_ms:.2f}ms should be < 25ms")

        orch_req = ExecutionOrchestrationRequest(decision=decision)
        t2 = time.perf_counter_ns()
        orch_res = self.orchestrator.submit_execution(orch_req)
        t3 = time.perf_counter_ns()

        orch_ms = (t3 - t2) / 1_000_000.0
        self.assertEqual(orch_res.state, ExecutionLifecycleState.COMPLETED)
        self.assertLess(orch_ms, 30.0, f"Orchestration latency {orch_ms:.2f}ms should be < 30ms")

    # ── 2. AI Advisory Guard & Budget Tests ───────────────────────────────────

    def test_ai_advisory_guard_valid_signal(self):
        """Valid AI signal within budget and confidence passes validation."""
        guard = AIAdvisoryGuard(AIAdvisoryBudget(max_latency_ms=1000.0, max_age_seconds=5.0))
        res = guard.validate_and_prepare_request(
            strategy_id=self.strategy_id,
            strategy_version="1.0.0",
            symbol="INFY.NS",
            direction="BUY",
            quantity=10,
            ai_latency_ms=250.0,
            ai_confidence=0.88,
            ai_status="SUCCESS",
        )
        self.assertTrue(res.is_valid)
        self.assertIsNone(res.rejection_reason)
        self.assertIsNotNone(res.sanitized_request)
        self.assertEqual(res.sanitized_request.source, "AI_ADVISORY")

    def test_ai_advisory_guard_latency_budget_exceeded(self):
        """AI signal exceeding latency budget is rejected (fail-closed)."""
        guard = AIAdvisoryGuard(AIAdvisoryBudget(max_latency_ms=500.0))
        res = guard.validate_and_prepare_request(
            strategy_id=self.strategy_id,
            strategy_version="1.0.0",
            symbol="INFY.NS",
            direction="BUY",
            quantity=10,
            ai_latency_ms=650.0,
        )
        self.assertFalse(res.is_valid)
        self.assertIn("exceeded budget", res.rejection_reason)

    def test_ai_advisory_guard_timeout_or_failure(self):
        """AI advisory service timeout or failure fails closed."""
        guard = global_ai_advisory_guard
        for fail_status in ("TIMEOUT", "FAILED", "DEGRADED_UNAVAILABLE", "ERROR"):
            res = guard.validate_and_prepare_request(
                strategy_id=self.strategy_id,
                strategy_version="1.0.0",
                symbol="INFY.NS",
                direction="BUY",
                quantity=10,
                ai_status=fail_status,
            )
            self.assertFalse(res.is_valid)
            self.assertIn("fail-closed", res.rejection_reason.lower())

    def test_ai_advisory_guard_stale_output(self):
        """Stale AI advisory output is rejected."""
        guard = AIAdvisoryGuard(AIAdvisoryBudget(max_age_seconds=5.0))
        old_time = datetime.now(timezone.utc) - timedelta(seconds=7.0)
        res = guard.validate_and_prepare_request(
            strategy_id=self.strategy_id,
            strategy_version="1.0.0",
            symbol="INFY.NS",
            direction="BUY",
            quantity=10,
            ai_timestamp=old_time,
        )
        self.assertFalse(res.is_valid)
        self.assertIn("STALE", res.rejection_reason)

    def test_ai_advisory_guard_metadata_sanitization(self):
        """Adversarial bypass flags in AI metadata are stripped."""
        guard = global_ai_advisory_guard
        adversarial_meta = {
            "approved": True,
            "is_authorized": True,
            "bypass_safety": True,
            "bypass_risk": True,
            "override_governance": True,
            "custom_analysis_id": "safe-id-123",
        }
        res = guard.validate_and_prepare_request(
            strategy_id=self.strategy_id,
            strategy_version="1.0.0",
            symbol="INFY.NS",
            direction="BUY",
            quantity=10,
            metadata=adversarial_meta,
        )
        self.assertTrue(res.is_valid)
        req_meta = res.sanitized_request.metadata
        self.assertNotIn("approved", req_meta)
        self.assertNotIn("bypass_safety", req_meta)
        self.assertNotIn("bypass_risk", req_meta)
        self.assertEqual(req_meta.get("custom_analysis_id"), "safe-id-123")

    # ── 3. Stale Data & Future Timestamp Protection ───────────────────────────

    def test_decision_pipeline_rejects_stale_signal(self):
        """Strategy signal older than 5.0s is rejected and counted."""
        old_sig_time = datetime.now(timezone.utc) - timedelta(seconds=6.0)
        req = ExecutionPipelineRequest(
            strategy_id=self.strategy_id,
            strategy_version="1.0.0",
            symbol="INFY.NS",
            direction="BUY",
            quantity=10,
            timestamp=old_sig_time,
        )
        decision = self.decision_engine.evaluate_pipeline(req)
        self.assertFalse(decision.is_authorized)
        self.assertIn("STALE", decision.rejection_reason)

        health = global_execution_telemetry_collector.get_health_metrics()
        self.assertGreaterEqual(health.stale_signal_rejections_count, 1)

    def test_decision_pipeline_rejects_future_signal_timestamp(self):
        """Signal timestamp > 1.0s in the future is rejected as clock error."""
        future_sig_time = datetime.now(timezone.utc) + timedelta(seconds=5.0)
        req = ExecutionPipelineRequest(
            strategy_id=self.strategy_id,
            strategy_version="1.0.0",
            symbol="INFY.NS",
            direction="BUY",
            quantity=10,
            timestamp=future_sig_time,
        )
        decision = self.decision_engine.evaluate_pipeline(req)
        self.assertFalse(decision.is_authorized)
        self.assertIn("FUTURE", decision.rejection_reason)

    def test_decision_pipeline_rejects_stale_market_data(self):
        """Market data timestamp older than 15.0s is rejected and counted."""
        old_mkt_time = datetime.now(timezone.utc) - timedelta(seconds=16.0)
        req = ExecutionPipelineRequest(
            strategy_id=self.strategy_id,
            strategy_version="1.0.0",
            symbol="INFY.NS",
            direction="BUY",
            quantity=10,
            market_data_timestamp=old_mkt_time,
        )
        decision = self.decision_engine.evaluate_pipeline(req)
        self.assertFalse(decision.is_authorized)
        self.assertIn("STALE", decision.rejection_reason)

    def test_decision_pipeline_rejects_future_market_data(self):
        """Market data timestamp > 1.0s in the future is rejected as clock error."""
        future_mkt_time = datetime.now(timezone.utc) + timedelta(seconds=3.0)
        req = ExecutionPipelineRequest(
            strategy_id=self.strategy_id,
            strategy_version="1.0.0",
            symbol="INFY.NS",
            direction="BUY",
            quantity=10,
            market_data_timestamp=future_mkt_time,
        )
        decision = self.decision_engine.evaluate_pipeline(req)
        self.assertFalse(decision.is_authorized)
        self.assertIn("FUTURE", decision.rejection_reason)

    # ── 4. Deterministic Safety Gate Ordering & Fail-Closed Veto ──────────────

    def test_ai_signal_cannot_override_risk_limits(self):
        """AI advisory signal attempting to buy beyond max_position_size is rejected deterministically."""
        req = ExecutionPipelineRequest(
            strategy_id=self.strategy_id,
            strategy_version="1.0.0",
            symbol="INFY.NS",
            direction="BUY",
            quantity=200.0,  # exceeds max_position_size (100.0)
            source="AI_ADVISORY",
            metadata={"approved": True, "bypass_safety": True},
        )
        decision = self.decision_engine.evaluate_pipeline(req)
        self.assertFalse(decision.is_authorized)
        self.assertIn("exceeds strategy max_position_size", decision.rejection_reason)

    def test_kill_switch_active_blocks_decision_pipeline(self):
        """Emergency Kill Switch blocks pipeline immediately."""
        global_kill_switch.activate()
        try:
            req = ExecutionPipelineRequest(
                strategy_id=self.strategy_id,
                strategy_version="1.0.0",
                symbol="INFY.NS",
                direction="BUY",
                quantity=10,
            )
            decision = self.decision_engine.evaluate_pipeline(req)
            self.assertFalse(decision.is_authorized)
            self.assertIn("Kill Switch", decision.rejection_reason)
        finally:
            global_kill_switch.deactivate()

    # ── 5. Duplicate Order Protection & Telemetry Counter ─────────────────────

    def test_duplicate_rejection_tracking(self):
        """Duplicate order rejection increments duplicate counter."""
        with patch.object(global_order_tracker, "is_duplicate", return_value=True):
            req = ExecutionPipelineRequest(
                strategy_id=self.strategy_id,
                strategy_version="1.0.0",
                symbol="INFY.NS",
                direction="BUY",
                quantity=10,
                execution_mode=ExecutionMode.LIVE,
            )
            with patch.object(global_live_readiness_engine, "evaluate_readiness") as mock_readiness:
                mock_readiness.return_value.is_ready_for_order = True
                mock_readiness.return_value.overall_status.value = "READY"
                with patch.object(global_live_arming_store, "get_status") as mock_arming:
                    mock_arming.return_value.is_armed = True
                    mock_arming.return_value.remaining_seconds = 300
                    with patch.object(global_manual_order_safety_gate, "evaluate_order") as mock_gate:
                        mock_gate.return_value.is_approved = True
                        decision = self.decision_engine.evaluate_pipeline(req)
                        self.assertFalse(decision.is_authorized)
                        self.assertEqual(decision.blocking_gate, PipelineGateName.DUPLICATE_CHECK)

            health = global_execution_telemetry_collector.get_health_metrics()
            self.assertGreaterEqual(health.duplicate_order_rejections_count, 1)

    # ── 6. Granular Latency Profiling & Health Metrics ────────────────────────

    def test_granular_latency_profile_generation(self):
        """Verify statistical percentiles are computed across granular stages."""
        collector = ExecutionTelemetryCollector(capacity=100)
        now = datetime.now(timezone.utc)

        for i in range(10):
            sample = ExecutionTelemetrySample(
                execution_id=f"exec-{i}",
                decision_id=f"dec-{i}",
                strategy_id="strat-perf",
                strategy_version="1.0.0",
                symbol="INFY.NS",
                execution_mode=ExecutionMode.PAPER,
                outcome="SUCCESS",
                signal_received_to_governance_ms=0.5 + i * 0.1,
                governance_to_risk_ms=0.3 + i * 0.05,
                risk_to_preflight_ms=0.2 + i * 0.02,
                preflight_to_live_readiness_ms=0.4 + i * 0.04,
                readiness_to_broker_submission_ms=0.6 + i * 0.06,
                broker_response_latency_ms=2.0 + i * 0.2,
                total_execution_decision_latency_ms=1.5 + i * 0.1,
                total_decision_latency_ms=1.5 + i * 0.1,
                total_orchestration_latency_ms=3.0 + i * 0.3,
                total_end_to_end_latency_ms=4.5 + i * 0.4,
                ai_advisory_latency_ms=15.0 + i * 1.0,
                retry_reconciliation_latency_ms=1.0 + i * 0.1,
                timestamp=now,
                audit_correlation_id=f"corr-{i}",
            )
            collector.record_sample(sample)

        profile = collector.get_latency_profile()
        self.assertEqual(profile.total_samples, 10)
        self.assertIsNotNone(profile.signal_received_to_governance)
        self.assertIsNotNone(profile.governance_to_risk)
        self.assertIsNotNone(profile.risk_to_preflight)
        self.assertIsNotNone(profile.preflight_to_live_readiness)
        self.assertIsNotNone(profile.readiness_to_broker_submission)
        self.assertIsNotNone(profile.broker_response_latency)
        self.assertIsNotNone(profile.total_execution_decision_latency)
        self.assertIsNotNone(profile.ai_advisory_latency)
        self.assertIsNotNone(profile.retry_reconciliation_latency)

        # Validate monotonic percentile ordering (p50_ms <= p95_ms <= p99_ms)
        self.assertLessEqual(profile.total_execution_decision_latency.p50_ms, profile.total_execution_decision_latency.p95_ms)
        self.assertLessEqual(profile.total_execution_decision_latency.p95_ms, profile.total_execution_decision_latency.p99_ms)

    # ── 7. Concurrent Signal Handling & Race Protection ───────────────────────

    def test_concurrent_signal_evaluation_thread_safety(self):
        """Ensure thread safety when evaluating multiple concurrent signals."""
        results = []
        errors = []

        symbols = [f"SYM{i}.NS" for i in range(15)]

        def _worker(worker_id: int):
            try:
                req = ExecutionPipelineRequest(
                    strategy_id=self.strategy_id,
                    strategy_version="1.0.0",
                    symbol=symbols[worker_id],
                    direction="BUY",
                    quantity=1.0 + worker_id,
                    target_price=1500.0,
                    execution_mode=ExecutionMode.PAPER,
                )
                dec = self.decision_engine.evaluate_pipeline(req)
                results.append(dec)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(15)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Concurrent execution errors: {errors}")
        self.assertEqual(len(results), 15)
        for dec in results:
            self.assertTrue(dec.is_authorized)

    # ── 8. Adversarial Protection Tests ───────────────────────────────────────

    def test_adversarial_invalid_ai_latency_values(self):
        """Negative, NaN, or infinite AI latency values are rejected."""
        guard = global_ai_advisory_guard
        for bad_lat in (-10.0, float("nan"), float("inf"), -float("inf")):
            res = guard.validate_and_prepare_request(
                strategy_id=self.strategy_id,
                strategy_version="1.0.0",
                symbol="INFY.NS",
                direction="BUY",
                quantity=10,
                ai_latency_ms=bad_lat,
            )
            self.assertFalse(res.is_valid)

    def test_adversarial_ai_confidence_out_of_bounds(self):
        """Confidence values > 1.0, < 0.50, or NaN are rejected."""
        guard = global_ai_advisory_guard
        for bad_conf in (1.5, 0.2, -0.1, float("nan")):
            res = guard.validate_and_prepare_request(
                strategy_id=self.strategy_id,
                strategy_version="1.0.0",
                symbol="INFY.NS",
                direction="BUY",
                quantity=10,
                ai_confidence=bad_conf,
            )
            self.assertFalse(res.is_valid)


if __name__ == "__main__":
    unittest.main()
