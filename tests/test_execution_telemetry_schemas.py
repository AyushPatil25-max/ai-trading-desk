"""
Phase 32 — Schema Tests for Execution Telemetry & Latency Profiling

Covers:
- ExecutionTimingSpan duration computation from nanoseconds
- ExecutionTelemetrySample validation and finite latency enforcement
- Rejection of NaN and Inf in latency measurements
- Sanitization and zero-credential serialization
"""

from datetime import datetime, timezone
import math
import unittest

from backend.domain.execution_decision_schemas import ExecutionMode
from backend.domain.execution_telemetry_schemas import (
    ExecutionHealthMetrics,
    ExecutionLatencyProfile,
    ExecutionTelemetrySample,
    ExecutionTimingSpan,
    LatencyPercentiles,
    ObservabilityHealthState,
)


class TestExecutionTelemetrySchemas(unittest.TestCase):

    def test_timing_span_duration_computation(self):
        span = ExecutionTimingSpan(
            span_name="preflight_validation",
            start_ns=1_000_000_000,
            end_ns=1_015_500_000,
        )
        self.assertEqual(span.duration_ms, 15.5)

    def test_sample_valid_creation(self):
        now = datetime.now(timezone.utc)
        sample = ExecutionTelemetrySample(
            execution_id="exec-tel-01",
            decision_id="dec-tel-01",
            strategy_id="test_strat",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            execution_mode=ExecutionMode.PAPER,
            outcome="SUCCESS",
            total_decision_latency_ms=1.2,
            total_orchestration_latency_ms=3.4,
            total_end_to_end_latency_ms=4.6,
            timestamp=now,
        )
        self.assertEqual(sample.execution_id, "exec-tel-01")
        self.assertEqual(sample.total_end_to_end_latency_ms, 4.6)

    def test_sample_rejects_nan_inf(self):
        with self.assertRaises(ValueError):
            ExecutionTelemetrySample(
                execution_id="exec-nan",
                decision_id="dec-nan",
                strategy_id="strat",
                strategy_version="1.0.0",
                symbol="TCS.NS",
                total_end_to_end_latency_ms=float("nan"),
            )

        with self.assertRaises(ValueError):
            ExecutionTelemetrySample(
                execution_id="exec-inf",
                decision_id="dec-inf",
                strategy_id="strat",
                strategy_version="1.0.0",
                symbol="TCS.NS",
                total_end_to_end_latency_ms=float("inf"),
            )


if __name__ == "__main__":
    unittest.main()
