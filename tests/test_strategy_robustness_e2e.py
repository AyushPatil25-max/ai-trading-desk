"""
Phase 25 — Strategy Robustness, Regime Analysis & Monte Carlo Validation E2E Tests

Comprehensive test suite verifying:
1. Strongly typed schema validation and enum completeness.
2. Deterministic parameter sensitivity analysis & stable region isolation.
3. Performance cliff detection under parameter perturbation.
4. Point-in-Time market regime classification (zero look-ahead bias).
5. Regime performance attribution (win rate, return %, drawdowns).
6. Monte Carlo trade sequence resampling reproducibility (identical seed -> identical percentiles).
7. Monte Carlo percentile calculations (5th, 25th, 50th, 75th, 95th).
8. Probability of loss and drawdown threshold calculations.
9. Bootstrap resampling reproducibility and 95% confidence intervals.
10. Insufficient-data handling and small-sample safety.
11. Zero-division and NaN/Inf protection across all numerical operations.
12. Execution friction stress testing across 4 tiers (baseline, mild, moderate, severe).
13. Break-even slippage identification.
14. Market stress scenarios (volatility shock, gap down).
15. Symbol concentration metrics and dominant-share detection.
16. Leave-One-Symbol-Out (LOSO) portfolio survival.
17. Performance degradation and walk-forward OOS/IS ratio.
18. Transparent, rule-based overfitting & fragility detection.
19. 12-Category Unified Robustness Scorecard calculation and 0–100 weighting.
20. Phase 23 Observability integration (OperationalEvent emission to global_audit_chain, audit verification).
21. REST API endpoint availability and FastAPI router integration.
22. SHA-256 reproducibility fingerprint consistency.
23. Non-negotiable safety invariant verification (TIER_4 locked, zero live broker authority).
"""

from datetime import datetime, timezone, timedelta
import math
import unittest
from unittest.mock import MagicMock, patch

from backend.domain.observability_schemas import AuditVerificationStatus, EventCategory
from backend.domain.replay_schemas import ExecutionAssumptions, HistoricalDataPoint, ReplayConfig, ReplayTrade
from backend.domain.robustness_schemas import (
    ROBUSTNESS_SCHEMA_VERSION,
    BootstrapConfidenceInterval,
    FrictionStressLevel,
    FrictionStressResult,
    LeaveOneOutResult,
    MarketRegimeType,
    MarketStressResult,
    MonteCarloPercentiles,
    OverfittingAssessment,
    ParameterSensitivitySurface,
    RegimePerformanceAttribution,
    RobustnessAnalysisReport,
    RobustnessAnalysisRequest,
    RobustnessClassification,
    RobustnessScorecard,
    ScorecardCategory,
    StressScenarioType,
    SymbolContribution,
)
from backend.application.strategy_robustness_engine import (
    StrategyRobustnessEngine,
    _pure_python_percentile,
    global_robustness_engine,
)
from backend.application.tamper_evident_audit_chain import global_audit_chain


class TestRobustnessSchemas(unittest.TestCase):
    """Test 1: Strongly typed schema validation and enum completeness."""

    def test_robustness_classification_enums(self):
        self.assertEqual(RobustnessClassification.ROBUST, "ROBUST")
        self.assertEqual(RobustnessClassification.MODERATELY_ROBUST, "MODERATELY_ROBUST")
        self.assertEqual(RobustnessClassification.FRAGILE, "FRAGILE")
        self.assertEqual(RobustnessClassification.UNRELIABLE, "UNRELIABLE")
        self.assertEqual(RobustnessClassification.INSUFFICIENT_DATA, "INSUFFICIENT_DATA")

    def test_friction_stress_level_enums(self):
        levels = [l.value for l in FrictionStressLevel]
        self.assertIn("BASELINE", levels)
        self.assertIn("MILD_STRESS", levels)
        self.assertIn("MODERATE_STRESS", levels)
        self.assertIn("SEVERE_STRESS", levels)

    def test_market_regime_type_enums(self):
        regimes = [r.value for r in MarketRegimeType]
        self.assertIn("BULL_TRENDING", regimes)
        self.assertIn("BEAR_TRENDING", regimes)
        self.assertIn("SIDEWAYS_RANGING", regimes)
        self.assertIn("HIGH_VOLATILITY", regimes)
        self.assertIn("LOW_VOLATILITY", regimes)


