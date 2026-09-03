"""
Phase 6.7 — Scenario & Stress Testing Comprehensive Offline Unit Tests

Verifies all 46 required test cases:
1. Scenario schema
2. Scenario validation
3. Market crash
4. Market rally
5. Volatility spike
6. Sector shock
7. Stock shock
8. Gap down
9. Gap up
10. Regime change
11. Portfolio drawdown
12. Liquidity stress
13. Baseline preservation
14. Stressed-state calculation
15. Stock P&L
16. Portfolio P&L
17. Drawdown
18. Exposure change
19. Stop-loss interaction
20. Gap-through-stop handling
21. Risk Engine dry-run
22. Risk veto preservation
23. Position sizing preservation
24. Conviction preservation
25. Scenario resilience
26. Scenario severity
27. Stress score
28. Scenario comparison
29. Scenario matrix
30. Missing market data
31. Missing portfolio
32. Missing sector
33. Missing benchmark
34. Insufficient history
35. Stale data
36. NaN handling
37. Infinity handling
38. Invalid scenario parameters
39. Provenance
40. Context ID propagation
41. Portfolio ID propagation
42. Scenario version
43. Deterministic repeatability
44. Degraded mode
45. Backward compatibility
46. Complete end-to-end integration
"""

from datetime import datetime, timezone
import math
import unittest
from typing import Any, Dict, List

from backend.domain.schemas import (
    MarketContext,
    EvidenceSummary,
    AgentInput,
    AgentOutput,
    AgentExecutionRecord,
    SpecialistRunResult,
    _TechnicalLLMResponse, TrendDirection, SetupType,
    _MomentumLLMResponse, MomentumDirection, MomentumStrength,
    _QuantLLMResponse, QuantStatisticalRegime, QuantRiskCharacterization,
    _FundamentalLLMResponse, FundamentalQuality, GrowthAssessment, ProfitabilityAssessment, BalanceSheetAssessment,
)
from backend.domain.debate_schemas import DebateResult, DebateDecisionState
from backend.domain.investment_committee_schemas import (
    CommitteeRecommendation,
    CommitteeDecision,
)
from backend.domain.calibration_schemas import ConvictionCalibrationResult
from backend.domain.risk_schemas import (
    PositionDirection,
    RiskConfiguration,
    PositionSizingPlan,
)
from backend.domain.regime_schemas import (
    OverallMarketRegime,
    MarketRegime,
)
from backend.domain.portfolio_schemas import (
    PortfolioIntelligence,
    PortfolioConstraintConfig,
)
from backend.domain.scenario_schemas import (
    SCENARIO_ENGINE_VERSION,
    ScenarioType,
    ScenarioSeverity,
    ScenarioResilience,
    ScenarioDataQuality,
    ScenarioDefinition,
    ScenarioResult,
    ScenarioComparison,
    ScenarioMatrix,
)
from backend.application.scenario_engine import ScenarioEngine
from backend.application.market_regime_engine import MarketRegimeEngine
from backend.application.portfolio_intelligence_engine import PortfolioIntelligenceEngine
from backend.application.conviction_calibrator import ConvictionCalibrator
from backend.application.risk_engine import RiskEngine
from backend.application.investment_committee import InvestmentCommittee
from backend.application.debate_engine import DebateEngine
from backend.application.evidence_aggregator import EvidenceAggregator
from backend.specialists.technical_specialist import TechnicalSpecialist
from backend.specialists.momentum_specialist import MomentumSpecialist
from backend.specialists.quant_specialist import QuantSpecialist
from backend.specialists.fundamental_specialist import FundamentalSpecialist
from backend.infrastructure.llm import MockLLMClient


