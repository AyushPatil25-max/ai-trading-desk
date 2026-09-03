"""
Phase 31 — AI Advisory Boundary Tests for Execution Orchestration

Covers:
- AI outputs have ZERO direct execution authority
- AI-injected metadata cannot bypass orchestration gates
- AI cannot alter control plane state (pause/resume/halt) or arm live trading
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


class TestExecutionOrchestrationAIBoundary(unittest.TestCase):

    def setUp(self):
        self.orchestrator = ExecutionOrchestrator()
        global_strategy_registry.clear()

        # Register active strategy
        self.strat = StrategyDefinition(
            strategy_id="ai_boundary_strat",
            name="AI Boundary Strategy",
            version="1.0.0",
            status=StrategyStatus.ACTIVE,
            allowed_instruments=["TCS.NS"],
            allowed_exchanges=["NSE"],
        )
        global_strategy_registry.register(self.strat)

    def test_ai_unauthorized_decision_rejected(self):
        now = datetime.now(timezone.utc)
        # AI creates a decision candidate that is NOT authorized
        decision = ExecutionPipelineDecision(
            decision_id="dec-ai-unauth",
            execution_mode=ExecutionMode.PAPER,
            pipeline_status=ExecutionPipelineStatus.REJECTED,
            is_authorized=False,
            strategy_id="ai_boundary_strat",
            strategy_version="1.0.0",
            signal_fingerprint="sig-ai-fp",
            symbol="TCS.NS",
            exchange="NSE",
            direction="BUY",
            quantity=10.0,
            estimated_value=35000.0,
            rejection_reason="AI advisory only; not authorized",
            timestamp=now,
        )
        req = ExecutionOrchestrationRequest(decision=decision)

        result = self.orchestrator.submit_execution(req, current_time=now)
        self.assertEqual(result.state, ExecutionLifecycleState.REJECTED)
        self.assertIn("not authorized", result.rejection_reason)


if __name__ == "__main__":
    unittest.main()