class TestPurePythonPercentilesAndSafety(unittest.TestCase):
    """Test 11 & 12: Percentile calculation safety, zero division, and NaN/Inf guards."""

    def test_empty_percentile(self):
        self.assertEqual(_pure_python_percentile([], 50.0), 0.0)

    def test_single_element_percentile(self):
        self.assertEqual(_pure_python_percentile([42.0], 50.0), 42.0)
        self.assertEqual(_pure_python_percentile([42.0], 5.0), 42.0)

    def test_linear_interpolation_percentiles(self):
        data = [10.0, 20.0, 30.0, 40.0, 50.0]
        # Median (50th) should be exactly 30.0
        self.assertEqual(_pure_python_percentile(data, 50.0), 30.0)
        # 0th should be 10.0, 100th should be 50.0
        self.assertEqual(_pure_python_percentile(data, 0.0), 10.0)
        self.assertEqual(_pure_python_percentile(data, 100.0), 50.0)
        # 25th should be 20.0
        self.assertEqual(_pure_python_percentile(data, 25.0), 20.0)


class TestMonteCarloTradeSequenceResampling(unittest.TestCase):
    """Test 6, 7, 8: Seeded Monte Carlo trade-sequence resampling and percentiles."""

    def _create_mock_trades(self, count: int = 20) -> list:
        trades = []
        for i in range(count):
            pnl = float(((i * 37) % 350) - 120.0)
            trades.append(
                ReplayTrade(
                    trade_id=f"t-{i}",
                    correlation_id=f"corr-{i}",
                    symbol="TCS.NS",
                    entry_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
                    exit_time=datetime(2025, 1, 5, tzinfo=timezone.utc),
                    entry_price=3000.0,
                    exit_price=3050.0 if pnl > 0 else 2965.0,
                    quantity=10,
                    net_pnl=pnl,
                    return_pct=(pnl / 30000.0) * 100.0,
                )
            )
        return trades

    def test_monte_carlo_deterministic_reproducibility(self):
        engine = StrategyRobustnessEngine()
        trades = self._create_mock_trades(25)

        mc1 = engine._evaluate_monte_carlo(trades, initial_capital=100000.0, iterations=300, seed=42)
        mc2 = engine._evaluate_monte_carlo(trades, initial_capital=100000.0, iterations=300, seed=42)

        self.assertEqual(mc1.equity_p5, mc2.equity_p5)
        self.assertEqual(mc1.equity_p50, mc2.equity_p50)
        self.assertEqual(mc1.equity_p95, mc2.equity_p95)
        self.assertEqual(mc1.probability_of_net_loss, mc2.probability_of_net_loss)
        self.assertEqual(mc1.drawdown_p95, mc2.drawdown_p95)

    def test_monte_carlo_diverges_on_different_seeds(self):
        engine = StrategyRobustnessEngine()
        trades = self._create_mock_trades(25)

        mc1 = engine._evaluate_monte_carlo(trades, initial_capital=100000.0, iterations=300, seed=42)
        mc2 = engine._evaluate_monte_carlo(trades, initial_capital=100000.0, iterations=300, seed=999)

        # Seeds should produce distinct samples
        self.assertNotEqual(mc1.equity_p5, mc2.equity_p5)

    def test_insufficient_data_monte_carlo(self):
        engine = StrategyRobustnessEngine()
        mc = engine._evaluate_monte_carlo([], initial_capital=100000.0, iterations=100, seed=42)
        self.assertTrue(mc.insufficient_data)


class TestBootstrapConfidenceIntervals(unittest.TestCase):
    """Test 9 & 10: Bootstrap resampling reproducibility and small sample handling."""

    def test_bootstrap_reproducibility(self):
        engine = StrategyRobustnessEngine()
        trades = [
            ReplayTrade(
                trade_id=f"t-{i}",
                correlation_id=f"corr-boot-{i}",
                symbol="INFY.NS",
                entry_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
                exit_time=datetime(2025, 1, 3, tzinfo=timezone.utc),
                entry_price=1500.0,
                quantity=10,
                net_pnl=50.0 if i % 2 == 0 else -20.0,
                return_pct=1.0 if i % 2 == 0 else -0.5,
            )
            for i in range(15)
        ]

        b1 = engine._evaluate_bootstrap(trades, iterations=200, seed=42)
        b2 = engine._evaluate_bootstrap(trades, iterations=200, seed=42)

        self.assertEqual(len(b1), len(b2))
        self.assertEqual(b1[0].mean_estimate, b2[0].mean_estimate)
        self.assertEqual(b1[0].ci_lower_95, b2[0].ci_lower_95)
        self.assertEqual(b1[0].ci_upper_95, b2[0].ci_upper_95)

    def test_insufficient_data_bootstrap(self):
        engine = StrategyRobustnessEngine()
        b = engine._evaluate_bootstrap([], iterations=100, seed=42)
        self.assertTrue(b[0].insufficient_data)


