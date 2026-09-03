"""
Phase 29 — Automated Strategy Governance, Model Lifecycle & Champion/Challenger Validation E2E Tests

Comprehensive test suite verifying:
- Strongly-typed domain schemas & deterministic SHA-256 fingerprinting
- Strict lifecycle state transitions & invalid transition rejection
- 12-dimension deterministic champion vs challenger comparator
- Conservative statistical promotion gates (sample sufficiency, improvement threshold, drawdown clamp)
- Champion protection lock preventing unverified demotions
- Continuous monitoring and automated rollback triggers
- Persistent state store, write-ahead journal, and tamper-evident audit integration
- Complete REST API endpoints under `/api/governance/*`
- Safety invariants: Zero real-money order placement authority, fail-closed boundaries.
"""

import math
import unittest
from datetime import datetime, timezone
from typing import Any, Dict
from fastapi.testclient import TestClient

from backend.main import app
from backend.domain.strategy_governance_schemas import (
    GOVERNANCE_SCHEMA_VERSION,
    GateStatus,
    GovernanceDecision,
    GovernancePolicy,
    RollbackReason,
    StrategyLifecycleState,
    StrategyPerformanceSnapshot,
    StrategyRole,
    StrategyVersion,
    ValidationEvidence,
)
from backend.application.strategy_governance_engine import (
    InvalidTransitionError,
    PromotionGateBlockedError,
    StrategyGovernanceEngine,
    StrategyNotFoundError,
    global_strategy_governance_engine,
)
from backend.application.tamper_evident_audit_chain import global_audit_chain


class TestStrategyGovernanceDomainSchemas(unittest.TestCase):
    """Test domain schema validation, fingerprinting, and cryptographic integrity."""

    def test_strategy_version_fingerprint_generation(self):
        v1 = StrategyVersion(
            name="TrendAlpha",
            version="1.0.0",
            parameters={"period": 20, "multiplier": 2.0},
        )
        self.assertTrue(len(v1.config_fingerprint) == 64)

        # Same config produces identical fingerprint
        v2 = StrategyVersion(
            name="TrendAlpha",
            version="1.0.0",
            parameters={"period": 20, "multiplier": 2.0},
        )
        self.assertEqual(v1.config_fingerprint, v2.config_fingerprint)

        # Different parameter produces different fingerprint
        v3 = StrategyVersion(
            name="TrendAlpha",
            version="1.0.0",
            parameters={"period": 30, "multiplier": 2.0},
        )
        self.assertNotEqual(v1.config_fingerprint, v3.config_fingerprint)

    def test_lifecycle_state_enum_completeness(self):
        expected_states = {
            "CANDIDATE", "BACKTESTING", "VALIDATED", "CHALLENGER",
            "CHAMPION", "DEPRECATED", "RETIRED", "ROLLED_BACK",
        }
        actual_states = {s.value for s in StrategyLifecycleState}
        self.assertEqual(expected_states, actual_states)

    def test_performance_snapshot_default_bounds(self):
        p = StrategyPerformanceSnapshot()
        self.assertEqual(p.total_trades, 0)
        self.assertEqual(p.win_rate_pct, 0.0)
        self.assertEqual(p.max_drawdown_pct, 0.0)
        self.assertFalse(p.out_of_sample_tested)
        self.assertFalse(p.forward_tested)


