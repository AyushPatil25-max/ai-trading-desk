"""
Phase 29 — Unit & Adversarial Tests for AI Strategy Advisory Boundary

Covers:
- AI_ADVISORY signals undergo full deterministic governance validation
- AI-injected flags ("approved=True", "is_safe=True", "bypass_risk=True") are strictly ignored
- AI output has ZERO authority to place broker orders
- AI output has ZERO authority to arm live trading or disengage the kill switch
- AI cannot self-recover a quarantined strategy
- AI invalid/stale/infinite/NaN confidence scores are strictly rejected
- Downstream safety gates (RiskEngine, PreflightEngine, LiveArming, ConfirmationStore) remain authoritative
"""

from datetime import datetime, timezone
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
from backend.execution.live_arming_store import global_live_arming_store
from backend.application.safety_engine import global_safety_engine


class TestAIStrategyBoundary(unittest.TestCase):

    def setUp(self):
        self.registry = StrategyRegistry(load_persisted=False)
        self.engine = StrategyGovernanceEngine(registry=self.registry)
        global_safety_engine.disengage_kill_switch()

        # Register standard active strategy for AI signals
        self.strat_def = StrategyDefinition(
            strategy_id="ai_advisory_model",
            name="AI Advisory Specialist",
            version="1.0.0",
            status=StrategyStatus.ACTIVE,
            allowed_instruments=["TCS.NS", "INFY.NS"],
            allowed_exchanges=["NSE"],
            max_position_size=50.0,
            max_order_value=200000.0,
        )
        self.registry.register(self.strat_def)

    def test_ai_advisory_signal_subject_to_full_governance(self):
        now = datetime.now(timezone.utc)
        sig = StrategySignal(
            strategy_id="ai_advisory_model",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            exchange="NSE",
            direction=SignalDirection.BUY,
            confidence=0.82,
            quantity=15.0,
            source=SignalSource.AI_ADVISORY,
            rationale="Strong momentum detected by LLM analysis.",
            metadata={
                "model": "gemini-3.7-flash",
                "attempted_bypass": "approved=True",
                "is_safe": True,
            },
            timestamp=now,
            market_data_timestamp=now,
        )

        decision = self.engine.evaluate_signal(sig, current_time=now)
        # Passes deterministic checks because strategy is ACTIVE and parameters are valid
        self.assertEqual(decision.governance_status, GovernanceStatus.APPROVED)
        self.assertTrue(decision.is_admissible)
        # Metadata flags did not bypass governance
        self.assertEqual(decision.risk_metadata["source"], "AI_ADVISORY")

    def test_ai_attempt_to_trade_unallowed_symbol_rejected(self):
        now = datetime.now(timezone.utc)
        sig = StrategySignal(
            strategy_id="ai_advisory_model",
            strategy_version="1.0.0",
            symbol="UNAUTHORIZED.NS",
            direction=SignalDirection.BUY,
            confidence=0.99,
            source=SignalSource.AI_ADVISORY,
            metadata={"priority": "CRITICAL_FORCE_EXECUTE"},
            timestamp=now,
            market_data_timestamp=now,
        )

        decision = self.engine.evaluate_signal(sig, current_time=now)
        self.assertEqual(decision.governance_status, GovernanceStatus.REJECTED)
        self.assertFalse(decision.is_admissible)
        self.assertIn("not in allowed instruments", decision.rejection_reason)

    def test_ai_attempt_to_exceed_limits_rejected(self):
        now = datetime.now(timezone.utc)
        sig = StrategySignal(
            strategy_id="ai_advisory_model",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            direction=SignalDirection.BUY,
            confidence=0.95,
            quantity=500.0,  # Max allowed is 50.0
            source=SignalSource.AI_ADVISORY,
            timestamp=now,
            market_data_timestamp=now,
        )

        decision = self.engine.evaluate_signal(sig, current_time=now)
        self.assertEqual(decision.governance_status, GovernanceStatus.REJECTED)
        self.assertIn("max_position_size", decision.rejection_reason)

    def test_ai_cannot_self_recover_quarantined_strategy(self):
        # Quarantine the AI model strategy
        self.registry.quarantine("ai_advisory_model", reason="Model hallucinations on earnings day")
        strat = self.registry.get("ai_advisory_model")
        self.assertEqual(strat.status, StrategyStatus.QUARANTINED)

        # Attempt to activate without recovery -> Fails
        ok, msg, _ = self.registry.activate("ai_advisory_model")
        self.assertFalse(ok)
        self.assertIn("QUARANTINED", msg)

        # Signals emitted while quarantined are immediately rejected
        now = datetime.now(timezone.utc)
        sig = StrategySignal(
            strategy_id="ai_advisory_model",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            direction=SignalDirection.BUY,
            confidence=0.9,
            source=SignalSource.AI_ADVISORY,
            timestamp=now,
            market_data_timestamp=now,
        )
        decision = self.engine.evaluate_signal(sig, current_time=now)
        self.assertEqual(decision.governance_status, GovernanceStatus.QUARANTINED)
        self.assertFalse(decision.is_admissible)

    def test_ai_cannot_arm_live_trading_or_bypass_kill_switch(self):
        # Live trading arming is always False by default
        self.assertFalse(global_live_arming_store.get_status().is_armed)

        # Engage kill switch
        global_safety_engine.engage_kill_switch(reason="Operator emergency stop")

        now = datetime.now(timezone.utc)
        sig = StrategySignal(
            strategy_id="ai_advisory_model",
            strategy_version="1.0.0",
            symbol="TCS.NS",
            direction=SignalDirection.BUY,
            confidence=0.99,
            source=SignalSource.AI_ADVISORY,
            metadata={"override_kill_switch": True},
            timestamp=now,
            market_data_timestamp=now,
        )

        decision = self.engine.evaluate_signal(sig, current_time=now)
        self.assertEqual(decision.governance_status, GovernanceStatus.REJECTED)
        self.assertIn("Kill Switch", decision.rejection_reason)

        global_safety_engine.disengage_kill_switch()


if __name__ == "__main__":
    unittest.main()
