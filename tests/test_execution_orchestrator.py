"""
Phase 31 — Unit & Integration Tests for ExecutionOrchestrator

Covers:
- Core orchestrator initialization and lifecycle coordination
- Submission of approved ExecutionPipelineDecision
- Decision validation and rejection of unapproved or stale decisions
- Strategy provenance verification
- Status reporting and diagnostics
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


class TestExecutionOrchestrator(unittest.TestCase):

    def setUp(self):
        self.orchestrator = ExecutionOrchestrator()
        global_strategy_registry.clear()
        global_kill_switch.deactivate()

        # Register active strategy
        self.strat = StrategyDefinition(
            strategy_id="orch_strat",
            name="Orchestration Test Strategy",
            version="1.0.0",
            status=StrategyStatus.ACTIVE,
            allowed_instruments=["TCS.NS", "INFY.NS"],
            allowed_exchanges=["NSE"],
            max_position_size=100.0,
            max_order_value=500000.0,
        )
        global_strategy_registry.register(self.strat)

    def _create_approved_decision(
        self,
        symbol: str = "TCS.NS",
        quantity: float = 20.0,
        mode: ExecutionMode = ExecutionMode.PAPER,
        timestamp: Optional[datetime] = None,
    ) -> ExecutionPipelineDecision:
        now = timestamp or datetime.now(timezone.utc)
        return ExecutionPipelineDecision(
            decision_id=f"dec-test-{symbol.replace('.', '')}",
            execution_mode=mode,
            pipeline_status=ExecutionPipelineStatus.APPROVED,
            is_authorized=True,
            strategy_id="orch_strat",
            strategy_version="1.0.0",
            signal_fingerprint="sig-fp-12345",
            symbol=symbol,
            exchange="NSE",
            direction="BUY",
            quantity=quantity,
            estimated_value=quantity * 3500.0,
            governance_status="APPROVED",
            risk_decision="APPROVED",
            preflight_decision="APPROVED",
            timestamp=now,
        )

    def test_submit_valid_paper_decision(self):
        now = datetime.now(timezone.utc)
        decision = self._create_approved_decision(timestamp=now)
        req = ExecutionOrchestrationRequest(decision=decision)

        result = self.orchestrator.submit_execution(req, current_time=now)
        self.assertEqual(result.state, ExecutionLifecycleState.COMPLETED)
        self.assertEqual(result.filled_quantity, 20.0)
        self.assertIsNotNone(result.broker_order_id)
        self.assertIsNone(result.rejection_reason)

    def test_reject_unapproved_decision(self):
        now = datetime.now(timezone.utc)
        decision = ExecutionPipelineDecision(
            decision_id="dec-rejected",
            execution_mode=ExecutionMode.PAPER,
            pipeline_status=ExecutionPipelineStatus.REJECTED,
            is_authorized=False,
            strategy_id="orch_strat",
            strategy_version="1.0.0",
            signal_fingerprint="fp",
            symbol="TCS.NS",
            direction="BUY",
            quantity=10.0,
            estimated_value=35000.0,
            rejection_reason="Failed governance",
            timestamp=now,
        )
        req = ExecutionOrchestrationRequest(decision=decision)

        result = self.orchestrator.submit_execution(req, current_time=now)
        self.assertEqual(result.state, ExecutionLifecycleState.REJECTED)
        self.assertIn("not authorized", result.rejection_reason)

    def test_reject_stale_decision(self):
        # 10 minutes old decision (exceeds 300s freshness window)
        old_time = datetime.now(timezone.utc) - timedelta(seconds=600)
        now = datetime.now(timezone.utc)
        decision = self._create_approved_decision(timestamp=old_time)
        req = ExecutionOrchestrationRequest(decision=decision)

        result = self.orchestrator.submit_execution(req, current_time=now)
        self.assertEqual(result.state, ExecutionLifecycleState.REJECTED)
        self.assertIn("STALE", result.rejection_reason)

    def test_reject_unregistered_strategy(self):
        now = datetime.now(timezone.utc)
        decision = ExecutionPipelineDecision(
            decision_id="dec-unreg",
            execution_mode=ExecutionMode.PAPER,
            pipeline_status=ExecutionPipelineStatus.APPROVED,
            is_authorized=True,
            strategy_id="unregistered_strat",
            strategy_version="1.0.0",
            signal_fingerprint="fp",
            symbol="TCS.NS",
            direction="BUY",
            quantity=10.0,
            estimated_value=35000.0,
            timestamp=now,
        )
        req = ExecutionOrchestrationRequest(decision=decision)

        result = self.orchestrator.submit_execution(req, current_time=now)
        self.assertEqual(result.state, ExecutionLifecycleState.REJECTED)
        self.assertIn("not found in registry", result.rejection_reason)


if __name__ == "__main__":
    unittest.main()