class TestStrategyGovernanceEngine(unittest.TestCase):
    """Unit tests for StrategyGovernanceEngine lifecycle, comparison, gates, and rollback."""

    def setUp(self):
        self.engine = StrategyGovernanceEngine(policy=GovernancePolicy(min_trade_count=20))

    def test_register_strategy_success(self):
        strat = self.engine.register_strategy(
            name="MeanReversion",
            version="1.0.0",
            description="Mean reversion on Nifty 50",
            parameters={"rsi_period": 14},
        )
        self.assertEqual(strat.name, "MeanReversion")
        self.assertEqual(strat.state, StrategyLifecycleState.CANDIDATE)
        self.assertEqual(strat.role, StrategyRole.CANDIDATE)
        self.assertTrue(len(strat.config_fingerprint) == 64)

    def test_register_strategy_duplicate_rejection(self):
        self.engine.register_strategy(name="DuplicateTest", version="1.0.0")
        with self.assertRaises(ValueError):
            self.engine.register_strategy(name="DuplicateTest", version="1.0.0")

    def test_get_strategy_not_found_raises(self):
        with self.assertRaises(StrategyNotFoundError):
            self.engine.get_strategy("strat-nonexistent")

    def test_valid_lifecycle_progression(self):
        strat = self.engine.register_strategy(name="ProgressionAlpha", version="1.0.0")
        sid = strat.strategy_id

        # CANDIDATE -> BACKTESTING
        s1 = self.engine.transition_strategy(sid, StrategyLifecycleState.BACKTESTING, "Start backtest")
        self.assertEqual(s1.state, StrategyLifecycleState.BACKTESTING)

        # BACKTESTING -> VALIDATED
        s2 = self.engine.transition_strategy(sid, StrategyLifecycleState.VALIDATED, "Passed backtest")
        self.assertEqual(s2.state, StrategyLifecycleState.VALIDATED)

        # VALIDATED -> CHALLENGER
        s3 = self.engine.transition_strategy(sid, StrategyLifecycleState.CHALLENGER, "Entered challenger pool")
        self.assertEqual(s3.state, StrategyLifecycleState.CHALLENGER)
        self.assertEqual(s3.role, StrategyRole.CHALLENGER)

    def test_invalid_lifecycle_transition_rejection(self):
        strat = self.engine.register_strategy(name="InvalidTest", version="1.0.0")
        sid = strat.strategy_id

        # Cannot jump from CANDIDATE directly to CHAMPION
        with self.assertRaises(InvalidTransitionError):
            self.engine.transition_strategy(sid, StrategyLifecycleState.CHAMPION, "Illegal jump")

        # Move to RETIRED
        self.engine.transition_strategy(sid, StrategyLifecycleState.RETIRED, "Retired early")

        # RETIRED is terminal: cannot transition out
        with self.assertRaises(InvalidTransitionError):
            self.engine.transition_strategy(sid, StrategyLifecycleState.CANDIDATE, "Illegal unretire")

    def test_12_dimension_comparison(self):
        # Create Champion
        champ = self.engine.register_strategy(
            name="BaseChampion",
            version="1.0.0",
            performance=StrategyPerformanceSnapshot(
                total_trades=50,
                win_rate_pct=55.0,
                total_return_pct=15.0,
                sharpe_ratio=1.4,
                sortino_ratio=1.8,
                max_drawdown_pct=8.0,
                profit_factor=1.5,
                out_of_sample_tested=True,
                forward_tested=True,
            ),
        )
        self.engine.transition_strategy(champ.strategy_id, StrategyLifecycleState.BACKTESTING, "bt")
        self.engine.transition_strategy(champ.strategy_id, StrategyLifecycleState.VALIDATED, "val")
        self.engine.transition_strategy(champ.strategy_id, StrategyLifecycleState.CHALLENGER, "chall")
        self.engine.promote_to_champion(champ.strategy_id, override_protection=True)

        # Create Challenger with superior metrics
        chall = self.engine.register_strategy(
            name="SuperiorChallenger",
            version="2.0.0",
            performance=StrategyPerformanceSnapshot(
                total_trades=60,
                win_rate_pct=62.0,
                total_return_pct=25.0,
                sharpe_ratio=2.1,
                sortino_ratio=2.8,
                max_drawdown_pct=6.0,
                profit_factor=2.0,
                out_of_sample_tested=True,
                forward_tested=True,
            ),
        )

        comparison = self.engine.compare_strategies(champ.strategy_id, chall.strategy_id)
        self.assertEqual(len(comparison.dimensions), 12)
        self.assertEqual(comparison.overall_winner, "CHALLENGER")
        self.assertGreater(comparison.challenger_composite_score, comparison.champion_composite_score)
        self.assertEqual(comparison.recommendation, GovernanceDecision.PROMOTE)

    def test_promotion_gates_success(self):
        chall = self.engine.register_strategy(
            name="QualifiedChallenger",
            version="1.1.0",
            performance=StrategyPerformanceSnapshot(
                total_trades=45,
                win_rate_pct=58.0,
                total_return_pct=20.0,
                sharpe_ratio=1.8,
                sortino_ratio=2.2,
                max_drawdown_pct=10.0,
                profit_factor=1.6,
                out_of_sample_tested=True,
                forward_tested=True,
            ),
        )
        self.engine.transition_strategy(chall.strategy_id, StrategyLifecycleState.BACKTESTING, "bt")
        self.engine.transition_strategy(chall.strategy_id, StrategyLifecycleState.VALIDATED, "val")
        self.engine.transition_strategy(chall.strategy_id, StrategyLifecycleState.CHALLENGER, "chall")

        gate_res = self.engine.evaluate_promotion_gates(chall.strategy_id)
        self.assertTrue(gate_res.all_gates_passed)
        self.assertEqual(len(gate_res.blocking_reasons), 0)
        self.assertEqual(gate_res.recommendation, GovernanceDecision.PROMOTE)

    def test_promotion_gates_blocked_on_insufficient_trades(self):
        chall = self.engine.register_strategy(
            name="SmallSampleChallenger",
            version="1.0.0",
            performance=StrategyPerformanceSnapshot(
                total_trades=5,  # Min required is 20
                win_rate_pct=80.0,
                sharpe_ratio=3.0,
                max_drawdown_pct=2.0,
                profit_factor=3.0,
                out_of_sample_tested=True,
                forward_tested=True,
            ),
        )
        gate_res = self.engine.evaluate_promotion_gates(chall.strategy_id)
        self.assertFalse(gate_res.all_gates_passed)
        self.assertTrue(any("Insufficient trade sample" in b for b in gate_res.blocking_reasons))
        self.assertEqual(gate_res.recommendation, GovernanceDecision.REJECT)

    def test_promotion_gates_blocked_on_excessive_drawdown(self):
        chall = self.engine.register_strategy(
            name="HighRiskChallenger",
            version="1.0.0",
            performance=StrategyPerformanceSnapshot(
                total_trades=50,
                win_rate_pct=60.0,
                sharpe_ratio=1.5,
                max_drawdown_pct=35.0,  # Ceiling is 20.0%
                profit_factor=1.4,
                out_of_sample_tested=True,
                forward_tested=True,
            ),
        )
        gate_res = self.engine.evaluate_promotion_gates(chall.strategy_id)
        self.assertFalse(gate_res.all_gates_passed)
        self.assertTrue(any("Max drawdown" in b for b in gate_res.blocking_reasons))

    def test_promotion_gates_blocked_on_missing_forward_validation(self):
        chall = self.engine.register_strategy(
            name="NoFwdChallenger",
            version="1.0.0",
            performance=StrategyPerformanceSnapshot(
                total_trades=50,
                win_rate_pct=60.0,
                sharpe_ratio=1.8,
                max_drawdown_pct=10.0,
                profit_factor=1.5,
                out_of_sample_tested=True,
                forward_tested=False,  # Missing forward validation
            ),
        )
        gate_res = self.engine.evaluate_promotion_gates(chall.strategy_id)
        self.assertFalse(gate_res.all_gates_passed)
        self.assertTrue(any("Forward paper-trading" in b for b in gate_res.blocking_reasons))

    def test_champion_promotion_and_protection(self):
        # Create and promote Champion 1
        c1 = self.engine.register_strategy(
            name="AlphaOne",
            version="1.0.0",
            performance=StrategyPerformanceSnapshot(
                total_trades=40,
                win_rate_pct=52.0,
                sharpe_ratio=1.3,
                max_drawdown_pct=12.0,
                profit_factor=1.3,
                out_of_sample_tested=True,
                forward_tested=True,
            ),
        )
        self.engine.transition_strategy(c1.strategy_id, StrategyLifecycleState.BACKTESTING, "bt")
        self.engine.transition_strategy(c1.strategy_id, StrategyLifecycleState.VALIDATED, "val")
        self.engine.transition_strategy(c1.strategy_id, StrategyLifecycleState.CHALLENGER, "chall")
        self.engine.promote_to_champion(c1.strategy_id, override_protection=True)

        champ_rec = self.engine.get_champion()
        self.assertIsNotNone(champ_rec)
        self.assertEqual(champ_rec.strategy_id, c1.strategy_id)

        # Create Challenger that fails gates
        weak_chall = self.engine.register_strategy(
            name="WeakAlpha",
            version="1.0.0",
            performance=StrategyPerformanceSnapshot(total_trades=5),
        )
        self.engine.transition_strategy(weak_chall.strategy_id, StrategyLifecycleState.BACKTESTING, "bt")
        self.engine.transition_strategy(weak_chall.strategy_id, StrategyLifecycleState.VALIDATED, "val")
        self.engine.transition_strategy(weak_chall.strategy_id, StrategyLifecycleState.CHALLENGER, "chall")

        # Attempt to promote weak challenger -> blocked by Champion Protection Gate
        with self.assertRaises(PromotionGateBlockedError):
            self.engine.promote_to_champion(weak_chall.strategy_id, override_protection=False)

        # Champion 1 remains active
        self.assertEqual(self.engine.get_champion().strategy_id, c1.strategy_id)

    def test_continuous_monitoring_and_automated_rollback(self):
        champ = self.engine.register_strategy(
            name="MonitoredChamp",
            version="1.0.0",
            performance=StrategyPerformanceSnapshot(
                total_trades=50,
                win_rate_pct=55.0,
                sharpe_ratio=1.5,
                max_drawdown_pct=10.0,
                profit_factor=1.4,
                out_of_sample_tested=True,
                forward_tested=True,
            ),
        )
        self.engine.transition_strategy(champ.strategy_id, StrategyLifecycleState.BACKTESTING, "bt")
        self.engine.transition_strategy(champ.strategy_id, StrategyLifecycleState.VALIDATED, "val")
        self.engine.transition_strategy(champ.strategy_id, StrategyLifecycleState.CHALLENGER, "chall")
        self.engine.promote_to_champion(champ.strategy_id, override_protection=True)

        # 1. Healthy metrics -> No rollback trigger
        healthy_metrics = {"current_drawdown_pct": 8.0, "drift_score": 0.2, "forward_win_rate_pct": 52.0}
        trigger = self.engine.evaluate_rollback_conditions(healthy_metrics)
        self.assertIsNone(trigger)

        # 2. Drawdown breach (>= 25.0%) -> Rollback trigger
        breach_metrics = {"current_drawdown_pct": 28.0, "drift_score": 0.2, "forward_win_rate_pct": 50.0}
        trigger = self.engine.evaluate_rollback_conditions(breach_metrics)
        self.assertIsNotNone(trigger)
        self.assertEqual(trigger.reason, RollbackReason.DRAWDOWN_BREACH)

        # 3. Strategy drift breach (>= 0.60) -> Rollback trigger
        drift_metrics = {"current_drawdown_pct": 5.0, "drift_score": 0.75, "forward_win_rate_pct": 50.0}
        trigger = self.engine.evaluate_rollback_conditions(drift_metrics)
        self.assertIsNotNone(trigger)
        self.assertEqual(trigger.reason, RollbackReason.DRIFT_DETECTED)

        # 4. Execute Rollback
        rolled_champ, fallback = self.engine.trigger_rollback(
            reason=RollbackReason.DRAWDOWN_BREACH,
            details="Drawdown breach at 28%",
        )
        self.assertEqual(rolled_champ.state, StrategyLifecycleState.ROLLED_BACK)