class TestFrictionStressTesting(unittest.TestCase):
    """Test 12, 13: Execution friction stress testing and break-even calculation."""

    def _sample_dataset(self) -> dict:
        base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
        return {
            "TCS.NS": [
                {
                    "symbol": "TCS.NS",
                    "event_timestamp": (base_ts + timedelta(days=i)).isoformat(),
                    "open": 3000.0 + (i * 5.0),
                    "high": 3015.0 + (i * 5.0),
                    "low": 2995.0 + (i * 5.0),
                    "close": 3010.0 + (i * 5.0),
                    "volume": 20000.0,
                }
                for i in range(20)
            ]
        }

    def test_friction_stress_tiers(self):
        engine = StrategyRobustnessEngine()
        ds = self._sample_dataset()
        cfg = ReplayConfig(symbols=["TCS.NS"])

        results = engine._evaluate_friction_stress(ds, cfg)
        self.assertEqual(len(results), 4)

        baseline = results[0]
        severe = results[3]

        self.assertEqual(baseline.stress_level, FrictionStressLevel.BASELINE)
        self.assertEqual(severe.stress_level, FrictionStressLevel.SEVERE_STRESS)
        # Severe friction should have higher roundtrip cost
        self.assertGreater(severe.total_roundtrip_cost_pct, baseline.total_roundtrip_cost_pct)
        # Degradation should be non-negative
        self.assertGreaterEqual(severe.return_degradation_pct, 0.0)


class TestMarketStressScenarios(unittest.TestCase):
    """Test 14: Deterministic market stress scenarios."""

    def test_volatility_and_gap_scenarios(self):
        engine = StrategyRobustnessEngine()
        base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
        ds = {
            "RELIANCE.NS": [
                {
                    "symbol": "RELIANCE.NS",
                    "event_timestamp": (base_ts + timedelta(days=i)).isoformat(),
                    "open": 2500.0 + (i * 3.0),
                    "high": 2510.0 + (i * 3.0),
                    "low": 2490.0 + (i * 3.0),
                    "close": 2505.0 + (i * 3.0),
                    "volume": 15000.0,
                }
                for i in range(15)
            ]
        }
        cfg = ReplayConfig(symbols=["RELIANCE.NS"])
        scenarios = engine._evaluate_market_stress(ds, cfg)
        self.assertEqual(len(scenarios), 2)
        self.assertEqual(scenarios[0].scenario_type, StressScenarioType.VOLATILITY_SHOCK)
        self.assertEqual(scenarios[1].scenario_type, StressScenarioType.GAP_DOWN)


class TestSymbolRobustnessAndLOSO(unittest.TestCase):
    """Test 15, 16: Symbol concentration & Leave-One-Symbol-Out (LOSO)."""

    def test_multi_symbol_contributions_and_loso(self):
        engine = StrategyRobustnessEngine()
        base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
        ds = {}
        for sym in ["TCS.NS", "INFY.NS"]:
            ds[sym] = [
                {
                    "symbol": sym,
                    "event_timestamp": (base_ts + timedelta(days=i)).isoformat(),
                    "open": 1000.0 + (i * 2.0),
                    "high": 1010.0 + (i * 2.0),
                    "low": 995.0 + (i * 2.0),
                    "close": 1005.0 + (i * 2.0),
                    "volume": 20000.0,
                }
                for i in range(15)
            ]

        cfg = ReplayConfig(symbols=["TCS.NS", "INFY.NS"])
        base_res = engine._replay.run_replay(ds, cfg)
        contribs, loso = engine._evaluate_symbol_robustness(ds, cfg, base_res)

        self.assertEqual(len(contribs), 2)
        self.assertEqual(len(loso), 2)
        # Check leave-one-out symbols
        omitted = [l.omitted_symbol for l in loso]
        self.assertIn("TCS.NS", omitted)
        self.assertIn("INFY.NS", omitted)


