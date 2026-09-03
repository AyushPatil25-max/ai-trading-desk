"""
Phase 31 — Recovery & Reconciliation Tests for Execution Orchestration

Covers:
- Handling of RECONCILIATION_REQUIRED states
- Triggering reconciliation via ReconciliationService
- Cancellation coordination
- Durable persistence of execution records
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
    ExecutionRecord,
)
from backend.domain.strategy_schemas import (
    StrategyDefinition,
    StrategyStatus,
)
from backend.execution.strategy_registry import global_strategy_registry
from backend.execution.execution_orchestrator import ExecutionOrchestrator


class TestExecutionOrchestrationRecovery(unittest.TestCase):

    def setUp(self):
        self.orchestrator = ExecutionOrchestrator()
        global_strategy_registry.clear()

        # Register active strategy
        self.strat = StrategyDefinition(
            strategy_id="recov_strat",
            name="Recovery Strategy",
            version="1.0.0",
            status=StrategyStatus.ACTIVE,
            allowed_instruments=["TCS.NS"],
            allowed_exchanges=["NSE"],
        )
        global_strategy_registry.register(self.strat)

    def test_cancel_active_execution(self):
        now = datetime.now(timezone.utc)
        # Create queued record
        rec = ExecutionRecord(
            decision_id="dec-cancel-01",
            decision_fingerprint="fp-cancel-01",
            strategy_id="recov_strat",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            direction="BUY",
            quantity=10.0,
            estimated_value=35000.0,
            execution_mode=ExecutionMode.PAPER,
            state=ExecutionLifecycleState.QUEUED,
        )
        self.orchestrator._records[rec.execution_id] = rec

        res = self.orchestrator.cancel_execution(rec.execution_id, reason="Operator cancelled")
        self.assertEqual(res.state, ExecutionLifecycleState.CANCELLED)

    def test_reconcile_ambiguous_execution(self):
        now = datetime.now(timezone.utc)
        rec = ExecutionRecord(
            decision_id="dec-recon-01",
            decision_fingerprint="fp-recon-01",
            strategy_id="recov_strat",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            direction="BUY",
            quantity=10.0,
            estimated_value=35000.0,
            execution_mode=ExecutionMode.LIVE,
            state=ExecutionLifecycleState.RECONCILIATION_REQUIRED,
        )
        self.orchestrator._records[rec.execution_id] = rec

        res = self.orchestrator.reconcile_execution(rec.execution_id)
        self.assertEqual(res.state, ExecutionLifecycleState.SUBMITTED)


if __name__ == "__main__":
    unittest.main()
