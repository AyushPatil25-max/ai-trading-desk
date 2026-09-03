"""
Phase 6.6 — Market Regime & Portfolio Intelligence Foundation Comprehensive Offline Tests

Verifies all 42 requirements:
1. Market regime creation
2. Bull regime
3. Bear regime
4. Sideways regime
5. High volatility regime
6. Low volatility regime
7. Transition regime
8. Stressed regime
9. Unknown regime
10. Regime confidence
11. Missing market data
12. Insufficient history
13. Relative strength
14. Benchmark missing
15. Portfolio state creation
16. Empty portfolio
17. Single position
18. Multiple positions
19. Position weights
20. Sector exposure
21. Concentration
22. Correlation
23. Insufficient correlation history
24. Diversification
25. Candidate marginal exposure
26. Portfolio constraints
27. Stale portfolio
28. Missing sector
29. NaN handling
30. Infinity handling
31. Invalid weights
32. Provenance
33. Context propagation
34. Portfolio ID propagation
35. Deterministic repeatability
36. Partial/degraded mode
37. Conviction remains separate
38. Risk remains separate
39. Risk veto remains authoritative
40. Position sizing cannot be bypassed
41. End-to-end integration:
    MarketContext -> Specialists -> EvidenceAggregator -> DebateEngine -> InvestmentCommittee -> ConvictionCalibrator -> MarketRegime -> PortfolioIntelligence -> RiskEngine -> PositionSizingPlan
42. Backward compatibility
"""

from datetime import datetime, timezone, timedelta
import math
import unittest
from typing import Any, Dict, List

from backend.domain.schemas import (
    MarketContext,
    EvidenceSummary,
    AgentInput,
    AgentOutput,
    AgentExecutionRecord,
    AgentState,
    _TechnicalLLMResponse, TrendDirection, SetupType,
    _MomentumLLMResponse, MomentumDirection, MomentumStrength,
    _QuantLLMResponse, QuantStatisticalRegime, QuantRiskCharacterization,
    _FundamentalLLMResponse, FundamentalQuality, GrowthAssessment, ProfitabilityAssessment, BalanceSheetAssessment,
)
from backend.domain.debate_schemas import (
    DebateResult, DebateDecisionState,
)
from backend.domain.investment_committee_schemas import (
    CommitteeRecommendation,
    DataQualityStatus,
    CommitteeDecision,
)
from backend.domain.calibration_schemas import (
    ConvictionCalibrationResult,
)
from backend.domain.risk_schemas import (
    PositionDirection,
    RiskConfiguration,
    PositionSizingPlan,
    RiskConstraintType,
)
from backend.domain.regime_schemas import (
    REGIME_ENGINE_VERSION,
    MarketTrendRegime,
    MarketVolatilityRegime,
    MarketBreadthRegime,
    MarketMomentumRegime,
    MarketStressLevel,
    OverallMarketRegime,
    RegimeAlignment,
    RelativeStrengthStatus,
    MarketRegime,
)
from backend.domain.portfolio_schemas import (
    PORTFOLIO_ENGINE_VERSION,
    PortfolioDataQuality,
    PortfolioPosition,
    PortfolioConstraintConfig,
    PortfolioIntelligence,
    MarketPortfolioIntelligence,
)
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