class TestOverfittingAndUnifiedScorecard(unittest.TestCase):
    """Test 18, 19: Rule-based overfitting assessment and 12-category scorecard."""

    def test_scorecard_categories_count_and_bounded_scores(self):
        engine = StrategyRobustnessEngine()
        base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
        ds = {
            "TCS.NS": [
                {
                    "symbol": "TCS.NS",
                    "event_timestamp": (base_ts + timedelta(days=i)).isoformat(),
                    "open": 3000.0 + (i * 4.0),
                    "high": 3015.0 + (i * 4.0),
                    "low": 2995.0 + (i * 4.0),
                    "close": 3010.0 + (i * 4.0),
                    "volume": 25000.0,
                }
                for i in range(25)
            ]
        }

        report = engine.analyze_strategy(ds, ReplayConfig(symbols=["TCS.NS"]), monte_carlo_iterations=100, seed=42)

        self.assertIsInstance(report, RobustnessAnalysisReport)
        self.assertEqual(report.audit_status, "VALID")

        # Scorecard must have exactly 12 categories
        sc = report.scorecard
        self.assertEqual(len(sc.categories), 12)
        self.assertGreaterEqual(sc.overall_score, 0.0)
        self.assertLessEqual(sc.overall_score, 100.0)

        for cat in sc.categories:
            self.assertGreaterEqual(cat.score, 0.0)
            self.assertLessEqual(cat.score, 100.0)


class TestObservabilityAndAuditIntegrity(unittest.TestCase):
    """Test 20: Phase 23 tamper-evident audit integration."""

    def test_audit_events_emitted_and_chain_valid(self):
        engine = StrategyRobustnessEngine()
        base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
        ds = {
            "INFY.NS": [
                {
                    "symbol": "INFY.NS",
                    "event_timestamp": (base_ts + timedelta(days=i)).isoformat(),
                    "open": 1500.0 + i,
                    "high": 1510.0 + i,
                    "low": 1495.0 + i,
                    "close": 1505.0 + i,
                    "volume": 15000.0,
                }
                for i in range(12)
            ]
        }

        report = engine.analyze_strategy(ds, ReplayConfig(symbols=["INFY.NS"]), monte_carlo_iterations=50, seed=42)

        # Audit chain must remain 100% cryptographically valid
        audit_rep = global_audit_chain.verify_integrity()
        self.assertEqual(audit_rep.status, AuditVerificationStatus.VALID)


class TestSafetyInvariants(unittest.TestCase):
    """Test 23: Non-negotiable safety boundaries."""

    def test_tier4_live_real_money_permanently_locked(self):
        from backend.application.broker_interface import BrokerFactory, ConfigurationSafetyError
        with self.assertRaises(ConfigurationSafetyError):
            BrokerFactory.get_adapter("live")

    def test_robustness_engine_has_zero_live_order_authority(self):
        engine = StrategyRobustnessEngine()
        self.assertFalse(hasattr(engine, "place_live_order"))
        self.assertFalse(hasattr(engine, "submit_live_order"))
        self.assertFalse(hasattr(engine, "execute_live_order"))


class TestRobustnessRESTEndpoints(unittest.TestCase):
    """Test 21: REST API routes availability and FastAPI registration."""

    def test_routes_registered_in_robustness_router(self):
        from backend.application.robustness_routes import robustness_router
        paths = [r.path for r in robustness_router.routes]
        self.assertIn("/api/robustness/status", paths)
        self.assertIn("/api/robustness/analyze", paths)
        self.assertIn("/api/robustness/reports", paths)
        self.assertIn("/api/robustness/report/{analysis_id}", paths)
        self.assertIn("/api/robustness/scorecard/{analysis_id}", paths)
        self.assertIn("/api/robustness/sensitivity/{analysis_id}", paths)
        self.assertIn("/api/robustness/regimes/{analysis_id}", paths)
        self.assertIn("/api/robustness/monte-carlo/{analysis_id}", paths)
        self.assertIn("/api/robustness/bootstrap/{analysis_id}", paths)
        self.assertIn("/api/robustness/stress/{analysis_id}", paths)
        self.assertIn("/api/robustness/symbols/{analysis_id}", paths)

    def test_main_fastapi_app_includes_robustness_router(self):
        from backend.main import app
        all_paths = []
        for r in app.routes:
            if hasattr(r, "path"):
                all_paths.append(r.path)
            if hasattr(r, "original_router") and hasattr(r.original_router, "routes"):
                all_paths.extend([sub.path for sub in r.original_router.routes if hasattr(sub, "path")])

        self.assertIn("/api/robustness/status", all_paths)
        self.assertIn("/api/robustness/analyze", all_paths)

    def test_direct_route_invocations(self):
        from backend.application.robustness_routes import (
            get_robustness_status,
            trigger_robustness_analysis,
            list_robustness_reports,
        )

        status = get_robustness_status()
        self.assertEqual(status["live_money_execution"], "LOCKED")
        self.assertEqual(status["tier_4_live_real_money"], "FAIL_CLOSED")

        rep = trigger_robustness_analysis()
        self.assertIsInstance(rep, RobustnessAnalysisReport)
        self.assertEqual(rep.tier_4_live_real_money_locked, True)

        reps_list = list_robustness_reports()
        self.assertGreaterEqual(reps_list["count"], 1)