class TestScenarioStressTestingPhase67(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 29, 12, 0, 0, tzinfo=timezone.utc)
        self.ctx = MarketContext(
            context_id="ctx-scen-p67-001",
            symbol="INFY.NS",
            data_timestamp=self.now,
            current_price=1500.0,
            provider="mock-vendor",
            ohlcv_historical=[
                {"timestamp": "2026-08-25T00:00:00Z", "close": 1450.0, "volume": 100000},
                {"timestamp": "2026-08-26T00:00:00Z", "close": 1470.0, "volume": 110000},
                {"timestamp": "2026-08-27T00:00:00Z", "close": 1480.0, "volume": 105000},
                {"timestamp": "2026-08-28T00:00:00Z", "close": 1490.0, "volume": 120000},
                {"timestamp": "2026-08-29T00:00:00Z", "close": 1500.0, "volume": 130000},
            ],
            technical_indicators={
                "rsi": 65.0,
                "ema20": 1460.0,
                "ema50": 1420.0,
                "20_day_high": 1700.0,
                "20_day_low": 1350.0,
            },
            sector_data={
                "sector": "Information Technology",
                "industry": "Software",
                "benchmark_symbol": "^NSEI",
                "benchmark_return_pct": 2.5,
                "beta": 1.10,
            },
            provenance=[{"source": "test_setup", "timestamp": str(self.now)}],
        )

        self.plan = PositionSizingPlan(
            plan_id="plan-test-001",
            context_id="ctx-scen-p67-001",
            symbol="INFY.NS",
            direction=PositionDirection.LONG,
            position_quantity=20,
            entry_price=1500.0,
            position_notional=30000.0,
            account_capital=200000.0,
            exposure_pct=0.15,
            stop_loss_price=1425.0,
            stop_loss_pct=0.05,
            risk_per_trade_pct=0.0075,
            risk_reward_ratio=2.67,
            conviction_score=0.80,
        )

        self.portfolio_dict = {
            "portfolio_id": "port-test-001",
            "total_equity": 200000.0,
            "cash": 100000.0,
            "positions": {
                "TCS.NS": {
                    "symbol": "TCS.NS",
                    "quantity": 15.0,
                    "current_price": 3400.0,
                    "market_value": 51000.0,
                    "sector": "Information Technology",
                },
                "RELIANCE.NS": {
                    "symbol": "RELIANCE.NS",
                    "quantity": 20.0,
                    "current_price": 2450.0,
                    "market_value": 49000.0,
                    "sector": "Energy",
                },
            },
            "updated_at": self.now,
        }

        self.engine = ScenarioEngine()

    # 1. Scenario schema
    def test_01_scenario_schema(self):
        sc_def = ScenarioDefinition(
            scenario_type=ScenarioType.MARKET_CRASH,
            name="Test Crash",
            market_return_shock=-0.10,
        )
        self.assertEqual(sc_def.scenario_type, ScenarioType.MARKET_CRASH)
        self.assertEqual(sc_def.market_return_shock, -0.10)

    # 2. Scenario validation
    def test_02_scenario_validation(self):
        # Loss > -100% must be rejected
        with self.assertRaises(ValueError):
            ScenarioDefinition(
                scenario_type=ScenarioType.MARKET_CRASH,
                name="Impossible Crash",
                market_return_shock=-1.50,
            )
        # Non-positive volatility multiplier must be rejected
        with self.assertRaises(ValueError):
            ScenarioDefinition(
                scenario_type=ScenarioType.VOLATILITY_SPIKE,
                name="Bad Vol",
                volatility_multiplier=-0.5,
            )

    # 3. Market crash
    def test_03_market_crash(self):
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
            scenario_def=self.engine.get_standard_scenarios()["MARKET_CRASH_10"],
        )
        self.assertEqual(res.scenario_type, ScenarioType.MARKET_CRASH)
        self.assertLess(res.position_impact.stressed_price, res.position_impact.baseline_price)
        self.assertGreater(res.portfolio_impact.pct_drawdown, 0.0)

    # 4. Market rally
    def test_04_market_rally(self):
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
            scenario_def=self.engine.get_standard_scenarios()["MARKET_RALLY_10"],
        )
        self.assertEqual(res.scenario_type, ScenarioType.MARKET_RALLY)
        self.assertGreater(res.position_impact.stressed_price, res.position_impact.baseline_price)
        self.assertGreater(res.portfolio_impact.absolute_loss_gain, 0.0)

    # 5. Volatility spike
    def test_05_volatility_spike(self):
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
            scenario_def=self.engine.get_standard_scenarios()["VOLATILITY_SPIKE_50"],
        )
        self.assertEqual(res.scenario_type, ScenarioType.VOLATILITY_SPIKE)
        self.assertIsInstance(res.stress_score, float)

    # 6. Sector shock
    def test_06_sector_shock(self):
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
            scenario_def=self.engine.get_standard_scenarios()["SECTOR_SHOCK_15"],
        )
        self.assertEqual(res.scenario_type, ScenarioType.SECTOR_SHOCK)
        # Candidate is IT -> -15%
        self.assertAlmostEqual(res.position_impact.pct_change, -15.0)
        # TCS is also IT -> affected
        self.assertIn("TCS.NS", res.portfolio_impact.affected_positions)
        # RELIANCE is Energy -> unaffected by sector shock
        self.assertNotIn("RELIANCE.NS", res.portfolio_impact.affected_positions)

    # 7. Stock shock
    def test_07_stock_shock(self):
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
            scenario_def=self.engine.get_standard_scenarios()["STOCK_SHOCK_12"],
        )
        self.assertEqual(res.scenario_type, ScenarioType.STOCK_SHOCK)
        self.assertAlmostEqual(res.position_impact.pct_change, -12.0)

    # 8. Gap down
    def test_08_gap_down(self):
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
            scenario_def=self.engine.get_standard_scenarios()["GAP_DOWN_8"],
        )
        self.assertEqual(res.scenario_type, ScenarioType.GAP_DOWN)
        self.assertAlmostEqual(res.position_impact.pct_change, -8.0)

    # 9. Gap up
    def test_09_gap_up(self):
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
            scenario_def=self.engine.get_standard_scenarios()["GAP_UP_8"],
        )
        self.assertEqual(res.scenario_type, ScenarioType.GAP_UP)
        self.assertAlmostEqual(res.position_impact.pct_change, 8.0)

    # 10. Regime change
    def test_10_regime_change(self):
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
            scenario_def=self.engine.get_standard_scenarios()["REGIME_CHANGE_STRESSED"],
        )
        self.assertEqual(res.scenario_type, ScenarioType.REGIME_CHANGE)
        self.assertEqual(res.regime_context.get("target_regime"), "STRESSED")

    # 11. Portfolio drawdown
    def test_11_portfolio_drawdown(self):
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
            scenario_def=self.engine.get_standard_scenarios()["PORTFOLIO_DRAWDOWN_15"],
        )
        self.assertEqual(res.scenario_type, ScenarioType.PORTFOLIO_DRAWDOWN)
        self.assertGreater(res.portfolio_impact.pct_drawdown, 5.0)

    # 12. Liquidity stress
    def test_12_liquidity_stress(self):
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
            scenario_def=self.engine.get_standard_scenarios()["LIQUIDITY_STRESS_50"],
        )
        self.assertEqual(res.scenario_type, ScenarioType.LIQUIDITY_STRESS)
        self.assertIsInstance(res.severity, ScenarioSeverity)

    # 13. Baseline preservation
    def test_13_baseline_preservation(self):
        orig_price = self.ctx.current_price
        orig_qty = self.plan.position_quantity
        orig_eq = self.portfolio_dict["total_equity"]

        self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
            scenario_def=self.engine.get_standard_scenarios()["MARKET_CRASH_20"],
        )

        self.assertEqual(self.ctx.current_price, orig_price)
        self.assertEqual(self.plan.position_quantity, orig_qty)
        self.assertEqual(self.portfolio_dict["total_equity"], orig_eq)

    # 14. Stressed-state calculation
    def test_14_stressed_state_calculation(self):
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
            scenario_def=self.engine.get_standard_scenarios()["MARKET_CRASH_10"],
        )
        # Entry = 1500, Beta = 1.10, Shock = -10% * 1.10 = -11% => Stressed = 1500 * 0.89 = 1335.0
        self.assertEqual(res.position_impact.stressed_price, 1335.0)

    # 15. Stock P&L
    def test_15_stock_pnl(self):
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
            scenario_def=self.engine.get_standard_scenarios()["MARKET_CRASH_10"],
        )
        # Baseline = 20 * 1500 = 30,000. Stressed = 20 * 1335 = 26,700. P&L = -3,300.
        self.assertEqual(res.position_impact.absolute_pnl_change, -3300.0)

    # 16. Portfolio P&L
    def test_16_portfolio_pnl(self):
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
            scenario_def=self.engine.get_standard_scenarios()["MARKET_CRASH_10"],
        )
        # Cash = 100k. Positions: 100k * 0.90 = 90k. Total stressed = 190k. Loss = -10,000.
        self.assertEqual(res.portfolio_impact.absolute_loss_gain, -10000.0)

    # 17. Drawdown
    def test_17_drawdown(self):
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
            scenario_def=self.engine.get_standard_scenarios()["MARKET_CRASH_10"],
        )
        # 10,000 / 200,000 = 5.0%
        self.assertEqual(res.portfolio_impact.pct_drawdown, 5.0)

    # 18. Exposure change
    def test_18_exposure_change(self):
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
            scenario_def=self.engine.get_standard_scenarios()["MARKET_CRASH_10"],
        )
        self.assertGreater(res.position_impact.exposure_after, 0.0)
        self.assertLessEqual(res.position_impact.exposure_after, 1.0)

    # 19. Stop-loss interaction
    def test_19_stop_loss_interaction(self):
        # Stop loss is at 1425. Stressed price 1335 is below stop.
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
            scenario_def=self.engine.get_standard_scenarios()["MARKET_CRASH_10"],
        )
        self.assertTrue(res.stop_loss_interaction.stop_triggered)

    # 20. Gap-through-stop handling
    def test_20_gap_through_stop_handling(self):
        # Overnight gap down -8% brings 1500 to 1380. Stop is 1425.
        # Price gapped through stop: 1380 < 1425.
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
            scenario_def=self.engine.get_standard_scenarios()["GAP_DOWN_8"],
        )
        self.assertTrue(res.stop_loss_interaction.gap_through)
        self.assertEqual(res.stop_loss_interaction.potential_slippage, 45.0)  # 1425 - 1380
        self.assertEqual(res.stop_loss_interaction.execution_price_estimate, 1380.0)

    # 21. Risk Engine dry-run
    def test_21_risk_engine_dry_run(self):
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
            scenario_def=self.engine.get_standard_scenarios()["MARKET_CRASH_10"],
        )
        dry_plan = self.engine.dry_run_risk(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            scenario_result=res,
            portfolio_state=self.portfolio_dict,
        )
        self.assertIsInstance(dry_plan, PositionSizingPlan)
        # Dry-run plan has entry price reflecting stressed price (1335.0)
        self.assertEqual(dry_plan.entry_price, 1335.0)
        # Original plan is unaffected
        self.assertEqual(self.plan.entry_price, 1500.0)

    # 22. Risk veto preservation
    def test_22_risk_veto_preservation(self):
        vetoed_plan = self.plan.model_copy(update={
            "veto_applied": True,
            "veto_reasons": ["CRITICAL_SAFETY_BREACH"],
        })
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=vetoed_plan,
            portfolio_state=self.portfolio_dict,
            scenario_def=self.engine.get_standard_scenarios()["MARKET_RALLY_10"],
        )
        dry_plan = self.engine.dry_run_risk(
            candidate_context=self.ctx,
            candidate_plan=vetoed_plan,
            scenario_result=res,
        )
        # Rally scenario cannot remove active risk veto
        self.assertTrue(dry_plan.veto_applied)
        self.assertEqual(dry_plan.position_quantity, 0)

    # 23. Position sizing preservation
    def test_23_position_sizing_preservation(self):
        orig_qty = self.plan.position_quantity
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
            scenario_def=self.engine.get_standard_scenarios()["MARKET_CRASH_20"],
        )
        self.assertEqual(self.plan.position_quantity, orig_qty)

    # 24. Conviction preservation
    def test_24_conviction_preservation(self):
        orig_conv = self.plan.conviction_score
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
            scenario_def=self.engine.get_standard_scenarios()["MARKET_CRASH_20"],
        )
        self.assertEqual(self.plan.conviction_score, orig_conv)
        self.assertEqual(res.conviction_context.baseline_conviction, orig_conv)
        self.assertLess(res.conviction_context.scenario_adjusted_conviction, orig_conv)

    # 25. Scenario resilience
    def test_25_scenario_resilience(self):
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
            scenario_def=self.engine.get_standard_scenarios()["MARKET_CRASH_20"],
        )
        self.assertIn(res.resilience, (ScenarioResilience.WEAK, ScenarioResilience.FRAGILE))

    # 26. Scenario severity
    def test_26_scenario_severity(self):
        res_mild = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
            scenario_def=ScenarioDefinition(scenario_type=ScenarioType.MARKET_CRASH, name="Mild -2%", market_return_shock=-0.02),
        )
        res_severe = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
            scenario_def=self.engine.get_standard_scenarios()["MARKET_CRASH_20"],
        )
        self.assertIn(res_mild.severity, (ScenarioSeverity.LOW, ScenarioSeverity.MODERATE))
        self.assertIn(res_severe.severity, (ScenarioSeverity.HIGH, ScenarioSeverity.SEVERE, ScenarioSeverity.EXTREME))

    # 27. Stress score
    def test_27_stress_score(self):
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
            scenario_def=self.engine.get_standard_scenarios()["MARKET_CRASH_10"],
        )
        self.assertGreaterEqual(res.stress_score, 0.0)
        self.assertLessEqual(res.stress_score, 1.0)

    # 28. Scenario comparison
    def test_28_scenario_comparison(self):
        comp = self.engine.run_scenario_suite(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
        )
        self.assertIsInstance(comp, ScenarioComparison)
        self.assertGreater(len(comp.scenarios), 3)
        self.assertIsNotNone(comp.worst_case_scenario)
        self.assertIsNotNone(comp.most_resilient_scenario)

    # 29. Scenario matrix
    def test_29_scenario_matrix(self):
        mat = self.engine.generate_scenario_matrix(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
        )
        self.assertIsInstance(mat, ScenarioMatrix)
        self.assertGreater(len(mat.rows), 0)

    # 30. Missing market data
    def test_30_missing_market_data(self):
        ctx_sparse = self.ctx.model_copy(update={"sector_data": {}, "technical_indicators": {}})
        res = self.engine.run_scenario(
            candidate_context=ctx_sparse,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
        )
        self.assertIsInstance(res, ScenarioResult)

    # 31. Missing portfolio
    def test_31_missing_portfolio(self):
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=None,
        )
        self.assertIsInstance(res, ScenarioResult)
        self.assertEqual(res.data_quality, ScenarioDataQuality.PARTIAL)

    # 32. Missing sector
    def test_32_missing_sector(self):
        ctx_no_sec = self.ctx.model_copy(update={"sector_data": {}})
        res = self.engine.run_scenario(
            candidate_context=ctx_no_sec,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
            scenario_def=self.engine.get_standard_scenarios()["SECTOR_SHOCK_15"],
        )
        self.assertTrue(any("SECTOR_UNKNOWN" in w for w in res.warnings))

    # 33. Missing benchmark
    def test_33_missing_benchmark(self):
        ctx_no_bm = self.ctx.model_copy(update={"sector_data": {"sector": "IT"}})
        res = self.engine.run_scenario(
            candidate_context=ctx_no_bm,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
        )
        self.assertIsInstance(res, ScenarioResult)

    # 34. Insufficient history
    def test_34_insufficient_history(self):
        ctx_short = self.ctx.model_copy(update={"ohlcv_historical": []})
        res = self.engine.run_scenario(
            candidate_context=ctx_short,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
        )
        self.assertIsInstance(res, ScenarioResult)

    # 35. Stale data
    def test_35_stale_data(self):
        from datetime import timedelta
        stale_portfolio = dict(self.portfolio_dict)
        stale_portfolio["updated_at"] = self.now - timedelta(days=2)
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=stale_portfolio,
        )
        self.assertEqual(res.data_quality, ScenarioDataQuality.STALE)
        self.assertTrue(any("STALE_PORTFOLIO" in w for w in res.warnings))

    # 36. NaN handling
    def test_36_nan_handling(self):
        clean_f = self.engine._clean_number(float("nan"))
        self.assertEqual(clean_f, 0.0)

    # 37. Infinity handling
    def test_37_infinity_handling(self):
        clean_f = self.engine._clean_number(float("inf"))
        self.assertEqual(clean_f, 0.0)

    # 38. Invalid scenario parameters
    def test_38_invalid_scenario_parameters(self):
        with self.assertRaises(ValueError):
            ScenarioDefinition(
                scenario_type=ScenarioType.MARKET_CRASH,
                name="NaN Shock",
                market_return_shock=float("nan"),
            )

    # 39. Provenance
    def test_39_provenance(self):
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
        )
        self.assertGreater(len(res.provenance), 0)
        self.assertTrue(any(p["source"] == "ScenarioEngine" for p in res.provenance))

    # 40. Context ID propagation
    def test_40_context_id_propagation(self):
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
        )
        self.assertEqual(res.context_id, "ctx-scen-p67-001")

    # 41. Portfolio ID propagation
    def test_41_portfolio_id_propagation(self):
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
        )
        self.assertEqual(res.portfolio_id, "port-test-001")

    # 42. Scenario version
    def test_42_scenario_version(self):
        res = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
        )
        self.assertEqual(res.scenario_version, SCENARIO_ENGINE_VERSION)
        self.assertEqual(res.scenario_version, "6.7.0")

    # 43. Deterministic repeatability
    def test_43_deterministic_repeatability(self):
        r1 = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
        )
        r2 = self.engine.run_scenario(
            candidate_context=self.ctx,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
        )
        self.assertEqual(r1.stress_score, r2.stress_score)
        self.assertEqual(r1.position_impact.stressed_price, r2.position_impact.stressed_price)
        self.assertEqual(r1.portfolio_impact.stressed_equity, r2.portfolio_impact.stressed_equity)

    # 44. Degraded mode
    def test_44_degraded_mode(self):
        ctx_degraded = self.ctx.model_copy(update={"current_price": 0.0})
        res = self.engine.run_scenario(
            candidate_context=ctx_degraded,
            candidate_plan=self.plan,
            portfolio_state=self.portfolio_dict,
        )
        self.assertTrue(any("INVALID_PRICE" in w for w in res.warnings))

    # 45. Backward compatibility
    def test_45_backward_compatibility(self):
        # ScenarioEngine can run without portfolio_state or candidate_plan
        res = self.engine.run_scenario(candidate_context=self.ctx)
        self.assertIsInstance(res, ScenarioResult)
        self.assertEqual(res.candidate_symbol, "INFY.NS")

    # 46. Complete end-to-end integration test
    async def test_46_end_to_end_integration(self):
        """
        Complete end-to-end multi-agent pipeline integration:
        MarketContext
        -> Specialists (Technical, Momentum, Quant, Fundamental)
        -> EvidenceAggregator -> EvidenceSummary
        -> DebateEngine -> DebateResult
        -> InvestmentCommittee -> CommitteeDecision
        -> ConvictionCalibrator -> ConvictionCalibrationResult
        -> MarketRegimeEngine -> MarketRegime
        -> PortfolioIntelligenceEngine -> PortfolioIntelligence
        -> ScenarioEngine -> ScenarioResult
        -> RiskEngine dry-run -> PositionSizingPlan
        """
        e2e_ctx = MarketContext(
            context_id="ctx-e2e-p67-full-001",
            symbol="TCS.NS",
            data_timestamp=self.now,
            current_price=3500.0,
            provider="mock-e2e",
            ohlcv_historical=[
                {"timestamp": "2024-01-01T00:00:00Z", "close": 3400.0, "volume": 100000},
                {"timestamp": "2024-01-02T00:00:00Z", "close": 3430.0, "volume": 110000},
                {"timestamp": "2024-01-03T00:00:00Z", "close": 3460.0, "volume": 120000},
                {"timestamp": "2024-01-04T00:00:00Z", "close": 3480.0, "volume": 130000},
                {"timestamp": "2024-01-05T00:00:00Z", "close": 3500.0, "volume": 140000},
            ],
            technical_indicators={"rsi": 62.0, "ema20": 3450.0, "ema50": 3400.0, "20_day_high": 3800.0, "20_day_low": 3300.0},
            sector_data={"sector": "Information Technology", "benchmark_symbol": "^NSEI", "benchmark_return_pct": 2.8, "beta": 1.05},
            fundamental_data={"period": "FY2024", "revenue": 10000.0, "net_income": 1900.0, "eps": 25.0, "total_debt": 500.0, "total_equity": 8000.0},
        )

        agent_input = AgentInput(
            symbol="TCS.NS",
            market_context=e2e_ctx,
            historical_ohlcv=e2e_ctx.ohlcv_historical,
            indicators=e2e_ctx.technical_indicators,
            additional_data={"pe_ratio": 24.5, "net_margin": 19.2},
        )

        # 1. Specialists
        tech_spec = TechnicalSpecialist(llm_client=MockLLMClient(fixed_response=_TechnicalLLMResponse(
            trend=TrendDirection.BULLISH, setup=SetupType.BREAKOUT, technical_score=8.0, confirmation=True, conclusion="Bullish", invalidation_conditions=["EMA20"], risks=["Overbought"], assumptions=["Trend"], confidence=0.85,
        )))
        mom_spec = MomentumSpecialist(llm_client=MockLLMClient(fixed_response=_MomentumLLMResponse(
            momentum_direction=MomentumDirection.BULLISH, momentum_strength=MomentumStrength.STRONG, confirmation=True, conclusion="Accelerating", invalidation_conditions=["Stall"], risks=["Exhaustion"], assumptions=["Volume"], confidence=0.85,
        )))
        quant_spec = QuantSpecialist(llm_client=MockLLMClient(fixed_response=_QuantLLMResponse(
            statistical_regime=QuantStatisticalRegime.NORMAL_VOLATILITY, risk_characterization=QuantRiskCharacterization.SUBDUED, anomaly_detected=False, statistical_strength=0.75, conclusion="Normal", invalidation_conditions=["Surge"], risks=["Fat tail"], assumptions=["Variance"], confidence=0.80,
        )))
        fund_spec = FundamentalSpecialist(llm_client=MockLLMClient(fixed_response=_FundamentalLLMResponse(
            fundamental_quality=FundamentalQuality.STRONG, growth_assessment=GrowthAssessment.HIGH_GROWTH, profitability_assessment=ProfitabilityAssessment.HIGHLY_PROFITABLE, balance_sheet_assessment=BalanceSheetAssessment.HEALTHY, financial_strength=0.85, conclusion="High margins", invalidation_conditions=["Drop"], risks=["Pricing"], assumptions=["Demand"], confidence=0.85,
        )))

        outputs = [
            await tech_spec.execute(agent_input),
            await mom_spec.execute(agent_input),
            await quant_spec.execute(agent_input),
            await fund_spec.execute(agent_input),
        ]
        records = [
            AgentExecutionRecord(
                agent_name=out.agent_name, agent_version=out.version, context_id="ctx-e2e-p67-full-001",
                started_at=self.now, completed_at=self.now, status=out.status, duration_seconds=0.01, output=out,
            )
            for out in outputs
        ]
        run_result = SpecialistRunResult(
            run_id="run-e2e-p67-001", context_id="ctx-e2e-p67-full-001", symbol="TCS.NS",
            started_at=self.now, completed_at=self.now, duration_seconds=0.04, total_agents=4,
            successful_agents=4, failed_agents=0, timed_out_agents=0, degraded_agents=0,
            records=records, outputs=outputs,
        )

        # 2. Evidence Layer
        evidence_summary = EvidenceAggregator().aggregate_evidence(run_result, market_context=e2e_ctx)

        # 3. Debate Engine
        debate_result = await DebateEngine(llm_client=None).run_debate(evidence_summary, market_context=e2e_ctx)

        # 4. Investment Committee
        decision = await InvestmentCommittee(llm_client=None).synthesize_decision(evidence_summary, debate_result, market_context=e2e_ctx)
        decision_approved = decision.model_copy(update={
            "recommendation": CommitteeRecommendation.BUY,
            "conviction_score": 0.85,
            "risk_score": 0.20,
            "risk_veto_applied": False,
        })

        # 5. Conviction Calibration (Phase 6.5)
        calibrator = ConvictionCalibrator()
        calib_res = await calibrator.calibrate(decision_approved, debate_result, evidence_summary, market_context=e2e_ctx)

        # 6. Market Regime Engine (Phase 6.6)
        regime_engine = MarketRegimeEngine()
        market_regime = await regime_engine.evaluate_regime(e2e_ctx)

        # 7. Portfolio Intelligence Engine (Phase 6.6)
        p_engine = PortfolioIntelligenceEngine(default_config=PortfolioConstraintConfig(max_sector_weight=0.50))
        portfolio_state = {
            "portfolio_id": "port-e2e-001",
            "total_equity": 300000.0,
            "cash": 200000.0,
            "positions": {
                "RELIANCE.NS": {"symbol": "RELIANCE.NS", "quantity": 40.0, "current_price": 2500.0, "market_value": 100000.0, "sector": "Energy"},
            },
        }
        p_intel = await p_engine.analyze_portfolio(portfolio_state, candidate_context=e2e_ctx)

        # 8. Baseline Risk Engine Sizing
        risk_engine = RiskEngine(config=RiskConfiguration(account_capital=300000.0, max_position_pct=0.20, max_sector_exposure_pct=0.50))
        plan = await risk_engine.evaluate_and_size(
            decision_approved,
            market_context=e2e_ctx,
            calibration=calib_res,
            portfolio_intelligence=p_intel,
            market_regime=market_regime,
        )

        # 9. Scenario & Stress Testing Engine (Phase 6.7)
        scen_engine = ScenarioEngine(default_risk_engine=risk_engine)
        scen_result = await scen_engine.run_scenario(
            candidate_context=e2e_ctx,
            candidate_plan=plan,
            portfolio_state=portfolio_state,
            scenario_def=scen_engine.get_standard_scenarios()["MARKET_CRASH_10"],
            market_regime=market_regime,
            risk_engine=risk_engine,
        )

        self.assertIsInstance(scen_result, ScenarioResult)
        self.assertEqual(scen_result.context_id, "ctx-e2e-p67-full-001")
        self.assertEqual(scen_result.candidate_symbol, "TCS.NS")
        self.assertEqual(scen_result.scenario_type, ScenarioType.MARKET_CRASH)
        self.assertLess(scen_result.position_impact.stressed_price, plan.entry_price)

        # 10. Risk Engine Dry-Run under Stressed State
        dry_run_plan = scen_engine.dry_run_risk(
            candidate_context=e2e_ctx,
            candidate_plan=plan,
            scenario_result=scen_result,
            portfolio_state=portfolio_state,
        )
        self.assertIsInstance(dry_run_plan, PositionSizingPlan)
        # Stressed entry price is 3500 * (1 - 0.10 * 1.05) = 3132.50
        self.assertEqual(dry_run_plan.entry_price, 3132.50)
        # Real baseline plan is unchanged
        self.assertEqual(plan.entry_price, 3500.0)


if __name__ == "__main__":
    unittest.main()
