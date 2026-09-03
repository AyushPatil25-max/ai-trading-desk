"""
Phase 31 — State Machine Tests for Execution Orchestration

Covers:
- Deterministic lifecycle state machine transitions
- Valid state progression paths
- Rejection of invalid/illegal transitions (InvalidTransitionError)
- Terminal state immutability
"""

import unittest
from datetime import datetime, timezone

from backend.domain.execution_decision_schemas import ExecutionMode
from backend.domain.execution_orchestration_schemas import (
    ExecutionLifecycleState,
    ExecutionRecord,
    ExecutionStage,
    InvalidTransitionError,
    TERMINAL_EXECUTION_STATES,
)


class TestExecutionOrchestrationStateMachine(unittest.TestCase):

    def _create_record(self) -> ExecutionRecord:
        now = datetime.now(timezone.utc)
        return ExecutionRecord(
            decision_id="dec-sm-01",
            decision_fingerprint="fp-sm-01",
            strategy_id="strat_sm",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            direction="BUY",
            quantity=10.0,
            estimated_value=35000.0,
            execution_mode=ExecutionMode.PAPER,
            state=ExecutionLifecycleState.RECEIVED,
            stage=ExecutionStage.INITIAL_SUBMISSION,
            created_at=now,
            updated_at=now,
        )

    def test_valid_paper_progression(self):
        rec = self._create_record()
        self.assertEqual(rec.state, ExecutionLifecycleState.RECEIVED)

        rec.transition_to(ExecutionLifecycleState.VALIDATING)
        self.assertEqual(rec.state, ExecutionLifecycleState.VALIDATING)

        rec.transition_to(ExecutionLifecycleState.APPROVED)
        self.assertEqual(rec.state, ExecutionLifecycleState.APPROVED)

        rec.transition_to(ExecutionLifecycleState.PREPARING)
        self.assertEqual(rec.state, ExecutionLifecycleState.PREPARING)

        rec.transition_to(ExecutionLifecycleState.PAPER_EXECUTING)
        self.assertEqual(rec.state, ExecutionLifecycleState.PAPER_EXECUTING)

        rec.transition_to(ExecutionLifecycleState.FILLED)
        self.assertEqual(rec.state, ExecutionLifecycleState.FILLED)

        rec.transition_to(ExecutionLifecycleState.COMPLETED)
        self.assertEqual(rec.state, ExecutionLifecycleState.COMPLETED)
        self.assertTrue(rec.is_terminal())

    def test_disallowed_transition_raises_error(self):
        rec = self._create_record()
        # Direct jump from RECEIVED to FILLED is forbidden
        with self.assertRaises(InvalidTransitionError):
            rec.transition_to(ExecutionLifecycleState.FILLED)

        # Jump from RECEIVED to LIVE_EXECUTING is forbidden
        with self.assertRaises(InvalidTransitionError):
            rec.transition_to(ExecutionLifecycleState.LIVE_EXECUTING)

    def test_terminal_states_cannot_transition(self):
        for term_state in TERMINAL_EXECUTION_STATES:
            rec = self._create_record()
            rec.state = term_state
            self.assertTrue(rec.is_terminal())

            # Attempting any transition out of a terminal state must raise InvalidTransitionError
            with self.assertRaises(InvalidTransitionError):
                rec.transition_to(ExecutionLifecycleState.SUBMITTED)


if __name__ == "__main__":
    unittest.main()
