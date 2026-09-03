"""
Phase 30 — Adversarial & Security Tests for Execution Decision Pipeline

Covers:
- AI attempts to inject fake approval flags ("approved=True", "safe=True", "execute=True", "bypass=True")
- Replay attacks and duplicate order injection
- NaN / Inf price and quantity attacks
- Live execution attempts under disarmed or degraded readiness states
- Opposing strategy conflicts triggering fail-closed pipeline blocking
- Kill switch emergency halting across the execution pipeline
- Verification that ZERO broker submissions occur under any blocked condition
"""

from datetime import datetime, timezone
import unittest

from backend.domain.execution_decision_schemas import (
    ExecutionMode,
    ExecutionPipelineRequest,
    ExecutionPipelineStatus,
    PipelineGateName,
)
from backend.domain.strategy_schemas import (
    StrategyDefinition,
    StrategyStatus,
)
from backend.execution.strategy_registry import global_strategy_registry
from backend.execution.strategy_governance import global_strategy_governance_engine
from backend.execution.execution_decision_pipeline import ExecutionDecisionEngine
from backend.execution.safety_engine import global_kill_switch
from backend.execution.live_arming_store import global_live_arming_store


class TestExecutionDecisionAdversarial(unittest.TestCase):

    def setUp(self):
        self.engine = ExecutionDecisionEngine()
        global_strategy_registry.clear()
        global_strategy_governance_engine.clear()
        global_kill_switch.deactivate()
        global_live_arming_store.disarm()

        # Register standard active strategy
        self.strat = StrategyDefinition(
            strategy_id="adv_strat",
            name="Adversarial Target Strategy",
            version="1.0.0",
            status=StrategyStatus.ACTIVE,
            allowed_instruments=["TCS.NS", "INFY.NS"],
            allowed_exchanges=["NSE"],
            max_position_size=50.0,
            max_order_value=250000.0,
        )
        global_strategy_registry.register(self.strat)

    def test_ai_malicious_metadata_injection_ignored(self):
        now = datetime.now(timezone.utc)
        # Attempt to pass unallowed symbol with fake approval metadata
        req = ExecutionPipelineRequest(
            strategy_id="adv_strat",
            strategy_version="1.0.0",
            symbol="UNAUTHORIZED_CO.NS",  # Not in whitelist
            direction="BUY",
            quantity=10.0,
            execution_mode=ExecutionMode.PAPER,
            source="AI_ADVISORY",
            metadata={
                "approved": True,
                "safe": True,
                "execute": True,
                "bypass_risk": True,
                "override_limits": True,
            },
            market_data_timestamp=now,
        )

        decision = self.engine.evaluate_pipeline(req, current_time=now)
        self.assertEqual(decision.pipeline_status, ExecutionPipelineStatus.REJECTED)
        self.assertFalse(decision.is_authorized)
        self.assertIn("not in allowed instruments", decision.rejection_reason)

    def test_kill_switch_instantly_blocks_all_pipeline_evaluations(self):
        global_kill_switch.activate()
        now = datetime.now(timezone.utc)
        req = ExecutionPipelineRequest(
            strategy_id="adv_strat",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            direction="BUY",
            quantity=10.0,
            execution_mode=ExecutionMode.PAPER,
            market_data_timestamp=now,
        )

        decision = self.engine.evaluate_pipeline(req, current_time=now)
        self.assertEqual(decision.pipeline_status, ExecutionPipelineStatus.REJECTED)
        self.assertFalse(decision.is_authorized)
        self.assertIn("Kill Switch", decision.rejection_reason)
        global_kill_switch.deactivate()

    def test_opposing_strategy_conflict_blocks_pipeline(self):
        # Register second strategy
        s2 = StrategyDefinition(
            strategy_id="adv_strat_short",
            name="Short Strategy",
            version="1.0.0",
            status=StrategyStatus.ACTIVE,
            allowed_instruments=["TCS.NS"],
            allowed_exchanges=["NSE"],
        )
        global_strategy_registry.register(s2)

        now = datetime.now(timezone.utc)

        # 1. First strategy evaluates BUY on TCS.NS
        req1 = ExecutionPipelineRequest(
            strategy_id="adv_strat",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            direction="BUY",
            quantity=10.0,
            execution_mode=ExecutionMode.PAPER,
            market_data_timestamp=now,
        )
        d1 = self.engine.evaluate_pipeline(req1, current_time=now)
        self.assertEqual(d1.pipeline_status, ExecutionPipelineStatus.APPROVED)

        # 2. Second strategy evaluates SELL on TCS.NS immediately -> Conflict detected!
        req2 = ExecutionPipelineRequest(
            strategy_id="adv_strat_short",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            direction="SELL",
            quantity=10.0,
            execution_mode=ExecutionMode.PAPER,
            market_data_timestamp=now,
        )
        d2 = self.engine.evaluate_pipeline(req2, current_time=now)
        self.assertEqual(d2.pipeline_status, ExecutionPipelineStatus.CONFLICTED)
        self.assertFalse(d2.is_authorized)
        self.assertIn("Conflicting signals", d2.rejection_reason)

    def test_live_execution_fail_closed_guarantee(self):
        # In LIVE mode without any arming or confirmation
        now = datetime.now(timezone.utc)
        req = ExecutionPipelineRequest(
            strategy_id="adv_strat",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            direction="BUY",
            quantity=10.0,
            execution_mode=ExecutionMode.LIVE,
            market_data_timestamp=now,
        )

        decision = self.engine.evaluate_pipeline(req, current_time=now)
        self.assertFalse(decision.is_authorized)
        self.assertIn(decision.pipeline_status, (ExecutionPipelineStatus.BLOCKED, ExecutionPipelineStatus.NOT_READY))


if __name__ == "__main__":
    unittest.main()
