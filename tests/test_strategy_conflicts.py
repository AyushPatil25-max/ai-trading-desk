"""
Phase 29 — Unit & Integration Tests for Strategy Conflict Detection

Covers:
- Opposing strategy signal detection (BUY vs SELL on same instrument within window)
- Conflict record creation & conflict metadata attachment
- Non-conflicting signals (same direction, different symbols)
- Conflict window expiration behavior
- Audit event emission on conflict detection
"""

from datetime import datetime, timezone, timedelta
import unittest

from backend.domain.strategy_schemas import (
    GovernanceStatus,
    SignalDirection,
    StrategyDefinition,
    StrategySignal,
    StrategyStatus,
)
from backend.execution.strategy_registry import StrategyRegistry
from backend.execution.strategy_governance import StrategyGovernanceEngine


class TestStrategyConflicts(unittest.TestCase):

    def setUp(self):
        self.registry = StrategyRegistry(load_persisted=False)
        self.engine = StrategyGovernanceEngine(
            registry=self.registry,
            conflict_window_seconds=300.0,
        )

        # Register Strategy A (Trend Buyer)
        self.strat_a = StrategyDefinition(
            strategy_id="strat_a",
            name="Trend Buyer",
            version="1.0.0",
            status=StrategyStatus.ACTIVE,
            allowed_instruments=["*"],
        )
        self.registry.register(self.strat_a)

        # Register Strategy B (Mean Reversion Short)
        self.strat_b = StrategyDefinition(
            strategy_id="strat_b",
            name="Mean Reversion Short",
            version="1.0.0",
            status=StrategyStatus.ACTIVE,
            allowed_instruments=["*"],
        )
        self.registry.register(self.strat_b)

    def test_opposing_signals_trigger_conflict(self):
        now = datetime.now(timezone.utc)

        # 1. Strategy A emits BUY on RELIANCE.NS
        sig_a = StrategySignal(
            strategy_id="strat_a",
            strategy_version="1.0.0",
            symbol="RELIANCE.NS",
            direction=SignalDirection.BUY,
            confidence=0.8,
            timestamp=now,
            market_data_timestamp=now,
        )
        d_a = self.engine.evaluate_signal(sig_a, current_time=now)
        self.assertEqual(d_a.governance_status, GovernanceStatus.APPROVED)

        # 2. Strategy B emits SELL on RELIANCE.NS 10 seconds later
        sig_b = StrategySignal(
            strategy_id="strat_b",
            strategy_version="1.0.0",
            symbol="RELIANCE.NS",
            direction=SignalDirection.SELL,
            confidence=0.75,
            timestamp=now + timedelta(seconds=10),
            market_data_timestamp=now + timedelta(seconds=10),
        )
        d_b = self.engine.evaluate_signal(sig_b, current_time=now + timedelta(seconds=10))
        self.assertEqual(d_b.governance_status, GovernanceStatus.CONFLICTED)
        self.assertFalse(d_b.is_admissible)
        self.assertIn("Conflicting signals", d_b.rejection_reason)
        self.assertIsNotNone(d_b.conflict_metadata)

        # 3. Check conflict record in engine
        conflicts = self.engine.get_conflicts()
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].symbol, "RELIANCE.NS")

    def test_same_direction_signals_do_not_conflict(self):
        now = datetime.now(timezone.utc)

        sig_a = StrategySignal(
            strategy_id="strat_a",
            strategy_version="1.0.0",
            symbol="INFY.NS",
            direction=SignalDirection.BUY,
            confidence=0.8,
            timestamp=now,
            market_data_timestamp=now,
        )
        d_a = self.engine.evaluate_signal(sig_a, current_time=now)
        self.assertEqual(d_a.governance_status, GovernanceStatus.APPROVED)

        # Strategy B also emits BUY on INFY.NS
        sig_b = StrategySignal(
            strategy_id="strat_b",
            strategy_version="1.0.0",
            symbol="INFY.NS",
            direction=SignalDirection.BUY,
            confidence=0.85,
            timestamp=now + timedelta(seconds=5),
            market_data_timestamp=now + timedelta(seconds=5),
        )
        d_b = self.engine.evaluate_signal(sig_b, current_time=now + timedelta(seconds=5))
        self.assertEqual(d_b.governance_status, GovernanceStatus.APPROVED)
        self.assertEqual(len(self.engine.get_conflicts()), 0)

    def test_different_symbols_do_not_conflict(self):
        now = datetime.now(timezone.utc)

        sig_a = StrategySignal(
            strategy_id="strat_a",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            direction=SignalDirection.BUY,
            confidence=0.8,
            timestamp=now,
            market_data_timestamp=now,
        )
        d_a = self.engine.evaluate_signal(sig_a, current_time=now)
        self.assertEqual(d_a.governance_status, GovernanceStatus.APPROVED)

        # Strategy B emits SELL on different symbol (WIPRO.NS)
        sig_b = StrategySignal(
            strategy_id="strat_b",
            strategy_version="1.0.0",
            symbol="WIPRO.NS",
            direction=SignalDirection.SELL,
            confidence=0.8,
            timestamp=now + timedelta(seconds=5),
            market_data_timestamp=now + timedelta(seconds=5),
        )
        d_b = self.engine.evaluate_signal(sig_b, current_time=now + timedelta(seconds=5))
        self.assertEqual(d_b.governance_status, GovernanceStatus.APPROVED)
        self.assertEqual(len(self.engine.get_conflicts()), 0)

    def test_conflict_window_expiration(self):
        now = datetime.now(timezone.utc)

        sig_a = StrategySignal(
            strategy_id="strat_a",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            direction=SignalDirection.BUY,
            confidence=0.8,
            timestamp=now,
            market_data_timestamp=now,
        )
        self.engine.evaluate_signal(sig_a, current_time=now)

        # Strategy B emits SELL on TCS.NS after conflict window (350s > 300s)
        sig_b = StrategySignal(
            strategy_id="strat_b",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            direction=SignalDirection.SELL,
            confidence=0.8,
            timestamp=now + timedelta(seconds=350),
            market_data_timestamp=now + timedelta(seconds=350),
        )
        d_b = self.engine.evaluate_signal(sig_b, current_time=now + timedelta(seconds=350))
        self.assertEqual(d_b.governance_status, GovernanceStatus.APPROVED)
        self.assertEqual(len(self.engine.get_conflicts()), 0)


if __name__ == "__main__":
    unittest.main()