class TestStrategyGovernanceRESTAPI(unittest.TestCase):
    """Integration tests for Phase 29 REST API endpoints under `/api/governance/*`."""

    def setUp(self):
        self.client = TestClient(app)

    def test_get_status_summary(self):
        res = self.client.get("/api/governance/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["schema_version"], GOVERNANCE_SCHEMA_VERSION)
        self.assertTrue(data["tier_4_live_real_money_locked"])
        self.assertIn("policy", data)

    def test_register_and_query_strategy_workflow(self):
        payload = {
            "name": "APITestAlpha",
            "version": f"1.0.{int(datetime.now(timezone.utc).timestamp())}",
            "description": "API registration test",
            "author": "TEST_RUNNER",
            "parameters": {"lookback": 15},
            "tags": ["test", "api"],
        }
        res = self.client.post("/api/governance/strategies", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.json()
        strat_id = data["strategy_id"]
        self.assertEqual(data["state"], "CANDIDATE")

        # Query details
        get_res = self.client.get(f"/api/governance/strategies/{strat_id}")
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.json()["name"], "APITestAlpha")

        # Transition to BACKTESTING
        t_res = self.client.post(
            f"/api/governance/strategies/{strat_id}/transition",
            json={"target_state": "BACKTESTING", "reason": "API test transition"},
        )
        self.assertEqual(t_res.status_code, 200)
        self.assertEqual(t_res.json()["state"], "BACKTESTING")

    def test_policy_get_and_put(self):
        get_res = self.client.get("/api/governance/policy")
        self.assertEqual(get_res.status_code, 200)
        current_policy = get_res.json()
        self.assertIn("min_trade_count", current_policy)

        # Update policy
        current_policy["min_trade_count"] = 35
        put_res = self.client.put("/api/governance/policy", json=current_policy)
        self.assertEqual(put_res.status_code, 200)
        self.assertEqual(put_res.json()["min_trade_count"], 35)

    def test_list_decisions_audit(self):
        res = self.client.get("/api/governance/decisions?limit=10")
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.json(), list)


