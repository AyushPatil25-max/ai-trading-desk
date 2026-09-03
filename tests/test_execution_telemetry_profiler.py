"""
Phase 32 — Profiler Tests for Latency Percentiles & Bounded Retention

Covers:
- Pure-Python percentiles calculation (p50, p90, p95, p99, min, max, mean, std_dev)
- Small sample size handling (0, 1, and 5 samples)
- Bounded ring buffer memory enforcement
- Mode filtering (PAPER vs LIVE)
"""

from datetime import datetime, timezone
import unittest

from backend.domain.execution_decision_schemas import ExecutionMode
from backend.domain.execution_telemetry_schemas import ExecutionTelemetrySample
from backend.execution.execution_telemetry import (
    ExecutionTelemetryCollector,
    compute_percentiles,
)


class TestExecutionTelemetryProfiler(unittest.TestCase):

    def setUp(self):
        self.collector = ExecutionTelemetryCollector(capacity=50)

    def test_compute_percentiles_empty(self):
        pct = compute_percentiles([])
        self.assertEqual(pct.count, 0)
        self.assertEqual(pct.p50_ms, 0.0)
        self.assertEqual(pct.p99_ms, 0.0)

    def test_compute_percentiles_single_sample(self):
        pct = compute_percentiles([42.5])
        self.assertEqual(pct.count, 1)
        self.assertEqual(pct.min_ms, 42.5)
        self.assertEqual(pct.max_ms, 42.5)
        self.assertEqual(pct.p50_ms, 42.5)
        self.assertEqual(pct.p99_ms, 42.5)

    def test_compute_percentiles_distribution(self):
        # 10 values: 10, 20, 30, ..., 100
        values = [float(i * 10) for i in range(1, 11)]
        pct = compute_percentiles(values)
        self.assertEqual(pct.count, 10)
        self.assertEqual(pct.min_ms, 10.0)
        self.assertEqual(pct.max_ms, 100.0)
        self.assertEqual(pct.mean_ms, 55.0)
        self.assertEqual(pct.p50_ms, 55.0)

    def test_bounded_retention_capacity(self):
        # Insert 70 samples into a collector with capacity 50
        for i in range(70):
            sample = ExecutionTelemetrySample(
                execution_id=f"exec-{i}",
                decision_id=f"dec-{i}",
                strategy_id="strat_1",
                strategy_version="1.0.0",
                symbol="TCS.NS",
                execution_mode=ExecutionMode.PAPER,
                total_orchestration_latency_ms=float(i),
                total_end_to_end_latency_ms=float(i),
            )
            self.collector.record_sample(sample)

        recent = self.collector.get_recent_samples(limit=100)
        self.assertEqual(len(recent), 50)
        self.assertEqual(recent[-1].execution_id, "exec-69")
        self.assertEqual(recent[0].execution_id, "exec-20")

    def test_profile_mode_filtering(self):
        # 5 Paper, 5 Live
        for i in range(5):
            self.collector.record_sample(
                ExecutionTelemetrySample(
                    execution_id=f"exec-p-{i}",
                    decision_id=f"dec-p-{i}",
                    strategy_id="strat_1",
                    strategy_version="1.0.0",
                    symbol="TCS.NS",
                    execution_mode=ExecutionMode.PAPER,
                    total_orchestration_latency_ms=10.0,
                    total_end_to_end_latency_ms=10.0,
                )
            )
            self.collector.record_sample(
                ExecutionTelemetrySample(
                    execution_id=f"exec-l-{i}",
                    decision_id=f"dec-l-{i}",
                    strategy_id="strat_1",
                    strategy_version="1.0.0",
                    symbol="TCS.NS",
                    execution_mode=ExecutionMode.LIVE,
                    total_orchestration_latency_ms=100.0,
                    total_end_to_end_latency_ms=100.0,
                )
            )

        paper_profile = self.collector.get_latency_profile(mode=ExecutionMode.PAPER)
        self.assertEqual(paper_profile.total_samples, 5)
        self.assertEqual(paper_profile.end_to_end_latency.mean_ms, 10.0)

        live_profile = self.collector.get_latency_profile(mode=ExecutionMode.LIVE)
        self.assertEqual(live_profile.total_samples, 5)
        self.assertEqual(live_profile.end_to_end_latency.mean_ms, 100.0)


if __name__ == "__main__":
    unittest.main()