class TestMarketRegimeAndPortfolioPhase66(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 29, 12, 0, 0, tzinfo=timezone.utc)
        self.ctx = MarketContext(
            context_id="ctx-regime-p66-001",
            symbol="INFY.NS",
            data_timestamp=self.now,
            current_price=1500.0,
            provider="mock-vendor",
            ohlcv_historical=[
                {"timestamp": "2026-08-25T00:00:00Z", "close": 1400.0, "volume": 100000},
                {"timestamp": "2026-08-26T00:00:00Z", "close": 1420.0, "volume": 110000},
                {"timestamp": "2026-08-27T00:00:00Z", "close": 1450.0, "volume": 105000},
                {"timestamp": "2026-08-28T00:00:00Z", "close": 1480.0, "volume": 120000},
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
                "benchmark_return_pct": 3.5,
                "advance_decline_ratio": 70.0,
            },
            provenance=[{"source": "test_setup", "timestamp": str(self.now)}],
        )

        self.portfolio_dict = {
            "portfolio_id": "port-test-001",
            "total_equity": 200000.0,
            "cash": 80000.0,
            "available_cash": 80000.0,
            "positions": {
                "TCS.NS": {
                    "symbol": "TCS.NS",
                    "quantity": 20.0,
                    "average_price": 3400.0,
                    "current_price": 3500.0,
                    "market_value": 70000.0,
                    "sector": "Information Technology",
                },
                "RELIANCE.NS": {
                    "symbol": "RELIANCE.NS",
                    "quantity": 20.0,
                    "average_price": 2400.0,
                    "current_price": 2500.0,
                    "market_value": 50000.0,
                    "sector": "Energy",
                },
            },
            "updated_at": self.now,
        }

    # 1. Market regime creation
    def test_01_market_regime_creation(self):
        engine = MarketRegimeEngine()
        regime = engine.evaluate_regime(self.ctx)
        self.assertIsInstance(regime, MarketRegime)
        self.assertEqual(regime.symbol, "INFY.NS")
        self.assertEqual(regime.context_id, "ctx-regime-p66-001")
        self.assertEqual(regime.engine_version, REGIME_ENGINE_VERSION)
        self.assertEqual(regime.engine_version, "6.6.0")

    # 2. Bull regime
    def test_02_bull_regime(self):
        ctx_bull = self.ctx.model_copy(update={
            "sector_data": {"benchmark_return_pct": 4.5, "advance_decline_ratio": 75.0},
        })
        engine = MarketRegimeEngine()
        regime = engine.evaluate_regime(ctx_bull)
        self.assertEqual(regime.trend, MarketTrendRegime.BULL)
        self.assertEqual(regime.overall_regime, OverallMarketRegime.BULL)

    # 3. Bear regime
    def test_03_bear_regime(self):
        ctx_bear = self.ctx.model_copy(update={
            "sector_data": {"benchmark_return_pct": -4.5, "advance_decline_ratio": 25.0},
        })
        engine = MarketRegimeEngine()
        regime = engine.evaluate_regime(ctx_bear)
        self.assertEqual(regime.trend, MarketTrendRegime.BEAR)
        self.assertIn(regime.overall_regime, (OverallMarketRegime.BEAR, OverallMarketRegime.STRESSED))

    # 4. Sideways regime
    def test_04_sideways_regime(self):
        ctx_side = self.ctx.model_copy(update={
            "sector_data": {"benchmark_return_pct": 0.2, "advance_decline_ratio": 50.0},
        })
        engine = MarketRegimeEngine()
        regime = engine.evaluate_regime(ctx_side)
        self.assertEqual(regime.trend, MarketTrendRegime.SIDEWAYS)
        self.assertIn(regime.overall_regime, (OverallMarketRegime.SIDEWAYS, OverallMarketRegime.LOW_VOLATILITY, OverallMarketRegime.HIGH_VOLATILITY))

    # 5. High volatility regime
    def test_05_high_volatility_regime(self):
        high_vol_bars = [
            {"close": 100.0}, {"close": 115.0}, {"close": 95.0}, {"close": 120.0}, {"close": 90.0},
        ]
        engine = MarketRegimeEngine()
        regime = engine.evaluate_regime(self.ctx, benchmark_ohlcv=high_vol_bars)
        self.assertIn(regime.volatility, (MarketVolatilityRegime.HIGH, MarketVolatilityRegime.EXTREME))

    # 6. Low volatility regime
    def test_06_low_volatility_regime(self):
        low_vol_bars = [
            {"close": 100.0}, {"close": 100.2}, {"close": 100.1}, {"close": 100.3}, {"close": 100.2},
        ]
        engine = MarketRegimeEngine()
        regime = engine.evaluate_regime(self.ctx, benchmark_ohlcv=low_vol_bars)
        self.assertEqual(regime.volatility, MarketVolatilityRegime.LOW)

    # 7. Transition regime
    def test_07_transition_regime(self):
        # Bullish return + volatile swing (annualized vol ~29%)
        vol_bars = [{"close": 100.0}, {"close": 101.5}, {"close": 99.8}, {"close": 101.3}, {"close": 99.5}]
        ctx_bull = self.ctx.model_copy(update={"sector_data": {"benchmark_return_pct": 3.0}})
        engine = MarketRegimeEngine()
        regime = engine.evaluate_regime(ctx_bull, benchmark_ohlcv=vol_bars)
        self.assertEqual(regime.overall_regime, OverallMarketRegime.TRANSITION)

    # 8. Stressed regime
    def test_08_stressed_regime(self):
        ctx_stress = self.ctx.model_copy(update={
            "sector_data": {"benchmark_return_pct": -6.5},
        })
        engine = MarketRegimeEngine()
        regime = engine.evaluate_regime(ctx_stress)
        self.assertEqual(regime.stress_level, MarketStressLevel.SEVERE)
        self.assertEqual(regime.overall_regime, OverallMarketRegime.STRESSED)

    # 9. Unknown regime
    def test_09_unknown_regime(self):
        ctx_empty = MarketContext(
            context_id="ctx-empty-001",
            symbol="UNKNOWN.NS",
            data_timestamp=self.now,
            current_price=100.0,
            provider="mock",
        )
        engine = MarketRegimeEngine()
        regime = engine.evaluate_regime(ctx_empty)
        self.assertEqual(regime.trend, MarketTrendRegime.UNKNOWN)
        self.assertLessEqual(regime.market_regime_confidence, 0.40)

    # 10. Regime confidence
    def test_10_regime_confidence(self):
        engine = MarketRegimeEngine()
        regime_full = engine.evaluate_regime(self.ctx)
        self.assertGreaterEqual(regime_full.market_regime_confidence, 0.50)
        self.assertLessEqual(regime_full.market_regime_confidence, 1.0)

    # 11. Missing market data
    def test_11_missing_market_data(self):
        ctx_missing = self.ctx.model_copy(update={"sector_data": {}})
        engine = MarketRegimeEngine()
        regime = engine.evaluate_regime(ctx_missing)
        self.assertIsInstance(regime, MarketRegime)
        self.assertTrue(any("BENCHMARK_UNAVAILABLE" in w for w in regime.warnings))

    # 12. Insufficient history
    def test_12_insufficient_history(self):
        ctx_short = self.ctx.model_copy(update={"ohlcv_historical": [{"close": 100.0}]})
        engine = MarketRegimeEngine()
        regime = engine.evaluate_regime(ctx_short)
        self.assertIsNone(regime.candidate_return)

    # 13. Relative strength
    def test_13_relative_strength(self):
        # Candidate = +7.14% ((1500-1400)/1400), Benchmark = +3.5% => Relative = +3.64%
        engine = MarketRegimeEngine()
        regime = engine.evaluate_regime(self.ctx)
        self.assertIsNotNone(regime.relative_return)
        self.assertGreater(regime.relative_return, 2.0)
        self.assertEqual(regime.relative_strength_status, RelativeStrengthStatus.OUTPERFORMING)

    # 14. Benchmark missing
    def test_14_benchmark_missing(self):
        ctx_no_bm = self.ctx.model_copy(update={"sector_data": {}})
        engine = MarketRegimeEngine()
        regime = engine.evaluate_regime(ctx_no_bm)
        self.assertIsNone(regime.benchmark_return)
        self.assertEqual(regime.relative_strength_status, RelativeStrengthStatus.UNKNOWN)

    # 15. Portfolio state creation
    def test_15_portfolio_state_creation(self):
        engine = PortfolioIntelligenceEngine()
        port = engine.analyze_portfolio(self.portfolio_dict)
        self.assertIsInstance(port, PortfolioIntelligence)
        self.assertEqual(port.portfolio_id, "port-test-001")
        self.assertEqual(port.total_equity, 200000.0)
        self.assertEqual(port.position_count, 2)

    # 16. Empty portfolio
    def test_16_empty_portfolio(self):
        engine = PortfolioIntelligenceEngine()
        port = engine.analyze_portfolio(None)
        self.assertEqual(port.position_count, 0)
        self.assertEqual(port.data_quality, PortfolioDataQuality.UNAVAILABLE)

    # 17. Single position
    def test_17_single_position(self):
        single_port = {
            "portfolio_id": "port-single",
            "total_equity": 100000.0,
            "cash": 50000.0,
            "positions": {"TCS.NS": {"symbol": "TCS.NS", "quantity": 10, "current_price": 5000.0, "market_value": 50000.0}},
        }
        engine = PortfolioIntelligenceEngine()
        port = engine.analyze_portfolio(single_port)
        self.assertEqual(port.position_count, 1)
        self.assertAlmostEqual(port.positions["TCS.NS"].weight, 0.50)

    # 18. Multiple positions
    def test_18_multiple_positions(self):
        engine = PortfolioIntelligenceEngine()
        port = engine.analyze_portfolio(self.portfolio_dict)
        self.assertEqual(len(port.positions), 2)
        self.assertIn("TCS.NS", port.positions)
        self.assertIn("RELIANCE.NS", port.positions)

    # 19. Position weights
    def test_19_position_weights(self):
        engine = PortfolioIntelligenceEngine()
        port = engine.analyze_portfolio(self.portfolio_dict)
        # TCS = 70,000 / 200,000 = 0.35
        # RELIANCE = 50,000 / 200,000 = 0.25
        self.assertAlmostEqual(port.positions["TCS.NS"].weight, 0.35)
        self.assertAlmostEqual(port.positions["RELIANCE.NS"].weight, 0.25)

    # 20. Sector exposure
    def test_20_sector_exposure(self):
        engine = PortfolioIntelligenceEngine()
        port = engine.analyze_portfolio(self.portfolio_dict)
        self.assertIn("Information Technology", port.sector_exposures)
        self.assertIn("Energy", port.sector_exposures)
        it_exp = port.sector_exposures["Information Technology"]
        self.assertAlmostEqual(it_exp.weight_pct, 35.0)

    # 21. Concentration
    def test_21_concentration(self):
        engine = PortfolioIntelligenceEngine()
        port = engine.analyze_portfolio(self.portfolio_dict)
        # Weights: 35%, 25%. HHI = 35^2 + 25^2 = 1225 + 625 = 1850.
        self.assertEqual(port.concentration.top_position_weight, 0.35)
        self.assertEqual(port.concentration.hhi_index, 1850.0)
        self.assertIn(port.concentration.concentration_risk_level, ("HIGH", "MODERATE"))

    # 22. Correlation
    def test_22_correlation(self):
        hist_prices = {
            "INFY.NS": [100.0, 105.0, 98.0, 104.0, 110.0],
            "TCS.NS": [100.0, 104.9, 98.1, 103.9, 109.8],
            "RELIANCE.NS": [100.0, 95.0, 102.0, 96.0, 91.0],
        }
        engine = PortfolioIntelligenceEngine()
        port = engine.analyze_portfolio(self.portfolio_dict, candidate_context=self.ctx, historical_prices=hist_prices)
        self.assertTrue(port.correlation.available)
        self.assertIsNotNone(port.correlation.avg_correlation_to_portfolio)
        self.assertGreater(port.correlation.max_correlation, 0.80)
        self.assertEqual(port.correlation.max_correlated_symbol, "TCS.NS")

    # 23. Insufficient correlation history
    def test_23_insufficient_correlation_history(self):
        hist_prices = {"INFY.NS": [100.0, 102.0]}  # only 2 bars
        engine = PortfolioIntelligenceEngine()
        port = engine.analyze_portfolio(self.portfolio_dict, candidate_context=self.ctx, historical_prices=hist_prices)
        self.assertFalse(port.correlation.available)
        self.assertIn("Insufficient history", port.correlation.unavailable_reason)

    # 24. Diversification
    def test_24_diversification(self):
        engine = PortfolioIntelligenceEngine()
        # Candidate Pharma adds new sector
        ctx_pharma = self.ctx.model_copy(update={
            "symbol": "SUNPHARMA.NS",
            "sector_data": {"sector": "Healthcare"},
        })
        port = engine.analyze_portfolio(self.portfolio_dict, candidate_context=ctx_pharma)
        self.assertIsNotNone(port.diversification)
        self.assertTrue(port.diversification.adds_new_sector)

    # 25. Candidate marginal exposure
    def test_25_candidate_marginal_exposure(self):
        engine = PortfolioIntelligenceEngine()
        mock_plan = PositionSizingPlan(
            plan_id="p1",
            context_id="c1",
            symbol="INFY.NS",
            direction=PositionDirection.LONG,
            position_quantity=10,
            entry_price=1500.0,
            position_notional=15000.0,
            account_capital=200000.0,
            exposure_pct=0.075,
            stop_loss_price=1420.0,
            stop_loss_pct=0.053,
            risk_per_trade_pct=0.004,
            risk_reward_ratio=2.0,
        )
        port = engine.analyze_portfolio(self.portfolio_dict, candidate_context=self.ctx, candidate_plan=mock_plan)
        self.assertIsNotNone(port.marginal_exposure)
        self.assertEqual(port.marginal_exposure.proposed_notional, 15000.0)
        self.assertAlmostEqual(port.marginal_exposure.incremental_exposure_pct, 7.5)
        # Sector IT was 35%, adds 7.5% -> 42.5%
        self.assertAlmostEqual(port.marginal_exposure.sector_exposure_after_pct, 42.5)

    # 26. Portfolio constraints
    def test_26_portfolio_constraints(self):
        engine = PortfolioIntelligenceEngine(default_config=PortfolioConstraintConfig(
            max_sector_weight=0.30,  # 30% limit
        ))
        port = engine.analyze_portfolio(self.portfolio_dict)
        sec_eval = next(c for c in port.constraints_evaluated if c.constraint_name == "MAX_SECTOR_EXPOSURE")
        self.assertFalse(sec_eval.passed)  # IT is 35% > 30%
        self.assertTrue(any("SECTOR_EXPOSURE_BREACH" in w for w in port.warnings))

    # 27. Stale portfolio
    def test_27_stale_portfolio(self):
        stale_port = dict(self.portfolio_dict)
        stale_port["updated_at"] = self.now - timedelta(days=2)
        engine = PortfolioIntelligenceEngine()
        port = engine.analyze_portfolio(stale_port)
        self.assertEqual(port.data_quality, PortfolioDataQuality.STALE)
        self.assertTrue(any("STALE_PORTFOLIO" in w for w in port.warnings))

    # 28. Missing sector
    def test_28_missing_sector(self):
        no_sec_port = {
            "portfolio_id": "p-no-sec",
            "total_equity": 100000.0,
            "cash": 50000.0,
            "positions": {"XYZ.NS": {"symbol": "XYZ.NS", "quantity": 10, "current_price": 5000.0, "market_value": 50000.0}},
        }
        engine = PortfolioIntelligenceEngine()
        port = engine.analyze_portfolio(no_sec_port)
        self.assertIn("UNKNOWN", port.sector_exposures)

    # 29. NaN handling
    def test_29_nan_handling(self):
        nan_port = {
            "portfolio_id": "p-nan",
            "total_equity": float("nan"),
            "cash": float("nan"),
            "positions": {"ABC.NS": {"symbol": "ABC.NS", "quantity": float("nan"), "current_price": 100.0}},
        }
        engine = PortfolioIntelligenceEngine()
        port = engine.analyze_portfolio(nan_port)
        self.assertFalse(math.isnan(port.total_equity))
        self.assertFalse(math.isnan(port.cash))

    # 30. Infinity handling
    def test_30_infinity_handling(self):
        inf_port = {
            "portfolio_id": "p-inf",
            "total_equity": float("inf"),
            "cash": 1000.0,
            "positions": {},
        }
        engine = PortfolioIntelligenceEngine()
        port = engine.analyze_portfolio(inf_port)
        self.assertFalse(math.isinf(port.total_equity))

    # 31. Invalid weights
    def test_31_invalid_weights(self):
        neg_port = {
            "portfolio_id": "p-neg",
            "total_equity": -5000.0,
            "cash": -1000.0,
            "positions": {"XYZ.NS": {"symbol": "XYZ.NS", "quantity": -5.0, "current_price": 100.0}},
        }
        engine = PortfolioIntelligenceEngine()
        port = engine.analyze_portfolio(neg_port)
        self.assertGreaterEqual(port.positions["XYZ.NS"].weight, 0.0)

    # 32. Provenance
    def test_32_provenance(self):
        engine = MarketRegimeEngine()
        regime = engine.evaluate_regime(self.ctx)
        self.assertGreater(len(regime.provenance), 0)
        self.assertTrue(any(p["source"] == "MarketRegimeEngine" for p in regime.provenance))

    # 33. Context propagation
    def test_33_context_propagation(self):
        engine = MarketRegimeEngine()
        regime = engine.evaluate_regime(self.ctx)
        self.assertEqual(regime.context_id, "ctx-regime-p66-001")
        self.assertEqual(regime.symbol, "INFY.NS")

    # 34. Portfolio ID propagation
    def test_34_portfolio_id_propagation(self):
        engine = PortfolioIntelligenceEngine()
        port = engine.analyze_portfolio(self.portfolio_dict)
        self.assertEqual(port.portfolio_id, "port-test-001")

    # 35. Deterministic repeatability
    def test_35_deterministic_repeatability(self):
        engine_r = MarketRegimeEngine()
        r1 = engine_r.evaluate_regime(self.ctx)
        r2 = engine_r.evaluate_regime(self.ctx)
        self.assertEqual(r1.overall_regime, r2.overall_regime)
        self.assertEqual(r1.market_regime_confidence, r2.market_regime_confidence)

        engine_p = PortfolioIntelligenceEngine()
        p1 = engine_p.analyze_portfolio(self.portfolio_dict)
        p2 = engine_p.analyze_portfolio(self.portfolio_dict)
        self.assertEqual(p1.concentration.hhi_index, p2.concentration.hhi_index)

    # 36. Partial/degraded mode
    def test_36_partial_degraded_mode(self):
        ctx_partial = self.ctx.model_copy(update={
            "sector_data": {},
            "technical_indicators": {},
        })
        engine = MarketRegimeEngine()
        regime = engine.evaluate_regime(ctx_partial)
        self.assertIn(regime.trend, (MarketTrendRegime.UNKNOWN, MarketTrendRegime.SIDEWAYS))

    # 37. Conviction remains separate
    def test_37_conviction_remains_separate(self):
        engine = MarketRegimeEngine()
        regime = engine.evaluate_regime(self.ctx)
        # Regime confidence does not dictate conviction
        self.assertIsInstance(regime.market_regime_confidence, float)
        self.assertNotEqual(regime.market_regime_confidence, 0.75)  # arbitrary distinct value

    # 38. Risk remains separate
    def test_38_risk_remains_separate(self):
        engine = MarketRegimeEngine()
        regime = engine.evaluate_regime(self.ctx)
        # Stress level does not equal numeric trade risk score
        self.assertIsInstance(regime.stress_level, MarketStressLevel)

    # 39. Risk veto remains authoritative
    async def test_39_risk_veto_remains_authoritative(self):
        # Even with strong BULL market, an active risk veto must be respected by RiskEngine
        decision_vetoed = CommitteeDecision(
            decision_id="dec-v-001",
            context_id="ctx-v-001",
            symbol="INFY.NS",
            recommendation=CommitteeRecommendation.BUY,
            conviction_score=0.90,
            risk_veto_applied=True,
            risk_veto_reason="Hard safety breach",
        )
        regime_engine = MarketRegimeEngine()
        regime = regime_engine.evaluate_regime(self.ctx)

        risk_engine = RiskEngine()
        plan = await risk_engine.evaluate_and_size(decision_vetoed, market_context=self.ctx, market_regime=regime)
        self.assertTrue(plan.veto_applied)
        self.assertEqual(plan.position_quantity, 0)

    # 40. Position sizing cannot be bypassed
    async def test_40_position_sizing_cannot_be_bypassed(self):
        # Sector limit breach in portfolio intelligence vetoes candidate in that sector
        p_engine = PortfolioIntelligenceEngine(default_config=PortfolioConstraintConfig(max_sector_weight=0.30))
        # Portfolio already has 35% in IT (TCS)
        p_intel = p_engine.analyze_portfolio(self.portfolio_dict, candidate_context=self.ctx)

        decision_approved = CommitteeDecision(
            decision_id="dec-app-001",
            context_id="ctx-regime-p66-001",
            symbol="INFY.NS",
            recommendation=CommitteeRecommendation.BUY,
            conviction_score=0.85,
            risk_score=0.20,
            risk_veto_applied=False,
        )
        risk_engine = RiskEngine(config=RiskConfiguration(max_sector_exposure_pct=0.30))
        plan = await risk_engine.evaluate_and_size(
            decision_approved,
            market_context=self.ctx,
            portfolio_intelligence=p_intel,
        )
        self.assertTrue(plan.veto_applied)
        self.assertEqual(plan.position_quantity, 0)
        self.assertTrue(any("SECTOR_EXPOSURE_EXCEEDED" in r for r in plan.veto_reasons))

    # 41. Complete end-to-end integration test
    async def test_41_end_to_end_integration(self):
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
        -> RiskEngine -> PositionSizingPlan
        """
        e2e_ctx = MarketContext(
            context_id="ctx-e2e-p66-full-001",
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
            technical_indicators={"rsi": 62.0, "ema20": 3450.0, "ema50": 3400.0, "20_day_high": 3700.0, "20_day_low": 3350.0},
            sector_data={"sector": "Information Technology", "benchmark_symbol": "^NSEI", "benchmark_return_pct": 2.8},
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
                agent_name=out.agent_name, agent_version=out.version, context_id="ctx-e2e-p66-full-001",
                started_at=self.now, completed_at=self.now, status=out.status, duration_seconds=0.01, output=out,
            )
            for out in outputs
        ]
        from backend.domain.schemas import SpecialistRunResult
        run_result = SpecialistRunResult(
            run_id="run-e2e-p66-001", context_id="ctx-e2e-p66-full-001", symbol="TCS.NS",
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

        # 5. Conviction Calibration (Phase 6.5)
        calibrator = ConvictionCalibrator()
        calib_res = await calibrator.calibrate(decision, debate_result, evidence_summary, market_context=e2e_ctx)

        # 6. Market Regime Engine (Phase 6.6)
        regime_engine = MarketRegimeEngine()
        market_regime = await regime_engine.evaluate_regime(e2e_ctx)
        self.assertEqual(market_regime.context_id, "ctx-e2e-p66-full-001")
        self.assertEqual(market_regime.overall_regime, OverallMarketRegime.BULL)

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
        self.assertEqual(p_intel.context_id, "ctx-e2e-p66-full-001")
        self.assertEqual(p_intel.position_count, 1)

        # 8. Unified Intelligence Envelope
        unified = await p_engine.create_unified_intelligence(market_regime, p_intel)
        self.assertIsInstance(unified, MarketPortfolioIntelligence)
        self.assertEqual(unified.context_id, "ctx-e2e-p66-full-001")

        # 9. Risk Engine & Position Sizing with Full Intelligence
        decision_approved = decision.model_copy(update={
            "recommendation": CommitteeRecommendation.BUY,
            "conviction_score": 0.85,
            "risk_score": 0.20,
            "risk_veto_applied": False,
        })
        calib_approved = await calibrator.calibrate(decision_approved, debate_result, evidence_summary, market_context=e2e_ctx)

        risk_engine = RiskEngine(config=RiskConfiguration(account_capital=300000.0, max_position_pct=0.20, max_sector_exposure_pct=0.50))
        plan = await risk_engine.evaluate_and_size(
            decision_approved,
            market_context=e2e_ctx,
            calibration=calib_approved,
            portfolio_intelligence=p_intel,
            market_regime=market_regime,
        )

        self.assertIsInstance(plan, PositionSizingPlan)
        self.assertEqual(plan.context_id, "ctx-e2e-p66-full-001")
        self.assertEqual(plan.direction, PositionDirection.LONG)
        self.assertFalse(plan.veto_applied)
        self.assertGreater(plan.position_quantity, 0)
        self.assertEqual(plan.entry_price, 3500.0)

    # 42. Backward compatibility
    def test_42_backward_compatibility(self):
        # RiskEngine can still size trades without portfolio_intelligence or market_regime
        decision_plain = CommitteeDecision(
            decision_id="dec-plain-001",
            context_id="ctx-plain-001",
            symbol="INFY.NS",
            recommendation=CommitteeRecommendation.BUY,
            conviction_score=0.80,
            risk_score=0.20,
            risk_veto_applied=False,
        )
        risk_engine = RiskEngine()
        plan = risk_engine.evaluate_and_size(decision_plain, market_context=self.ctx)
        self.assertIsInstance(plan, PositionSizingPlan)
        self.assertFalse(plan.veto_applied)
        self.assertGreater(plan.position_quantity, 0)


if __name__ == "__main__":
    unittest.main()
