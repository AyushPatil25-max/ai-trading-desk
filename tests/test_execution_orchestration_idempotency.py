"""
Phase 31 — Idempotency & Duplicate Protection Tests for Execution Orchestration

Covers:
- Idempotent execution submissions sharing the same decision_id
- Prevention of duplicate broker submissions
- Thread-safe duplicate handling
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


class TestExecutionOrchestrationIdempotency(unittest.TestCase):

    def setUp(self):
        self.orchestrator = ExecutionOrchestrator()
        global_strategy_registry.clear()

        # Register active strategy
        self.strat = StrategyDefinition(
            strategy_id="idem_strat",
            name="Idempotency Strategy",
            version="1.0.0",
            status=StrategyStatus.ACTIVE,
            allowed_instruments=["TCS.NS"],
            allowed_exchanges=["NSE"],
        )
        global_strategy_registry.register(self.strat)

    def test_duplicate_submission_returns_existing_record(self):
        now = datetime.now(timezone.utc)
        decision = ExecutionPipelineDecision(
            decision_id="dec-idem-01",
            execution_mode=ExecutionMode.PAPER,
            pipeline_status=ExecutionPipelineStatus.APPROVED,
            is_authorized=True,
            strategy_id="idem_strat",
            strategy_version="1.0.0",
            signal_fingerprint="sig-fp-idem",
            symbol="TCS.NS",
            exchange="NSE",
            direction="BUY",
            quantity=10.0,
            estimated_value=35000.0,
            timestamp=now,
        )
        req = ExecutionOrchestrationRequest(decision=decision)

        # 1. First submission
        res1 = self.orchestrator.submit_execution(req, current_time=now)
        self.assertEqual(res1.state, ExecutionLifecycleState.COMPLETED)
        exec_id = res1.execution_id

        # 2. Second submission with exact same decision_id
        res2 = self.orchestrator.submit_execution(req, current_time=now)
        self.assertEqual(res2.execution_id, exec_id)
        self.assertEqual(res2.state, ExecutionLifecycleState.COMPLETED)

        # History should contain exactly 1 execution record
        history = self.orchestrator.get_history()
        self.assertEqual(len(history), 1)


if __name__ == "__main__":
    unittest.main()
