"""
Phase 31 — Live Path Fail-Closed Tests for Execution Orchestration

Covers:
- Live execution path gating and fail-closed validation
- Rejection when LIVE_EXECUTION_ENABLED is False
- Rejection when Live arming is missing or disarmed
- Rejection when confirmation token is missing or invalid
- Rejection when live readiness check fails
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
from backend.execution.live_arming_store import global_live_arming_store


class TestExecutionOrchestrationLivePath(unittest.TestCase):

    def setUp(self):
        self.orchestrator = ExecutionOrchestrator()
        global_strategy_registry.clear()
        global_live_arming_store.disarm()

        # Register active strategy
        self.strat = StrategyDefinition(
            strategy_id="live_test_strat",
            name="Live Test Strategy",
            version="1.0.0",
            status=StrategyStatus.ACTIVE,
            allowed_instruments=["TCS.NS"],
            allowed_exchanges=["NSE"],
            max_position_size=50.0,
            max_order_value=250000.0,
        )
        global_strategy_registry.register(self.strat)

    def test_live_path_rejected_by_default_when_disabled(self):
        now = datetime.now(timezone.utc)
        decision = ExecutionPipelineDecision(
            decision_id="dec-live-01",
            execution_mode=ExecutionMode.LIVE,
            pipeline_status=ExecutionPipelineStatus.APPROVED,
            is_authorized=True,
            strategy_id="live_test_strat",
            strategy_version="1.0.0",
            signal_fingerprint="sig-fp-live",
            symbol="TCS.NS",
            exchange="NSE",
            direction="BUY",
            quantity=10.0,
            estimated_value=35000.0,
            timestamp=now,
        )
        req = ExecutionOrchestrationRequest(decision=decision, confirmation_token="dummy-tok")

        result = self.orchestrator.submit_execution(req, current_time=now)
        self.assertEqual(result.state, ExecutionLifecycleState.REJECTED)
        self.assertIn("Automated AI live execution is permanently blocked in Phase 42", result.rejection_reason)

    def test_live_path_rejected_when_confirmation_token_missing(self):
        now = datetime.now(timezone.utc)
        decision = ExecutionPipelineDecision(
            decision_id="dec-live-02",
            execution_mode=ExecutionMode.LIVE,
            pipeline_status=ExecutionPipelineStatus.APPROVED,
            is_authorized=True,
            strategy_id="live_test_strat",
            strategy_version="1.0.0",
            signal_fingerprint="sig-fp-live-2",
            symbol="TCS.NS",
            exchange="NSE",
            direction="BUY",
            quantity=10.0,
            estimated_value=35000.0,
            timestamp=now,
        )
        req = ExecutionOrchestrationRequest(decision=decision, confirmation_token=None)

        result = self.orchestrator.submit_execution(req, current_time=now)
        self.assertEqual(result.state, ExecutionLifecycleState.REJECTED)


if __name__ == "__main__":
    unittest.main()
