"""
Phase 31 — Control Plane Tests for Execution Orchestration

Covers:
- Control plane states: RUNNING, PAUSED, HALTED
- Pause and resume operations
- Emergency halt operations
- Kill switch priority override over control plane
"""

from datetime import datetime, timezone
import unittest

from backend.domain.execution_decision_schemas import (
    ExecutionMode,
    ExecutionPipelineDecision,
    ExecutionPipelineStatus,
)
from backend.domain.execution_orchestration_schemas import (
    ExecutionControlState,
    ExecutionLifecycleState,
    ExecutionOrchestrationRequest,
)
from backend.domain.strategy_schemas import (
    StrategyDefinition,
    StrategyStatus,
)
from backend.execution.strategy_registry import global_strategy_registry
from backend.execution.execution_orchestrator import ExecutionOrchestrator
from backend.execution.safety_engine import global_kill_switch


class TestExecutionOrchestrationControl(unittest.TestCase):

    def setUp(self):
        self.orchestrator = ExecutionOrchestrator()
        global_strategy_registry.clear()
        global_kill_switch.deactivate()

        # Register active strategy
        self.strat = StrategyDefinition(
            strategy_id="ctrl_strat",
            name="Control Strategy",
            version="1.0.0",
            status=StrategyStatus.ACTIVE,
            allowed_instruments=["TCS.NS"],
            allowed_exchanges=["NSE"],
        )
        global_strategy_registry.register(self.strat)

    def _create_decision(self) -> ExecutionPipelineDecision:
        now = datetime.now(timezone.utc)
        return ExecutionPipelineDecision(
            decision_id="dec-ctrl-01",
            execution_mode=ExecutionMode.PAPER,
            pipeline_status=ExecutionPipelineStatus.APPROVED,
            is_authorized=True,
            strategy_id="ctrl_strat",
            strategy_version="1.0.0",
            signal_fingerprint="sig-fp-ctrl",
            symbol="TCS.NS",
            exchange="NSE",
            direction="BUY",
            quantity=10.0,
            estimated_value=35000.0,
            timestamp=now,
        )

    def test_pause_and_resume(self):
        # 1. Pause
        self.orchestrator.pause(reason="Maintenance")
        self.assertEqual(self.orchestrator.get_control_state(), ExecutionControlState.PAUSED)

        # 2. Submission while paused -> Rejected
        now = datetime.now(timezone.utc)
        req = ExecutionOrchestrationRequest(decision=self._create_decision())
        res = self.orchestrator.submit_execution(req, current_time=now)
        self.assertEqual(res.state, ExecutionLifecycleState.REJECTED)
        self.assertIn("PAUSED", res.rejection_reason)

        # 3. Resume
        self.orchestrator.resume()
        self.assertEqual(self.orchestrator.get_control_state(), ExecutionControlState.RUNNING)

    def test_halt_blocks_orchestration(self):
        self.orchestrator.halt(reason="Emergency")
        self.assertEqual(self.orchestrator.get_control_state(), ExecutionControlState.HALTED)

        now = datetime.now(timezone.utc)
        req = ExecutionOrchestrationRequest(decision=self._create_decision())
        res = self.orchestrator.submit_execution(req, current_time=now)
        self.assertEqual(res.state, ExecutionLifecycleState.REJECTED)
        self.assertIn("HALTED", res.rejection_reason)

    def test_kill_switch_overrides_to_halted(self):
        global_kill_switch.activate()
        self.assertEqual(self.orchestrator.get_control_state(), ExecutionControlState.HALTED)

        now = datetime.now(timezone.utc)
        req = ExecutionOrchestrationRequest(decision=self._create_decision())
        res = self.orchestrator.submit_execution(req, current_time=now)
        self.assertEqual(res.state, ExecutionLifecycleState.REJECTED)
        self.assertIn("Kill Switch", res.rejection_reason)
        global_kill_switch.deactivate()


if __name__ == "__main__":
    unittest.main()
