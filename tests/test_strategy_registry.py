"""
Phase 29 — Unit & Integration Tests for StrategyRegistry

Covers:
- Strategy registration and retrieval
- Conflicting duplicate registration rejection
- Lifecycle state transitions (Activate, Pause, Disable, Quarantine, Recover)
- Quarantined strategy cannot be activated without formal recovery
- Recovery requires operator review and resets to PAUSED status
- Listing and status filtering
- Status summary reporting
"""

import unittest
from backend.domain.strategy_schemas import (
    StrategyDefinition,
    StrategyStatus,
)
from backend.execution.strategy_registry import (
    DuplicateStrategyError,
    StrategyRegistry,
)


class TestStrategyRegistry(unittest.TestCase):

    def setUp(self):
        self.registry = StrategyRegistry(load_persisted=False)

    def test_register_and_get_strategy(self):
        strat = StrategyDefinition(
            strategy_id="mean_reversion",
            name="Mean Reversion Intraday",
            version="1.0.0",
            status=StrategyStatus.DRAFT,
            allowed_instruments=["RELIANCE.NS", "TCS.NS"],
            max_position_size=50.0,
            max_order_value=200000.0,
        )
        reg = self.registry.register(strat)
        self.assertEqual(reg.strategy_id, "mean_reversion")

        fetched = self.registry.get("mean_reversion")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.name, "Mean Reversion Intraday")
        self.assertEqual(fetched.version, "1.0.0")
        self.assertEqual(fetched.status, StrategyStatus.DRAFT)

    def test_duplicate_conflicting_registration_rejected(self):
        strat1 = StrategyDefinition(
            strategy_id="trend_alpha",
            name="Trend Alpha",
            version="1.0.0",
            max_position_size=100.0,
        )
        self.registry.register(strat1)

        # Same version, different max_position_size -> DuplicateStrategyError
        strat2 = StrategyDefinition(
            strategy_id="trend_alpha",
            name="Trend Alpha",
            version="1.0.0",
            max_position_size=500.0,
        )
        with self.assertRaises(DuplicateStrategyError):
            self.registry.register(strat2)

    def test_lifecycle_transitions(self):
        strat = StrategyDefinition(
            strategy_id="stat_arb",
            name="Statistical Arbitrage",
            version="1.2.0",
            status=StrategyStatus.DRAFT,
        )
        self.registry.register(strat)

        # 1. Activate
        ok, msg, res = self.registry.activate("stat_arb")
        self.assertTrue(ok)
        self.assertEqual(res.status, StrategyStatus.ACTIVE)
        self.assertTrue(res.enabled)

        # 2. Pause
        ok, msg, res = self.registry.pause("stat_arb")
        self.assertTrue(ok)
        self.assertEqual(res.status, StrategyStatus.PAUSED)

        # 3. Disable
        ok, msg, res = self.registry.disable("stat_arb")
        self.assertTrue(ok)
        self.assertEqual(res.status, StrategyStatus.DISABLED)
        self.assertFalse(res.enabled)

    def test_quarantine_and_recovery_flow(self):
        strat = StrategyDefinition(
            strategy_id="breakout_v2",
            name="Breakout Strategy",
            version="2.0.0",
            status=StrategyStatus.ACTIVE,
        )
        self.registry.register(strat)

        # Quarantine
        ok, msg, res = self.registry.quarantine("breakout_v2", reason="Excessive rejections on stale quotes")
        self.assertTrue(ok)
        self.assertEqual(res.status, StrategyStatus.QUARANTINED)
        self.assertFalse(res.enabled)
        self.assertEqual(res.quarantine_reason, "Excessive rejections on stale quotes")

        # Attempt activation while quarantined -> Must be rejected
        ok, msg, res = self.registry.activate("breakout_v2")
        self.assertFalse(ok)
        self.assertIn("QUARANTINED", msg)

        # Recover -> Must transition to PAUSED
        ok, msg, res = self.registry.recover("breakout_v2", operator_notes="Checked data feed, resolved.")
        self.assertTrue(ok)
        self.assertEqual(res.status, StrategyStatus.PAUSED)
        self.assertIsNone(res.quarantine_reason)

        # Now activation is permitted
        ok, msg, res = self.registry.activate("breakout_v2")
        self.assertTrue(ok)
        self.assertEqual(res.status, StrategyStatus.ACTIVE)

    def test_list_and_filter(self):
        self.registry.register(StrategyDefinition(strategy_id="s1", name="S1", status=StrategyStatus.ACTIVE))
        self.registry.register(StrategyDefinition(strategy_id="s2", name="S2", status=StrategyStatus.PAUSED))
        self.registry.register(StrategyDefinition(strategy_id="s3", name="S3", status=StrategyStatus.QUARANTINED))

        all_strats = self.registry.list()
        self.assertEqual(len(all_strats), 3)

        active_strats = self.registry.list(status_filter=StrategyStatus.ACTIVE)
        self.assertEqual(len(active_strats), 1)
        self.assertEqual(active_strats[0].strategy_id, "s1")

    def test_registry_status_summary(self):
        self.registry.register(StrategyDefinition(strategy_id="s1", name="S1", status=StrategyStatus.ACTIVE))
        self.registry.register(StrategyDefinition(strategy_id="s2", name="S2", status=StrategyStatus.ACTIVE))
        self.registry.register(StrategyDefinition(strategy_id="s3", name="S3", status=StrategyStatus.QUARANTINED))

        st = self.registry.status()
        self.assertEqual(st["total_registered"], 3)
        self.assertEqual(st["by_status"]["ACTIVE"], 2)
        self.assertEqual(st["by_status"]["QUARANTINED"], 1)


if __name__ == "__main__":
    unittest.main()