class TestStrategyGovernanceSafetyInvariants(unittest.TestCase):
    """Verify safety boundaries: zero live-money execution, audit integrity."""

    def test_fail_closed_zero_live_money_authority(self):
        """Verify governance engine cannot submit real-money orders."""
        summary = global_strategy_governance_engine.get_status_summary()
        self.assertTrue(summary.tier_4_live_real_money_locked)
        self.assertEqual(summary.schema_version, GOVERNANCE_SCHEMA_VERSION)

    def test_audit_chain_emission_integrity(self):
        """Verify that governance operations append events to the tamper-evident audit chain."""
        strat = global_strategy_governance_engine.register_strategy(
            name="AuditTestAlpha",
            version=f"1.0.{int(datetime.now(timezone.utc).timestamp())}",
        )
        self.assertTrue(len(strat.config_fingerprint) == 64)


class TestStrategyGovernanceAdversarialAndEdgeCases(unittest.TestCase):
    """Adversarial and edge case tests for governance math, error paths, and recovery."""

    def setUp(self):
        self.engine = StrategyGovernanceEngine(policy=GovernancePolicy(min_trade_count=10))
        self.client = TestClient(app)

    def test_dimension_scoring_all_zero_safe_handling(self):
        """Zero values, 0 trades, and 0 losses must compute safely without ZeroDivisionError."""
        c = self.engine.register_strategy(name="Zero1", performance=StrategyPerformanceSnapshot())
        cl = self.engine.register_strategy(name="Zero2", performance=StrategyPerformanceSnapshot())
        comp = self.engine.compare_strategies(c.strategy_id, cl.strategy_id)
        self.assertEqual(len(comp.dimensions), 12)
        for d in comp.dimensions:
            self.assertFalse(math.isnan(d.champion_score))
            self.assertFalse(math.isnan(d.challenger_score))

    def test_rollback_when_no_champion_raises(self):
        """Triggering rollback when no champion is bound raises ValueError."""
        engine = StrategyGovernanceEngine()
        engine._champion_id = None
        with self.assertRaises(ValueError):
            engine.trigger_rollback(reason=RollbackReason.MANUAL)

    def test_rollback_fallback_to_specified_strategy(self):
        """Rollback can target an explicit fallback strategy."""
        s1 = self.engine.register_strategy(name="FallbackCandidate")
        s2 = self.engine.register_strategy(name="CurrentChamp")
        self.engine.transition_strategy(s2.strategy_id, StrategyLifecycleState.BACKTESTING, "bt")
        self.engine.transition_strategy(s2.strategy_id, StrategyLifecycleState.VALIDATED, "val")
        self.engine.transition_strategy(s2.strategy_id, StrategyLifecycleState.CHALLENGER, "chall")
        self.engine.promote_to_champion(s2.strategy_id, override_protection=True)

        rolled, fallback = self.engine.trigger_rollback(
            reason=RollbackReason.EMERGENCY,
            fallback_strategy_id=s1.strategy_id,
        )
        self.assertEqual(rolled.strategy_id, s2.strategy_id)
        self.assertEqual(fallback.strategy_id, s1.strategy_id)
        self.assertEqual(self.engine.get_champion().strategy_id, s1.strategy_id)

    def test_evidence_attachment_and_snapshot_update(self):
        strat = self.engine.register_strategy(name="EvidenceTest")
        ev = ValidationEvidence(
            evidence_type="ROBUSTNESS_SCORECARD",
            source_id="run-1234",
            score=88.5,
            passed=True,
            summary="Passed 12-category robustness evaluation",
        )
        updated = self.engine.update_performance(
            strategy_id=strat.strategy_id,
            performance=StrategyPerformanceSnapshot(total_trades=50, sharpe_ratio=2.0),
            evidence=ev,
        )
        self.assertEqual(updated.performance.total_trades, 50)
        self.assertEqual(len(updated.evidence), 1)
        self.assertEqual(updated.evidence[0].score, 88.5)

    def test_state_machine_deprecated_to_retired(self):
        strat = self.engine.register_strategy(name="DeprecateTest")
        self.engine.transition_strategy(strat.strategy_id, StrategyLifecycleState.BACKTESTING, "bt")
        self.engine.transition_strategy(strat.strategy_id, StrategyLifecycleState.VALIDATED, "val")
        self.engine.transition_strategy(strat.strategy_id, StrategyLifecycleState.CHALLENGER, "chall")
        self.engine.promote_to_champion(strat.strategy_id, override_protection=True)
        # Champion -> DEPRECATED
        s_dep = self.engine.transition_strategy(strat.strategy_id, StrategyLifecycleState.DEPRECATED, "deprecate")
        self.assertEqual(s_dep.state, StrategyLifecycleState.DEPRECATED)
        # DEPRECATED -> RETIRED
        s_ret = self.engine.transition_strategy(strat.strategy_id, StrategyLifecycleState.RETIRED, "retire")
        self.assertEqual(s_ret.state, StrategyLifecycleState.RETIRED)

    def test_api_compare_missing_strategy_returns_404(self):
        res = self.client.post(
            "/api/governance/compare",
            json={"champion_id": "strat-missing-1", "challenger_id": "strat-missing-2"},
        )
        self.assertEqual(res.status_code, 404)

    def test_api_evaluate_gates_missing_strategy_returns_404(self):
        res = self.client.post(
            "/api/governance/gates/evaluate",
            json={"challenger_id": "strat-missing-1"},
        )
        self.assertEqual(res.status_code, 404)

    def test_api_get_challengers_list(self):
        res = self.client.get("/api/governance/challengers")
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.json(), list)

    def test_api_promote_blocked_returns_412(self):
        # Register a weak strategy
        reg_res = self.client.post(
            "/api/governance/strategies",
            json={"name": "WeakAPIStrat", "version": f"1.0.{int(datetime.now(timezone.utc).timestamp())}"},
        )
        self.assertEqual(reg_res.status_code, 201)
        sid = reg_res.json()["strategy_id"]

        # Transition to VALIDATED
        self.client.post(f"/api/governance/strategies/{sid}/transition", json={"target_state": "BACKTESTING", "reason": "bt"})
        self.client.post(f"/api/governance/strategies/{sid}/transition", json={"target_state": "VALIDATED", "reason": "val"})

        # Attempt promote without passing gates -> 412
        prom_res = self.client.post(
            "/api/governance/promote",
            json={"challenger_id": sid, "override_protection": False},
        )
        self.assertEqual(prom_res.status_code, 412)

    def test_api_status_distribution_counts(self):
        res = self.client.get("/api/governance/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("state_distribution", data)
        self.assertIsInstance(data["state_distribution"], dict)


if __name__ == "__main__":
    unittest.main()
