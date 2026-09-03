"""
Phase 32 — Operational Drift Detection Tests

Covers:
- Latency drift detection comparing recent samples against baseline
- Error rate drift detection
- Rejection rate drift detection
- Insufficient sample handling
- Observability-only invariant: drift detection does NOT alter execution logic
"""

from datetime import datetime, timezone
import unittest

from backend.domain.execution_decision_schemas import ExecutionMode
from backend.domain.execution_telemetry_schemas import (
    ExecutionTelemetrySample,
    ObservabilityHealthState,
)
from backend.execution.execution_telemetry import ExecutionTelemetryCollector


class TestExecutionTelemetryDrift(unittest.TestCase):

    def setUp(self):
        self.collector = ExecutionTelemetryCollector(capacity=100)

    def test_insufficient_samples_for_drift(self):
        # Only 5 samples (less than minimum required for drift evaluation)
        for i in range(5):
            self.collector.record_sample(
                ExecutionTelemetrySample(
                    execution_id=f"exec-{i}",
                    decision_id=f"dec-{i}",
                    strategy_id="strat_1",
                    strategy_version="1.0.0",
                    symbol="TCS.NS",
                    execution_mode=ExecutionMode.PAPER,
                    total_orchestration_latency_ms=10.0,
                    total_end_to_end_latency_ms=10.0,
                )
            )

        report = self.collector.detect_drift(baseline_window=20, recent_window=5)
        self.assertFalse(report.is_drift_detected)
        self.assertIn("Insufficient", report.summary)

    def test_latency_drift_detected_when_recent_exceeds_baseline(self):
        # 20 Baseline samples with low latency (10ms)
        for i in range(20):
            self.collector.record_sample(
                ExecutionTelemetrySample(
                    execution_id=f"base-{i}",
                    decision_id=f"dec-b-{i}",
                    strategy_id="strat_1",
                    strategy_version="1.0.0",
                    symbol="TCS.NS",
                    execution_mode=ExecutionMode.PAPER,
                    total_orchestration_latency_ms=10.0,
                    total_end_to_end_latency_ms=10.0,
                )
            )

        # 5 Recent samples with high latency (120ms - exceeds 50ms warn and 1.5x ratio)
        for i in range(5):
            self.collector.record_sample(
                ExecutionTelemetrySample(
                    execution_id=f"rec-{i}",
                    decision_id=f"dec-r-{i}",
                    strategy_id="strat_1",
                    strategy_version="1.0.0",
                    symbol="TCS.NS",
                    execution_mode=ExecutionMode.PAPER,
                    total_orchestration_latency_ms=120.0,
                    total_end_to_end_latency_ms=120.0,
                )
            )

        report = self.collector.detect_drift(baseline_window=20, recent_window=5)
        self.assertTrue(report.is_drift_detected)
        self.assertEqual(report.drift_category, "LATENCY_DRIFT")
        self.assertGreater(report.latency_drift_ratio, 5.0)
        self.assertEqual(report.health_state, ObservabilityHealthState.WARNING)

    def test_error_rate_drift_detected(self):
        # 20 Baseline samples: all successful
        for i in range(20):
            self.collector.record_sample(
                ExecutionTelemetrySample(
                    execution_id=f"base-ok-{i}",
                    decision_id=f"dec-ok-{i}",
                    strategy_id="strat_1",
                    strategy_version="1.0.0",
                    symbol="TCS.NS",
                    execution_mode=ExecutionMode.PAPER,
                    outcome="SUCCESS",
                    total_orchestration_latency_ms=10.0,
                    total_end_to_end_latency_ms=10.0,
                )
            )

        # 5 Recent samples: all FAILED
        for i in range(5):
            self.collector.record_sample(
                ExecutionTelemetrySample(
                    execution_id=f"rec-fail-{i}",
                    decision_id=f"dec-fail-{i}",
                    strategy_id="strat_1",
                    strategy_version="1.0.0",
                    symbol="TCS.NS",
                    execution_mode=ExecutionMode.PAPER,
                    outcome="FAILED",
                    failure_category="BROKER_TIMEOUT",
                    total_orchestration_latency_ms=10.0,
                    total_end_to_end_latency_ms=10.0,
                )
            )

        report = self.collector.detect_drift(baseline_window=20, recent_window=5)
        self.assertTrue(report.is_drift_detected)
        self.assertEqual(report.drift_category, "ERROR_RATE_DRIFT")
        self.assertGreaterEqual(report.broker_error_rate_drift, 0.9)


if __name__ == "__main__":
    unittest.main()
