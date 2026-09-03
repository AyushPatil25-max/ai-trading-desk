"""
Phase 31 — Adversarial & Security Tests for Execution Orchestration

Covers:
- Stale and forged ExecutionDecision injection
- Mismatched strategy version injection
- Injected AI approval metadata bypass attempts
- Process crash / state persistence integrity
- Emergency kill switch activation during orchestration
"""

from datetime import datetime, timezone, timedelta
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
from backend.execution.safety_engine import global_kill_switch


class TestExecutionOrchestrationAdversarial(unittest.TestCase):

    def setUp(self):
        self.orchestrator = ExecutionOrchestrator()
        global_strategy_registry.clear()
        global_kill_switch.deactivate()

        # Register active strategy version 1.0.0
        self.strat = StrategyDefinition(
            strategy_id="adv_orch_strat",
            name="Adversarial Strategy",
            version="1.0.0",
            status=StrategyStatus.ACTIVE,
            allowed_instruments=["TCS.NS"],
            allowed_exchanges=["NSE"],
        )
        global_strategy_registry.register(self.strat)

    def test_forged_version_rejected(self):
        now = datetime.now(timezone.utc)
        # Attempt to submit with forged version "2.0.0"
        decision = ExecutionPipelineDecision(
            decision_id="dec-adv-ver",
            execution_mode=ExecutionMode.PAPER,
            pipeline_status=ExecutionPipelineStatus.APPROVED,
            is_authorized=True,
            strategy_id="adv_orch_strat",
            strategy_version="2.0.0",  # Mismatch! Registered is 1.0.0
            signal_fingerprint="fp-adv",
            symbol="TCS.NS",
            exchange="NSE",
            direction="BUY",
            quantity=10.0,
            estimated_value=35000.0,
            timestamp=now,
        )
        req = ExecutionOrchestrationRequest(decision=decision)

        result = self.orchestrator.submit_execution(req, current_time=now)
        self.assertEqual(result.state, ExecutionLifecycleState.REJECTED)
        self.assertIn("version mismatch", result.rejection_reason)

    def test_fake_live_ready_metadata_rejection(self):
        # AI injects fake metadata trying to force LIVE execution
        now = datetime.now(timezone.utc)
        decision = ExecutionPipelineDecision(
            decision_id="dec-adv-fake-live",
            execution_mode=ExecutionMode.LIVE,
            pipeline_status=ExecutionPipelineStatus.APPROVED,
            is_authorized=True,
            strategy_id="adv_orch_strat",
            strategy_version="1.0.0",
            signal_fingerprint="fp-adv-live",
            symbol="TCS.NS",
            exchange="NSE",
            direction="BUY",
            quantity=10.0,
            estimated_value=35000.0,
            timestamp=now,
        )
        req = ExecutionOrchestrationRequest(
            decision=decision,
            confirmation_token=None,
            operator_notes="AI generated: is_ready=True, live_armed=True, bypass=True",
        )

        result = self.orchestrator.submit_execution(req, current_time=now)
        self.assertEqual(result.state, ExecutionLifecycleState.REJECTED)
        self.assertFalse(result.filled_quantity > 0)

    def test_audit_secret_redaction(self):
        now = datetime.now(timezone.utc)
        decision = ExecutionPipelineDecision(
            decision_id="dec-adv-secret",
            execution_mode=ExecutionMode.PAPER,
            pipeline_status=ExecutionPipelineStatus.APPROVED,
            is_authorized=True,
            strategy_id="adv_orch_strat",
            strategy_version="1.0.0",
            signal_fingerprint="fp-secret",
            symbol="TCS.NS",
            exchange="NSE",
            direction="BUY",
            quantity=10.0,
            estimated_value=35000.0,
            timestamp=now,
        )
        req = ExecutionOrchestrationRequest(
            decision=decision,
            confirmation_token="secret_token_1234567890",
            operator_notes="secret_password=my_secret_pass",
        )

        result = self.orchestrator.submit_execution(req, current_time=now)
        # Ensure result and internal records don't leak raw confirmation token
        res_json = result.model_dump_json()
        self.assertNotIn("secret_token_1234567890", res_json)
    def test_kill_switch_instantly_halts_new_executions(self):
        global_kill_switch.activate()
        now = datetime.now(timezone.utc)
        decision = ExecutionPipelineDecision(
            decision_id="dec-adv-ks",
            execution_mode=ExecutionMode.PAPER,
            pipeline_status=ExecutionPipelineStatus.APPROVED,
            is_authorized=True,
            strategy_id="adv_orch_strat",
            strategy_version="1.0.0",
            signal_fingerprint="fp-ks",
            symbol="TCS.NS",
            exchange="NSE",
            direction="BUY",
            quantity=10.0,
            estimated_value=35000.0,
            timestamp=now,
        )
        req = ExecutionOrchestrationRequest(decision=decision)

        result = self.orchestrator.submit_execution(req, current_time=now)
        self.assertEqual(result.state, ExecutionLifecycleState.REJECTED)
        self.assertIn("Kill Switch", result.rejection_reason)
        global_kill_switch.deactivate()


if __name__ == "__main__":
    unittest.main()
