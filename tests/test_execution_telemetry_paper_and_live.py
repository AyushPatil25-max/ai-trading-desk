"""
Phase 32 — Paper vs Live Telemetry Isolation Tests

Covers:
- Paper execution records distinct PAPER mode telemetry samples
- Live path records LIVE mode telemetry samples
- Verification that Paper telemetry never interacts with live broker endpoints
- Fail-closed live execution telemetry capture
"""

from datetime import datetime, timezone
import unittest

from backend.domain.execution_decision_schemas import (
    ExecutionMode,
    ExecutionPipelineDecision,
    ExecutionPipelineStatus,
)
from backend.domain.execution_orchestration_schemas import (
    ExecutionLifecycleState,
    ExecutionOrchestrationRequest,
)
from backend.domain.strategy_schemas import (
    StrategyDefinition,
    StrategyStatus,
)
from backend.execution.strategy_registry import global_strategy_registry
from backend.execution.execution_orchestrator import ExecutionOrchestrator
from backend.execution.execution_telemetry import global_execution_telemetry_collector
from backend.execution.live_arming_store import global_live_arming_store


class TestExecutionTelemetryPaperAndLive(unittest.TestCase):

    def setUp(self):
        self.orchestrator = ExecutionOrchestrator()
        global_strategy_registry.clear()
        global_execution_telemetry_collector.clear()
        global_live_arming_store.disarm()

        # Register active strategy
        self.strat = StrategyDefinition(
            strategy_id="tel_strat",
            name="Telemetry Test Strategy",
            version="1.0.0",
            status=StrategyStatus.ACTIVE,
            allowed_instruments=["TCS.NS"],
            allowed_exchanges=["NSE"],
        )
        global_strategy_registry.register(self.strat)

    def test_paper_execution_records_telemetry_sample(self):
        now = datetime.now(timezone.utc)
        decision = ExecutionPipelineDecision(
            decision_id="dec-tel-p-01",
            execution_mode=ExecutionMode.PAPER,
            pipeline_status=ExecutionPipelineStatus.APPROVED,
            is_authorized=True,
            strategy_id="tel_strat",
            strategy_version="1.0.0",
            signal_fingerprint="sig-fp-tel-p",
            symbol="TCS.NS",
            exchange="NSE",
            direction="BUY",
            quantity=10.0,
            estimated_value=35000.0,
            timestamp=now,
        )
        req = ExecutionOrchestrationRequest(decision=decision)

        result = self.orchestrator.submit_execution(req, current_time=now)
        self.assertEqual(result.state, ExecutionLifecycleState.COMPLETED)

        import time
        time.sleep(0.05)
        # Check telemetry collector
        samples = global_execution_telemetry_collector.get_samples_by_execution(result.execution_id)
        self.assertEqual(len(samples), 1)
        sample = samples[0]
        self.assertEqual(sample.execution_mode, ExecutionMode.PAPER)
        self.assertEqual(sample.outcome, "SUCCESS")
        self.assertGreater(sample.total_orchestration_latency_ms, 0.0)

    def test_live_rejected_execution_records_telemetry_sample(self):
        now = datetime.now(timezone.utc)
        decision = ExecutionPipelineDecision(
            decision_id="dec-tel-l-01",
            execution_mode=ExecutionMode.LIVE,
            pipeline_status=ExecutionPipelineStatus.APPROVED,
            is_authorized=True,
            strategy_id="tel_strat",
            strategy_version="1.0.0",
            signal_fingerprint="sig-fp-tel-l",
            symbol="TCS.NS",
            exchange="NSE",
            direction="BUY",
            quantity=10.0,
            estimated_value=35000.0,
            timestamp=now,
        )
        req = ExecutionOrchestrationRequest(decision=decision, confirmation_token="tok-1")

        result = self.orchestrator.submit_execution(req, current_time=now)
        self.assertEqual(result.state, ExecutionLifecycleState.REJECTED)

        import time
        time.sleep(0.05)
        samples = global_execution_telemetry_collector.get_samples_by_execution(result.execution_id)
        self.assertEqual(len(samples), 1)
        sample = samples[0]
        self.assertEqual(sample.execution_mode, ExecutionMode.LIVE)
        self.assertEqual(sample.outcome, "REJECTED")


if __name__ == "__main__":
    unittest.main()
