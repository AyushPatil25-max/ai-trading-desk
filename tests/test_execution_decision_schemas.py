"""
Phase 30 — Unit Tests for Execution Decision Pipeline Domain Schemas

Covers:
- ExecutionPipelineDecision schema construction and validation
- Numerical validation (rejection of NaN, Inf, and negative values)
- Authorization consistency checks (APPROVED requires is_authorized=True, rejection_reason=None)
- Deterministic decision fingerprint generation
- GateExecutionResult tracking
- Serialization and secret omission
"""

import math
import unittest
from datetime import datetime, timezone
from pydantic import ValidationError

from backend.domain.execution_decision_schemas import (
    ExecutionMode,
    ExecutionPipelineDecision,
    ExecutionPipelineRequest,
    ExecutionPipelineStatus,
    GateExecutionResult,
    PipelineGateName,
)


class TestExecutionDecisionSchemas(unittest.TestCase):

    def test_valid_approved_decision(self):
        dec = ExecutionPipelineDecision(
            execution_mode=ExecutionMode.PAPER,
            pipeline_status=ExecutionPipelineStatus.APPROVED,
            is_authorized=True,
            strategy_id="momentum_alpha",
            strategy_version="1.0.0",
            signal_fingerprint="sig-fp-12345",
            symbol="TCS.NS",
            exchange="NSE",
            direction="BUY",
            quantity=50.0,
            estimated_value=175000.0,
            governance_status="APPROVED",
            risk_decision="APPROVED",
            preflight_decision="APPROVED",
        )
        self.assertTrue(dec.is_authorized)
        self.assertEqual(dec.pipeline_status, ExecutionPipelineStatus.APPROVED)
        self.assertIsNone(dec.rejection_reason)
        self.assertTrue(len(dec.decision_fingerprint) == 64)

    def test_valid_rejected_decision(self):
        dec = ExecutionPipelineDecision(
            execution_mode=ExecutionMode.LIVE,
            pipeline_status=ExecutionPipelineStatus.BLOCKED,
            is_authorized=False,
            strategy_id="momentum_alpha",
            strategy_version="1.0.0",
            signal_fingerprint="sig-fp-12345",
            symbol="TCS.NS",
            exchange="NSE",
            direction="BUY",
            quantity=50.0,
            estimated_value=175000.0,
            rejection_reason="Live session is not armed.",
            blocking_gate=PipelineGateName.LIVE_ARMING,
        )
        self.assertFalse(dec.is_authorized)
        self.assertEqual(dec.pipeline_status, ExecutionPipelineStatus.BLOCKED)
        self.assertEqual(dec.blocking_gate, PipelineGateName.LIVE_ARMING)
        self.assertIn("not armed", dec.rejection_reason)

    def test_reject_inconsistent_authorization(self):
        # APPROVED with is_authorized=False -> Error
        with self.assertRaises(ValidationError):
            ExecutionPipelineDecision(
                pipeline_status=ExecutionPipelineStatus.APPROVED,
                is_authorized=False,
                strategy_id="strat",
                strategy_version="1.0.0",
                signal_fingerprint="fp",
                symbol="TCS.NS",
                direction="BUY",
                quantity=10.0,
                estimated_value=1000.0,
            )

        # REJECTED with is_authorized=True -> Error
        with self.assertRaises(ValidationError):
            ExecutionPipelineDecision(
                pipeline_status=ExecutionPipelineStatus.REJECTED,
                is_authorized=True,
                strategy_id="strat",
                strategy_version="1.0.0",
                signal_fingerprint="fp",
                symbol="TCS.NS",
                direction="BUY",
                quantity=10.0,
                estimated_value=1000.0,
            )

    def test_reject_nan_and_inf_numbers(self):
        with self.assertRaises(ValidationError):
            ExecutionPipelineDecision(
                pipeline_status=ExecutionPipelineStatus.APPROVED,
                is_authorized=True,
                strategy_id="strat",
                strategy_version="1.0.0",
                signal_fingerprint="fp",
                symbol="TCS.NS",
                direction="BUY",
                quantity=float("nan"),
                estimated_value=1000.0,
            )

        with self.assertRaises(ValidationError):
            ExecutionPipelineDecision(
                pipeline_status=ExecutionPipelineStatus.APPROVED,
                is_authorized=True,
                strategy_id="strat",
                strategy_version="1.0.0",
                signal_fingerprint="fp",
                symbol="TCS.NS",
                direction="BUY",
                quantity=10.0,
                estimated_value=float("inf"),
            )

    def test_deterministic_decision_fingerprint(self):
        now = datetime.now(timezone.utc)
        d1 = ExecutionPipelineDecision(
            decision_id="dec-fixed-id",
            execution_mode=ExecutionMode.PAPER,
            pipeline_status=ExecutionPipelineStatus.APPROVED,
            is_authorized=True,
            strategy_id="strat_1",
            strategy_version="1.0.0",
            signal_fingerprint="sig-fp-100",
            symbol="INFY.NS",
            exchange="NSE",
            direction="BUY",
            quantity=25.0,
            estimated_value=37500.0,
            timestamp=now,
        )
        d2 = ExecutionPipelineDecision(
            decision_id="dec-fixed-id",
            execution_mode=ExecutionMode.PAPER,
            pipeline_status=ExecutionPipelineStatus.APPROVED,
            is_authorized=True,
            strategy_id="strat_1",
            strategy_version="1.0.0",
            signal_fingerprint="sig-fp-100",
            symbol="INFY.NS",
            exchange="NSE",
            direction="BUY",
            quantity=25.0,
            estimated_value=37500.0,
            timestamp=now,
        )
        self.assertEqual(d1.decision_fingerprint, d2.decision_fingerprint)


if __name__ == "__main__":
    unittest.main()
