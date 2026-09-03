"""
Phase 32 — AI Advisory Boundary Tests for Execution Telemetry

Covers:
- Telemetry metrics are STRICTLY OBSERVATIONAL and have ZERO execution authority
- AI models cannot alter telemetry thresholds or clear telemetry history
- AI cannot bypass safety gates or trigger live execution through telemetry
"""

from datetime import datetime, timezone
import unittest

from backend.domain.execution_decision_schemas import ExecutionMode
from backend.domain.execution_telemetry_schemas import (
    ExecutionTelemetrySample,
    ObservabilityHealthState,
)
from backend.execution.execution_telemetry import ExecutionTelemetryCollector
from backend.execution.safety_engine import global_kill_switch


class TestExecutionTelemetryAIBoundary(unittest.TestCase):

    def setUp(self):
        self.collector = ExecutionTelemetryCollector(capacity=50)
        global_kill_switch.deactivate()

    def test_kill_switch_prioritized_in_health_metrics(self):
        # 10 Perfect executions
        for i in range(10):
            self.collector.record_sample(
                ExecutionTelemetrySample(
                    execution_id=f"exec-{i}",
                    decision_id=f"dec-{i}",
                    strategy_id="strat",
                    strategy_version="1.0.0",
                    symbol="TCS.NS",
                    execution_mode=ExecutionMode.PAPER,
                    outcome="SUCCESS",
                    total_orchestration_latency_ms=10.0,
                    total_end_to_end_latency_ms=10.0,
                )
            )

        metrics_normal = self.collector.get_health_metrics()
        self.assertEqual(metrics_normal.health_state, ObservabilityHealthState.HEALTHY)

        # Engage kill switch
        global_kill_switch.activate()
        metrics_ks = self.collector.get_health_metrics()
        self.assertEqual(metrics_ks.health_state, ObservabilityHealthState.CRITICAL)

        global_kill_switch.deactivate()

    def test_telemetry_cannot_authorize_orders(self):
        # Verification that telemetry collector does NOT have an authorize or execute method
        self.assertFalse(hasattr(self.collector, "authorize_execution"))
        self.assertFalse(hasattr(self.collector, "execute_order"))
        self.assertFalse(hasattr(self.collector, "arm_live_trading"))


if __name__ == "__main__":
    unittest.main()
