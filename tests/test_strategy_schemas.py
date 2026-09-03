"""
Phase 29 — Unit Tests for Strategy Governance Domain Schemas

Covers:
- StrategySignal validation & field sanitization
- NaN and Inf confidence rejection
- Confidence boundary enforcement [0.0, 1.0]
- Unsupported exchange & symbol validation
- Deterministic SHA-256 fingerprint generation
- StrategyDefinition creation & validation
- StrategyDecision consistency constraints (is_admissible, rejection_reason)
"""

import math
import unittest
from datetime import datetime, timezone
from pydantic import ValidationError

from backend.domain.strategy_schemas import (
    GovernanceStatus,
    SignalDirection,
    SignalSource,
    StrategyDecision,
    StrategyDefinition,
    StrategyHealthMetrics,
    StrategySignal,
    StrategyStatus,
)


class TestStrategySchemas(unittest.TestCase):

    def test_valid_strategy_signal(self):
        sig = StrategySignal(
            strategy_id="momentum_v1",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            exchange="NSE",
            direction=SignalDirection.BUY,
            confidence=0.85,
            quantity=50.0,
            target_price=3500.0,
            stop_loss_price=3400.0,
            source=SignalSource.RULE_BASED,
        )
        self.assertEqual(sig.strategy_id, "momentum_v1")
        self.assertEqual(sig.symbol, "TCS.NS")
        self.assertEqual(sig.confidence, 0.85)
        self.assertEqual(sig.direction, SignalDirection.BUY)

    def test_reject_nan_and_inf_confidence(self):
        with self.assertRaises(ValidationError):
            StrategySignal(
                strategy_id="test",
                strategy_version="1.0.0",
                symbol="TCS.NS",
                direction=SignalDirection.BUY,
                confidence=float("nan"),
            )

        with self.assertRaises(ValidationError):
            StrategySignal(
                strategy_id="test",
                strategy_version="1.0.0",
                symbol="TCS.NS",
                direction=SignalDirection.BUY,
                confidence=float("inf"),
            )

        with self.assertRaises(ValidationError):
            StrategySignal(
                strategy_id="test",
                strategy_version="1.0.0",
                symbol="TCS.NS",
                direction=SignalDirection.BUY,
                confidence=1.5,  # > 1.0
            )

        with self.assertRaises(ValidationError):
            StrategySignal(
                strategy_id="test",
                strategy_version="1.0.0",
                symbol="TCS.NS",
                direction=SignalDirection.BUY,
                confidence=-0.1,  # < 0.0
            )

    def test_reject_invalid_symbol_and_exchange(self):
        with self.assertRaises(ValidationError):
            StrategySignal(
                strategy_id="test",
                strategy_version="1.0.0",
                symbol="",  # Empty symbol
                direction=SignalDirection.BUY,
                confidence=0.5,
            )

        with self.assertRaises(ValidationError):
            StrategySignal(
                strategy_id="test",
                strategy_version="1.0.0",
                symbol="TCS.NS",
                exchange="NASDAQ",  # Unsupported exchange
                direction=SignalDirection.BUY,
                confidence=0.5,
            )

    def test_reject_invalid_quantity(self):
        with self.assertRaises(ValidationError):
            StrategySignal(
                strategy_id="test",
                strategy_version="1.0.0",
                symbol="TCS.NS",
                direction=SignalDirection.BUY,
                confidence=0.5,
                quantity=-10.0,
            )

        with self.assertRaises(ValidationError):
            StrategySignal(
                strategy_id="test",
                strategy_version="1.0.0",
                symbol="TCS.NS",
                direction=SignalDirection.BUY,
                confidence=0.5,
                quantity=float("nan"),
            )

    def test_deterministic_signal_fingerprint(self):
        now = datetime.now(timezone.utc)
        sig1 = StrategySignal(
            strategy_id="strat_a",
            strategy_version="1.0.0",
            symbol="INFY.NS",
            exchange="NSE",
            direction=SignalDirection.BUY,
            confidence=0.9,
            quantity=25.0,
            market_data_timestamp=now,
        )
        sig2 = StrategySignal(
            strategy_id="strat_a",
            strategy_version="1.0.0",
            symbol="INFY.NS",
            exchange="NSE",
            direction=SignalDirection.BUY,
            confidence=0.9,
            quantity=25.0,
            market_data_timestamp=now,
        )
        fp1 = sig1.compute_fingerprint()
        fp2 = sig2.compute_fingerprint()
        self.assertEqual(fp1, fp2)
        self.assertEqual(len(fp1), 64)

    def test_strategy_definition_validation(self):
        sdef = StrategyDefinition(
            strategy_id="TrendFollower",
            name="Trend Following Strategy",
            version="2.1.0",
            status=StrategyStatus.ACTIVE,
            allowed_instruments=["TCS.NS", "INFY.NS"],
            allowed_exchanges=["NSE"],
            max_position_size=200.0,
            max_order_value=500000.0,
        )
        self.assertEqual(sdef.strategy_id, "trendfollower")  # Lowercased
        self.assertEqual(sdef.status, StrategyStatus.ACTIVE)
        self.assertEqual(sdef.max_position_size, 200.0)

    def test_strategy_decision_consistency(self):
        sig = StrategySignal(
            strategy_id="test_strat",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            direction=SignalDirection.BUY,
            confidence=0.8,
        )

        # Valid APPROVED decision
        dec_approved = StrategyDecision(
            signal=sig,
            governance_status=GovernanceStatus.APPROVED,
            is_admissible=True,
            strategy_version="1.0.0",
            fingerprint=sig.compute_fingerprint(),
        )
        self.assertTrue(dec_approved.is_admissible)
        self.assertIsNone(dec_approved.rejection_reason)

        # Valid REJECTED decision
        dec_rejected = StrategyDecision(
            signal=sig,
            governance_status=GovernanceStatus.REJECTED,
            is_admissible=False,
            rejection_reason="Symbol not permitted",
            strategy_version="1.0.0",
            fingerprint=sig.compute_fingerprint(),
        )
        self.assertFalse(dec_rejected.is_admissible)
        self.assertEqual(dec_rejected.rejection_reason, "Symbol not permitted")

        # Invalid inconsistent: APPROVED with is_admissible=False
        with self.assertRaises(ValidationError):
            StrategyDecision(
                signal=sig,
                governance_status=GovernanceStatus.APPROVED,
                is_admissible=False,
                strategy_version="1.0.0",
                fingerprint=sig.compute_fingerprint(),
            )


if __name__ == "__main__":
    unittest.main()
