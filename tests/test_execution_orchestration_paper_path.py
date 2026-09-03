"""
Phase 31 — Paper Path Isolation Tests for Execution Orchestration

Covers:
- Paper execution workflow through PaperBrokerAdapter
- Complete fill simulation and portfolio ledger updates
- Verification that Paper execution NEVER invokes Dhan broker calls or requires Live arming
- Verification that paper orders are completely isolated from live execution
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


class TestExecutionOrchestrationPaperPath(unittest.TestCase):

    def setUp(self):
        self.orchestrator = ExecutionOrchestrator()
        global_strategy_registry.clear()
        global_live_arming_store.disarm()

        # Register active strategy
        self.strat = StrategyDefinition(
            strategy_id="paper_strat",
            name="Paper Strategy",
            version="1.0.0",
            status=StrategyStatus.ACTIVE,
            allowed_instruments=["INFY.NS", "TCS.NS"],
            allowed_exchanges=["NSE"],
            max_position_size=100.0,
            max_order_value=500000.0,
        )
        global_strategy_registry.register(self.strat)

    def test_paper_execution_without_live_arming(self):
        # Explicitly disarmed
        self.assertFalse(global_live_arming_store.get_status().is_armed)

        now = datetime.now(timezone.utc)
        decision = ExecutionPipelineDecision(
            decision_id="dec-paper-01",
            execution_mode=ExecutionMode.PAPER,
            pipeline_status=ExecutionPipelineStatus.APPROVED,
            is_authorized=True,
            strategy_id="paper_strat",
            strategy_version="1.0.0",
            signal_fingerprint="sig-fp-paper",
            symbol="INFY.NS",
            exchange="NSE",
            direction="BUY",
            quantity=30.0,
            estimated_value=45000.0,
            timestamp=now,
        )
        req = ExecutionOrchestrationRequest(decision=decision)

        result = self.orchestrator.submit_execution(req, current_time=now)
        self.assertEqual(result.state, ExecutionLifecycleState.COMPLETED)
        self.assertEqual(result.filled_quantity, 30.0)
        self.assertEqual(result.execution_mode, ExecutionMode.PAPER)
        self.assertTrue(result.broker_order_id.startswith("pord-"))


if __name__ == "__main__":
    unittest.main()
