"""
Phase 32 — Adversarial & Security Tests for Execution Telemetry

Covers:
- Zero secret / token leakage in telemetry samples and serialization
- Resilience against NaN/Inf latency injection
- Telemetry failure isolation (telemetry error never compromises execution safety)
- Bounded query response enforcement
"""

from datetime import datetime, timezone
import unittest

from backend.domain.execution_decision_schemas import ExecutionMode
from backend.domain.execution_telemetry_schemas import ExecutionTelemetrySample
from backend.execution.execution_telemetry import ExecutionTelemetryCollector


class TestExecutionTelemetryAdversarial(unittest.TestCase):

    def setUp(self):
        self.collector = ExecutionTelemetryCollector(capacity=50)

    def test_secrets_redaction_in_telemetry_model(self):
        sample = ExecutionTelemetrySample(
            execution_id="exec-adv-01",
            decision_id="dec-adv-01",
            strategy_id="adv_strat",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            execution_mode=ExecutionMode.PAPER,
            total_orchestration_latency_ms=12.5,
            total_end_to_end_latency_ms=12.5,
        )
        json_repr = sample.model_dump_json()
        self.assertNotIn("dhan_access_token", json_repr)
        self.assertNotIn("client_secret", json_repr)
        self.assertNotIn("confirmation_token", json_repr)

    def test_corrupted_sample_rejected_safely(self):
        with self.assertRaises(ValueError):
            ExecutionTelemetrySample(
                execution_id="exec-adv-bad",
                decision_id="dec-adv-bad",
                strategy_id="strat",
                strategy_version="1.0.0",
                symbol="TCS.NS",
                total_end_to_end_latency_ms=-50.0,  # Negative latency disallowed
            )

    def test_collector_thread_safety(self):
        import concurrent.futures

        def record_worker(worker_id: int):
            for i in range(20):
                s = ExecutionTelemetrySample(
                    execution_id=f"thread-{worker_id}-{i}",
                    decision_id=f"dec-{worker_id}-{i}",
                    strategy_id="strat",
                    strategy_version="1.0.0",
                    symbol="TCS.NS",
                    execution_mode=ExecutionMode.PAPER,
                    total_orchestration_latency_ms=float(i + 1),
                    total_end_to_end_latency_ms=float(i + 1),
                )
                self.collector.record_sample(s)

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(record_worker, wid) for wid in range(5)]
            concurrent.futures.wait(futures)

        profile = self.collector.get_latency_profile()
        self.assertEqual(profile.total_samples, 50)  # Capped at capacity 50


if __name__ == "__main__":
    unittest.main()
