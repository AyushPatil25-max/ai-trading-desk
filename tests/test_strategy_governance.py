"""
Phase 29 — Unit & Integration Tests for StrategyGovernanceEngine

Covers:
- 17-point deterministic validation pipeline
- Unregistered strategy rejection
- Strategy status checks (DRAFT, PAUSED, DISABLED, QUARANTINED)
- Version mismatch detection
- Instrument & exchange whitelist enforcement
- Freshness enforcement (signal age & market data age)
- Position size & order value limit checks
- Kill switch rejection
- Signal deduplication via SHA-256 fingerprint
- Automated quarantine upon consecutive rejections
- Successful APPROVED decision generation
"""

from datetime import datetime, timezone, timedelta
import unittest

from backend.domain.strategy_schemas import (
    GovernanceStatus,
    SignalDirection,
    SignalSource,
    StrategyDefinition,
    StrategySignal,
    StrategyStatus,
)
from backend.execution.strategy_registry import StrategyRegistry
from backend.execution.strategy_governance import StrategyGovernanceEngine
from backend.application.safety_engine import global_safety_engine


class TestStrategyGovernance(unittest.TestCase):

    def setUp(self):
        self.registry = StrategyRegistry(load_persisted=False)
        self.engine = StrategyGovernanceEngine(registry=self.registry)
        global_safety_engine.disengage_kill_switch()

        # Register standard active strategy
        self.strat_def = StrategyDefinition(
            strategy_id="momentum_alpha",
            name="Momentum Alpha",
            version="1.0.0",
            status=StrategyStatus.ACTIVE,
            allowed_instruments=["TCS.NS", "INFY.NS", "RELIANCE.NS"],
            allowed_exchanges=["NSE"],
            max_position_size=100.0,
            max_order_value=400000.0,
        )
        self.registry.register(self.strat_def)

    def test_approved_signal_evaluation(self):
        now = datetime.now(timezone.utc)
        sig = StrategySignal(
            strategy_id="momentum_alpha",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            exchange="NSE",
            direction=SignalDirection.BUY,
            confidence=0.85,
            quantity=20.0,
            target_price=3500.0,
            timestamp=now,
            market_data_timestamp=now,
            source=SignalSource.RULE_BASED,
        )

        decision = self.engine.evaluate_signal(sig, current_time=now)
        self.assertEqual(decision.governance_status, GovernanceStatus.APPROVED)
        self.assertTrue(decision.is_admissible)
        self.assertIsNone(decision.rejection_reason)
        self.assertEqual(decision.strategy_version, "1.0.0")

    def test_unregistered_strategy_rejected(self):
        sig = StrategySignal(
            strategy_id="ghost_strategy",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            direction=SignalDirection.BUY,
            confidence=0.8,
        )
        decision = self.engine.evaluate_signal(sig)
        self.assertEqual(decision.governance_status, GovernanceStatus.REJECTED)
        self.assertFalse(decision.is_admissible)
        self.assertIn("not registered", decision.rejection_reason)

    def test_non_active_strategy_rejected(self):
        self.registry.pause("momentum_alpha")
        sig = StrategySignal(
            strategy_id="momentum_alpha",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            direction=SignalDirection.BUY,
            confidence=0.8,
        )
        decision = self.engine.evaluate_signal(sig)
        self.assertEqual(decision.governance_status, GovernanceStatus.REJECTED)
        self.assertIn("not ACTIVE", decision.rejection_reason)

    def test_version_mismatch_rejected(self):
        sig = StrategySignal(
            strategy_id="momentum_alpha",
            strategy_version="2.0.0",  # Registered is 1.0.0
            symbol="TCS.NS",
            direction=SignalDirection.BUY,
            confidence=0.8,
        )
        decision = self.engine.evaluate_signal(sig)
        self.assertEqual(decision.governance_status, GovernanceStatus.REJECTED)
        self.assertIn("strategy_version", decision.rejection_reason)

    def test_unallowed_symbol_and_exchange_rejected(self):
        # Unallowed symbol
        sig1 = StrategySignal(
            strategy_id="momentum_alpha",
            strategy_version="1.0.0",
            symbol="TATAMOTORS.NS",  # Not in whitelist
            direction=SignalDirection.BUY,
            confidence=0.8,
        )
        decision1 = self.engine.evaluate_signal(sig1)
        self.assertEqual(decision1.governance_status, GovernanceStatus.REJECTED)
        self.assertIn("not in allowed instruments", decision1.rejection_reason)

        # Unallowed exchange
        sig2 = StrategySignal(
            strategy_id="momentum_alpha",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            exchange="BSE",  # Only NSE allowed
            direction=SignalDirection.BUY,
            confidence=0.8,
        )
        decision2 = self.engine.evaluate_signal(sig2)
        self.assertEqual(decision2.governance_status, GovernanceStatus.REJECTED)
        self.assertIn("not in allowed exchanges", decision2.rejection_reason)

    def test_stale_signal_and_market_data_rejected(self):
        now = datetime.now(timezone.utc)

        # Stale signal (age > 1800s)
        stale_sig = StrategySignal(
            strategy_id="momentum_alpha",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            direction=SignalDirection.BUY,
            confidence=0.8,
            timestamp=now - timedelta(seconds=2000),
            market_data_timestamp=now,
        )
        d1 = self.engine.evaluate_signal(stale_sig, current_time=now)
        self.assertEqual(d1.governance_status, GovernanceStatus.REJECTED)
        self.assertIn("Signal is stale", d1.rejection_reason)

        # Stale market data (age > 300s)
        stale_md = StrategySignal(
            strategy_id="momentum_alpha",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            direction=SignalDirection.BUY,
            confidence=0.8,
            timestamp=now,
            market_data_timestamp=now - timedelta(seconds=400),
        )
        d2 = self.engine.evaluate_signal(stale_md, current_time=now)
        self.assertEqual(d2.governance_status, GovernanceStatus.REJECTED)
        self.assertIn("Market data is stale", d2.rejection_reason)

    def test_size_and_value_limits_enforced(self):
        now = datetime.now(timezone.utc)

        # Exceeds max_position_size (100)
        sig_large_qty = StrategySignal(
            strategy_id="momentum_alpha",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            direction=SignalDirection.BUY,
            confidence=0.8,
            quantity=150.0,
            timestamp=now,
            market_data_timestamp=now,
        )
        d1 = self.engine.evaluate_signal(sig_large_qty, current_time=now)
        self.assertEqual(d1.governance_status, GovernanceStatus.REJECTED)
        self.assertIn("max_position_size", d1.rejection_reason)

        # Exceeds max_order_value (400,000)
        sig_large_val = StrategySignal(
            strategy_id="momentum_alpha",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            direction=SignalDirection.BUY,
            confidence=0.8,
            quantity=90.0,
            target_price=5000.0,  # 90 * 5000 = 450,000 > 400,000
            timestamp=now,
            market_data_timestamp=now,
        )
        d2 = self.engine.evaluate_signal(sig_large_val, current_time=now)
        self.assertEqual(d2.governance_status, GovernanceStatus.REJECTED)
        self.assertIn("max_order_value", d2.rejection_reason)

    def test_kill_switch_blocks_signals(self):
        global_safety_engine.engage_kill_switch(reason="Emergency safety drill")
        now = datetime.now(timezone.utc)
        sig = StrategySignal(
            strategy_id="momentum_alpha",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            direction=SignalDirection.BUY,
            confidence=0.85,
            timestamp=now,
            market_data_timestamp=now,
        )
        decision = self.engine.evaluate_signal(sig, current_time=now)
        self.assertEqual(decision.governance_status, GovernanceStatus.REJECTED)
        self.assertIn("Kill Switch", decision.rejection_reason)
        global_safety_engine.disengage_kill_switch()

    def test_duplicate_signal_detection(self):
        now = datetime.now(timezone.utc)
        sig = StrategySignal(
            strategy_id="momentum_alpha",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            direction=SignalDirection.BUY,
            confidence=0.85,
            quantity=10.0,
            timestamp=now,
            market_data_timestamp=now,
        )

        d1 = self.engine.evaluate_signal(sig, current_time=now)
        self.assertEqual(d1.governance_status, GovernanceStatus.APPROVED)

        # Immediate repeat of same signal -> DUPLICATE
        d2 = self.engine.evaluate_signal(sig, current_time=now)
        self.assertEqual(d2.governance_status, GovernanceStatus.DUPLICATE)
        self.assertFalse(d2.is_admissible)
        self.assertIn("Duplicate signal", d2.rejection_reason)

    def test_auto_quarantine_after_consecutive_rejections(self):
        now = datetime.now(timezone.utc)

        # Trigger 5 consecutive rejections (e.g. unallowed symbol)
        for i in range(5):
            sig = StrategySignal(
                strategy_id="momentum_alpha",
                strategy_version="1.0.0",
                symbol=f"INVALID_{i}.NS",
                direction=SignalDirection.BUY,
                confidence=0.8,
                timestamp=now,
                market_data_timestamp=now,
            )
            d = self.engine.evaluate_signal(sig, current_time=now)
            self.assertEqual(d.governance_status, GovernanceStatus.REJECTED)

        # Check strategy is now QUARANTINED in registry
        strat = self.registry.get("momentum_alpha")
        self.assertEqual(strat.status, StrategyStatus.QUARANTINED)

        # Subsequent signals are now marked QUARANTINED
        valid_sig = StrategySignal(
            strategy_id="momentum_alpha",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            direction=SignalDirection.BUY,
            confidence=0.8,
            timestamp=now,
            market_data_timestamp=now,
        )
        d_quarantined = self.engine.evaluate_signal(valid_sig, current_time=now)
        self.assertEqual(d_quarantined.governance_status, GovernanceStatus.QUARANTINED)


if __name__ == "__main__":
    unittest.main()