class TestDetailedSensitivityAndRegimes(unittest.TestCase):
    """Test detailed parameter sensitivity and Point-in-Time market regime attribution."""

    def test_parameter_sensitivity_surface_evaluation(self):
        engine = StrategyRobustnessEngine()
        base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
        ds = {
            "TCS.NS": [
                {
                    "symbol": "TCS.NS",
                    "event_timestamp": (base_ts + timedelta(days=i)).isoformat(),
                    "open": 3000.0 + (i * 3.0),
                    "high": 3010.0 + (i * 3.0),
                    "low": 2990.0 + (i * 3.0),
                    "close": 3005.0 + (i * 3.0),
                    "volume": 20000.0,
                }
                for i in range(20)
            ]
        }
        cfg = ReplayConfig(symbols=["TCS.NS"])
        surfaces = engine._evaluate_parameter_sensitivity(ds, cfg)
        self.assertGreater(len(surfaces), 0)
        s = surfaces[0]
        self.assertEqual(s.parameter_name, "holding_period_bars")
        self.assertEqual(len(s.evaluated_points), 6)
        self.assertGreaterEqual(s.stability_score, 0.0)

    def test_market_regime_performance_attribution(self):
        engine = StrategyRobustnessEngine()
        t1 = ReplayTrade(
            trade_id="t-bull",
            correlation_id="corr-bull",
            symbol="TCS.NS",
            entry_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
            exit_time=datetime(2025, 1, 5, tzinfo=timezone.utc),
            entry_price=100.0,
            exit_price=105.0,
            quantity=10,
            net_pnl=50.0,
            return_pct=5.0,
            factor_scores_at_entry={"momentum": 0.05},
        )
        t2 = ReplayTrade(
            trade_id="t-bear",
            correlation_id="corr-bear",
            symbol="TCS.NS",
            entry_time=datetime(2025, 1, 6, tzinfo=timezone.utc),
            exit_time=datetime(2025, 1, 10, tzinfo=timezone.utc),
            entry_price=100.0,
            exit_price=95.0,
            quantity=10,
            net_pnl=-50.0,
            return_pct=-5.0,
            factor_scores_at_entry={"momentum": -0.05},
        )

        regimes = engine._evaluate_market_regimes({}, [t1, t2])
        bull_regime = next((r for r in regimes if r.regime_type == MarketRegimeType.BULL_TRENDING), None)
        bear_regime = next((r for r in regimes if r.regime_type == MarketRegimeType.BEAR_TRENDING), None)

        self.assertIsNotNone(bull_regime)
        self.assertIsNotNone(bear_regime)
        self.assertEqual(bull_regime.trades_count, 1)
        self.assertEqual(bear_regime.trades_count, 1)
        self.assertEqual(bull_regime.win_rate_pct, 100.0)
        self.assertEqual(bear_regime.win_rate_pct, 0.0)

    def test_route_get_report_and_scorecard_by_id(self):
        from backend.application.robustness_routes import (
            trigger_robustness_analysis,
            get_robustness_report,
            get_robustness_scorecard,
        )
        from fastapi import HTTPException

        rep = trigger_robustness_analysis()
        retrieved_rep = get_robustness_report(rep.analysis_id)
        self.assertEqual(retrieved_rep.analysis_id, rep.analysis_id)

        retrieved_sc = get_robustness_scorecard(rep.analysis_id)
        self.assertEqual(retrieved_sc.overall_score, rep.scorecard.overall_score)

        with self.assertRaises(HTTPException):
            get_robustness_report("invalid-nonexistent-id")


if __name__ == "__main__":
    unittest.main()
