"""
Phase 6.4 — Risk Management & Position Sizing Engine Comprehensive Offline Tests

Verifies all 36 requirements:
1. Risk engine creation
2. Configuration validation
3. Valid long position
4. Valid short position
5. Invalid long stop
6. Invalid short stop
7. Zero risk distance
8. Negative entry price
9. Negative account capital
10. Position size calculation (manual verification)
11. Position quantity flooring
12. Maximum position constraint
13. Maximum risk constraint
14. Maximum exposure constraint (with portfolio state)
15. Conviction-based restriction
16. Risk veto
17. Existing committee veto
18. Insufficient evidence
19. Missing fundamental data
20. Missing quant data
21. Degraded specialist
22. Failed specialist
23. Stale data
24. Risk/reward calculation
25. Invalid risk/reward
26. Short position risk/reward
27. NaN handling
28. Infinity handling
29. Zero quantity
30. Provenance preservation
31. context_id propagation
32. decision_id propagation
33. Deterministic repeatability
34. MarketContext immutability
35. Backward compatibility
36. Complete end-to-end integration:
    MarketContext -> Specialists -> EvidenceAggregator -> DebateEngine -> InvestmentCommittee -> RiskEngine -> PositionSizingPlan
"""

from copy import deepcopy
from datetime import datetime, timezone
import math
import unittest
from typing import Any, Dict, List

from backend.domain.schemas import (
    MarketContext,
    EvidenceSummary,
    EvidenceRecord,
    EvidenceCategory,
    SignalDirection,
    EvidenceType,
    SpecialistRunResult,
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
    DebateResult, DebateArgument, DebateSide, DebateDecisionState, RiskAssessment,
)
from backend.domain.investment_committee_schemas import (
    CommitteeRecommendation,
    DataQualityStatus,
    CommitteeDecision,
)
from backend.domain.risk_schemas import (
    PositionDirection,
    StopLossMethod,
    RiskConstraintType,
    RiskConfiguration,
    PositionSizingPlan,
)
from backend.domain.execution_schemas import PortfolioState, Position
from backend.application.risk_engine import RiskEngine
from backend.application.investment_committee import InvestmentCommittee
from backend.application.debate_engine import DebateEngine
from backend.application.evidence_aggregator import EvidenceAggregator
from backend.specialists.technical_specialist import TechnicalSpecialist
from backend.specialists.momentum_specialist import MomentumSpecialist
from backend.specialists.quant_specialist import QuantSpecialist
from backend.specialists.fundamental_specialist import FundamentalSpecialist
from backend.infrastructure.llm import MockLLMClient


class TestRiskManagementPhase64(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 29, 12, 0, 0, tzinfo=timezone.utc)
        self.ctx = MarketContext(
            context_id="ctx-risk-p64-001",
            symbol="INFY.NS",
            data_timestamp=self.now,
            current_price=100.0,
            provider="mock-vendor",
            technical_indicators={
                "rsi": 65.0,
                "ema20": 96.0,
                "ema50": 95.0,
                "20_day_high": 115.0,
                "20_day_low": 90.0,
            },
            provenance=[{"source": "test_setup", "timestamp": str(self.now)}],
        )

        self.decision = CommitteeDecision(
            decision_id="dec-risk-p64-001",
            run_id="run-risk-001",
            context_id="ctx-risk-p64-001",
            symbol="INFY.NS",
            decision_timestamp=self.now,
            started_at=self.now,
            completed_at=self.now,
            duration_seconds=0.1,
            recommendation=CommitteeRecommendation.BUY,
            conviction_score=0.80,
            confidence=0.85,
            time_horizon="MEDIUM_TERM",
            supporting_evidence_ids=["ev-101"],
            opposing_evidence_ids=[],
            strongest_bull_arguments=[],
            strongest_bear_arguments=[],
            unresolved_contradictions=[],
            risk_score=0.25,
            risk_level="LOW",
            risk_veto_applied=False,
            data_quality=DataQualityStatus.AVAILABLE,
            investment_thesis="Sound momentum and fundamental valuation.",
            decision_summary="Approved buy recommendation.",
            why_bull_case_wins="Clear upside momentum.",
            why_bear_case_wins="Downside limited.",
            what_would_change_the_decision="Close below 95.0.",
        )

    # 1. Risk engine creation
    def test_01_risk_engine_creation(self):
        default_engine = RiskEngine()
        self.assertEqual(default_engine.config.account_capital, 100000.0)
        self.assertEqual(default_engine.config.max_trade_risk_pct, 0.01)

        custom_cfg = RiskConfiguration(account_capital=250000.0, max_trade_risk_pct=0.02)
        custom_engine = RiskEngine(config=custom_cfg)
        self.assertEqual(custom_engine.config.account_capital, 250000.0)
        self.assertEqual(custom_engine.config.max_trade_risk_pct, 0.02)

    # 2. Configuration validation
    def test_02_configuration_validation(self):
        with self.assertRaises(ValueError):
            RiskConfiguration(account_capital=-5000.0)
        with self.assertRaises(ValueError):
            RiskConfiguration(account_capital=float("nan"))
        with self.assertRaises(ValueError):
            RiskConfiguration(max_trade_risk_pct=0.25, max_position_pct=0.10)

    # 3. Valid long position
    def test_03_valid_long_position(self):
        engine = RiskEngine()
        plan = engine.evaluate_and_size(self.decision, self.ctx)
        self.assertIsInstance(plan, PositionSizingPlan)
        self.assertEqual(plan.direction, PositionDirection.LONG)
        self.assertFalse(plan.veto_applied)
        self.assertGreater(plan.position_quantity, 0)
        self.assertEqual(plan.entry_price, 100.0)
        self.assertLess(plan.stop_loss_price, plan.entry_price)

    # 4. Valid short position
    def test_04_valid_short_position(self):
        short_cfg = RiskConfiguration(allow_short=True)
        engine = RiskEngine(config=short_cfg)
        short_decision = deepcopy(self.decision)
        short_decision.recommendation = CommitteeRecommendation.SELL
        plan = engine.evaluate_and_size(short_decision, self.ctx)
        self.assertEqual(plan.direction, PositionDirection.SHORT)
        self.assertFalse(plan.veto_applied)
        self.assertGreater(plan.position_quantity, 0)
        self.assertGreater(plan.stop_loss_price, plan.entry_price)

    # 5. Invalid long stop
    def test_05_invalid_long_stop(self):
        engine = RiskEngine()
        plan = engine.evaluate_and_size(self.decision, self.ctx, explicit_stop_loss=105.0)
        self.assertTrue(plan.veto_applied)
        self.assertEqual(plan.position_quantity, 0)
        self.assertTrue(any("INVALID_LONG_STOP" in r for r in plan.veto_reasons))

    # 6. Invalid short stop
    def test_06_invalid_short_stop(self):
        engine = RiskEngine(config=RiskConfiguration(allow_short=True))
        short_decision = deepcopy(self.decision)
        short_decision.recommendation = CommitteeRecommendation.SELL
        plan = engine.evaluate_and_size(short_decision, self.ctx, explicit_stop_loss=95.0)
        self.assertTrue(plan.veto_applied)
        self.assertEqual(plan.position_quantity, 0)
        self.assertTrue(any("INVALID_SHORT_STOP" in r for r in plan.veto_reasons))

    # 7. Zero risk distance
    def test_07_zero_risk_distance(self):
        engine = RiskEngine()
        plan = engine.evaluate_and_size(self.decision, self.ctx, explicit_stop_loss=100.0)
        self.assertTrue(plan.veto_applied)
        self.assertEqual(plan.position_quantity, 0)
        self.assertTrue(any("ZERO_RISK_DISTANCE" in r for r in plan.veto_reasons))

    # 8. Negative entry price
    def test_08_negative_entry_price(self):
        bad_ctx = self.ctx.model_copy(update={"current_price": -10.0})
        engine = RiskEngine()
        plan = engine.evaluate_and_size(self.decision, bad_ctx)
        self.assertTrue(plan.veto_applied)
        self.assertEqual(plan.position_quantity, 0)
        self.assertTrue(any("INVALID_PRICE" in r for r in plan.veto_reasons))

    # 9. Negative account capital
    def test_09_negative_account_capital(self):
        engine = RiskEngine()
        engine.config = engine.config.model_construct(account_capital=-1000.0)
        plan = engine.evaluate_and_size(self.decision, self.ctx)
        self.assertTrue(plan.veto_applied)
        self.assertEqual(plan.position_quantity, 0)
        self.assertTrue(any("INVALID_CAPITAL" in r for r in plan.veto_reasons))

    # 10. Position size calculation (manual verification)
    def test_10_position_size_calculation(self):
        """
        Verification:
        capital = 100,000
        max_trade_risk_pct = 1%
        conviction_score = 1.0 -> multiplier = 1.0
        risk budget = 100,000 * 0.01 * 1.0 = 1000.0
        entry = 100.0
        stop = 95.0
        risk/share = 5.0
        raw_quantity = 1000 / 5 = 200
        allocation_limit = 100,000 * 0.10 / 100 = 100 shares
        quantity = min(200, 100) = 100
        notional = 100 * 100 = 10,000
        """
        cfg = RiskConfiguration(
            account_capital=100000.0,
            max_trade_risk_pct=0.01,
            max_position_pct=0.10,
        )
        dec = deepcopy(self.decision)
        dec.conviction_score = 1.0
        engine = RiskEngine(config=cfg)
        plan = engine.evaluate_and_size(dec, self.ctx, explicit_stop_loss=95.0)
        self.assertEqual(plan.position_quantity, 100)
        self.assertEqual(plan.position_notional, 10000.0)
        self.assertEqual(plan.exposure_pct, 0.10)

    # 11. Position quantity flooring
    def test_11_position_quantity_flooring(self):
        cfg = RiskConfiguration(account_capital=100000.0, max_trade_risk_pct=0.01, max_position_pct=0.50)
        dec = deepcopy(self.decision)
        dec.conviction_score = 1.0
        engine = RiskEngine(config=cfg)
        # risk_budget = 1000, risk_per_share = 2.9 => 1000 / 2.9 = 344.8275...
        plan = engine.evaluate_and_size(dec, self.ctx, explicit_stop_loss=97.1)
        self.assertEqual(plan.position_quantity, 344)

    # 12. Maximum position constraint
    def test_12_maximum_position_constraint(self):
        # Stop loss is very tight (99.9), so risk/share is only 0.10
        # Risk budget allows 1000 / 0.10 = 10,000 shares
        # But max position is 10% of 100,000 = $10,000 => 100 shares
        cfg = RiskConfiguration(account_capital=100000.0, max_position_pct=0.10)
        engine = RiskEngine(config=cfg)
        plan = engine.evaluate_and_size(self.decision, self.ctx, explicit_stop_loss=99.9)
        self.assertEqual(plan.position_quantity, 100)

    # 13. Maximum risk constraint
    def test_13_maximum_risk_constraint(self):
        # Wide stop loss (90.0), risk/share = 10.0
        # Risk budget allows 800 / 10 = 80 shares
        # Max position allows 10,000 / 100 = 100 shares
        # Sizing should be constrained to 80 shares
        cfg = RiskConfiguration(account_capital=100000.0, max_trade_risk_pct=0.01, max_position_pct=0.50)
        dec = deepcopy(self.decision)
        dec.conviction_score = 1.0
        engine = RiskEngine(config=cfg)
        plan = engine.evaluate_and_size(dec, self.ctx, explicit_stop_loss=90.0)
        self.assertEqual(plan.position_quantity, 100)

    # 14. Maximum exposure constraint (with portfolio state)
    def test_14_maximum_exposure_constraint(self):
        # Single asset limit is 20% = $20,000
        # Existing position is already $15,000
        # Remaining budget = $5,000 => 50 shares
        cfg = RiskConfiguration(account_capital=100000.0, max_single_asset_exposure_pct=0.20, max_position_pct=0.50)
        engine = RiskEngine(config=cfg)
        pos = Position(symbol="INFY.NS", quantity=150, current_price=100.0, market_value=15000.0)
        port_state = PortfolioState(
            portfolio_id="port-test-01",
            initial_cash=100000.0,
            cash=85000.0,
            available_cash=85000.0,
            positions={"INFY.NS": pos},
            total_market_value=15000.0,
            total_equity=100000.0,
        )
        plan = engine.evaluate_and_size(self.decision, self.ctx, portfolio_state=port_state, explicit_stop_loss=95.0)
        self.assertEqual(plan.position_quantity, 50)

    # 15. Conviction-based restriction
    def test_15_conviction_based_restriction(self):
        # Lower conviction scales down risk budget
        dec_high = deepcopy(self.decision)
        dec_high.conviction_score = 0.90
        dec_low = deepcopy(self.decision)
        dec_low.conviction_score = 0.45

        cfg = RiskConfiguration(account_capital=100000.0, max_position_pct=0.50)
        engine = RiskEngine(config=cfg)
        plan_high = engine.evaluate_and_size(dec_high, self.ctx, explicit_stop_loss=95.0)
        plan_low = engine.evaluate_and_size(dec_low, self.ctx, explicit_stop_loss=95.0)
        self.assertGreater(plan_high.position_quantity, plan_low.position_quantity)

    # 16. Risk veto
    def test_16_risk_veto(self):
        high_risk_dec = deepcopy(self.decision)
        high_risk_dec.risk_score = 0.85 # > 0.75 max allowed
        engine = RiskEngine()
        plan = engine.evaluate_and_size(high_risk_dec, self.ctx)
        self.assertTrue(plan.veto_applied)
        self.assertEqual(plan.position_quantity, 0)
        self.assertTrue(any("EXCESSIVE_RISK_SCORE" in r for r in plan.veto_reasons))

    # 17. Existing committee veto
    def test_17_existing_committee_veto(self):
        vetoed_dec = deepcopy(self.decision)
        vetoed_dec.risk_veto_applied = True
        vetoed_dec.risk_veto_reason = "Critical valuation conflict"
        engine = RiskEngine()
        plan = engine.evaluate_and_size(vetoed_dec, self.ctx)
        self.assertTrue(plan.veto_applied)
        self.assertEqual(plan.position_quantity, 0)
        self.assertTrue(any("UPSTREAM_RISK_VETO" in r for r in plan.veto_reasons))

    # 18. Insufficient evidence
    def test_18_insufficient_evidence(self):
        ind_dec = deepcopy(self.decision)
        ind_dec.recommendation = CommitteeRecommendation.INDETERMINATE
        engine = RiskEngine()
        plan = engine.evaluate_and_size(ind_dec, self.ctx)
        self.assertTrue(plan.veto_applied)
        self.assertEqual(plan.position_quantity, 0)

    # 19. Missing fundamental data
    def test_19_missing_fundamental_data(self):
        partial_dec = deepcopy(self.decision)
        partial_dec.data_quality = DataQualityStatus.PARTIAL
        cfg = RiskConfiguration(account_capital=100000.0, max_position_pct=0.50)
        engine = RiskEngine(config=cfg)
        plan_avail = engine.evaluate_and_size(self.decision, self.ctx, explicit_stop_loss=95.0)
        plan_partial = engine.evaluate_and_size(partial_dec, self.ctx, explicit_stop_loss=95.0)
        self.assertLess(plan_partial.position_quantity, plan_avail.position_quantity)

    # 20. Missing quant data
    def test_20_missing_quant_data(self):
        deg_dec = deepcopy(self.decision)
        deg_dec.data_quality = DataQualityStatus.DEGRADED
        cfg = RiskConfiguration(account_capital=100000.0, max_position_pct=0.50)
        engine = RiskEngine(config=cfg)
        plan_deg = engine.evaluate_and_size(deg_dec, self.ctx, explicit_stop_loss=95.0)
        self.assertEqual(plan_deg.data_quality, DataQualityStatus.DEGRADED)

    # 21. Degraded specialist
    def test_21_degraded_specialist(self):
        deg_dec = deepcopy(self.decision)
        deg_dec.data_quality = DataQualityStatus.DEGRADED
        cfg = RiskConfiguration(account_capital=100000.0, max_position_pct=0.50)
        engine = RiskEngine(config=cfg)
        plan_norm = engine.evaluate_and_size(self.decision, self.ctx, explicit_stop_loss=95.0)
        plan_deg = engine.evaluate_and_size(deg_dec, self.ctx, explicit_stop_loss=95.0)
        # Sized down by 50%
        self.assertLess(plan_deg.position_quantity, plan_norm.position_quantity)

    # 22. Failed specialist
    def test_22_failed_specialist(self):
        fail_dec = deepcopy(self.decision)
        fail_dec.failed_specialists = ["TechnicalSpecialist"]
        engine = RiskEngine()
        plan = engine.evaluate_and_size(fail_dec, self.ctx)
        self.assertTrue(plan.veto_applied)
        self.assertEqual(plan.position_quantity, 0)

    # 23. Stale data
    def test_23_stale_data(self):
        stale_dec = deepcopy(self.decision)
        stale_dec.data_quality = DataQualityStatus.STALE
        engine = RiskEngine()
        plan = engine.evaluate_and_size(stale_dec, self.ctx)
        self.assertTrue(plan.veto_applied)
        self.assertEqual(plan.position_quantity, 0)
        self.assertTrue(any("DATA_QUALITY_STALE" in r for r in plan.veto_reasons))

    # 24. Risk/reward calculation
    def test_24_risk_reward_calculation(self):
        engine = RiskEngine()
        # Entry 100, Stop 95 (risk=5), Take-Profit 110 (reward=10) => R:R = 2.0
        plan = engine.evaluate_and_size(self.decision, self.ctx, explicit_stop_loss=95.0, explicit_take_profit=110.0)
        self.assertIsNotNone(plan.risk_reward_ratio)
        self.assertAlmostEqual(plan.risk_reward_ratio, 2.0)

    # 25. Invalid risk/reward
    def test_25_invalid_risk_reward(self):
        # Entry 100, Stop 95 (risk=5), Take-Profit 102 (reward=2) => R:R = 0.4 < 1.5 min
        engine = RiskEngine()
        plan = engine.evaluate_and_size(self.decision, self.ctx, explicit_stop_loss=95.0, explicit_take_profit=102.0)
        self.assertTrue(plan.veto_applied)
        self.assertEqual(plan.position_quantity, 0)
        self.assertTrue(any("INSUFFICIENT_RISK_REWARD" in r for r in plan.veto_reasons))

    # 26. Short position risk/reward
    def test_26_short_position_risk_reward(self):
        # Short: Entry 100, Stop 105 (risk=5), Take-Profit 85 (reward=15) => R:R = 3.0
        cfg = RiskConfiguration(allow_short=True)
        engine = RiskEngine(config=cfg)
        short_dec = deepcopy(self.decision)
        short_dec.recommendation = CommitteeRecommendation.SELL
        plan = engine.evaluate_and_size(short_dec, self.ctx, explicit_stop_loss=105.0, explicit_take_profit=85.0)
        self.assertIsNotNone(plan.risk_reward_ratio)
        self.assertAlmostEqual(plan.risk_reward_ratio, 3.0)

    # 27. NaN handling
    def test_27_nan_handling(self):
        nan_ctx = self.ctx.model_copy(update={"current_price": float("nan")})
        engine = RiskEngine()
        plan = engine.evaluate_and_size(self.decision, nan_ctx)
        self.assertTrue(plan.veto_applied)
        self.assertEqual(plan.position_quantity, 0)

    # 28. Infinity handling
    def test_28_infinity_handling(self):
        inf_ctx = self.ctx.model_copy(update={"current_price": float("inf")})
        engine = RiskEngine()
        plan = engine.evaluate_and_size(self.decision, inf_ctx)
        self.assertTrue(plan.veto_applied)
        self.assertEqual(plan.position_quantity, 0)

    # 29. Zero quantity
    def test_29_zero_quantity(self):
        # Entry price is $50,000, risk budget is $1,000, risk/share = $5,000 => 0 shares
        cfg = RiskConfiguration(account_capital=100000.0, max_trade_risk_pct=0.01)
        engine = RiskEngine(config=cfg)
        expensive_ctx = self.ctx.model_copy(update={"current_price": 50000.0})
        plan = engine.evaluate_and_size(self.decision, expensive_ctx, explicit_stop_loss=45000.0)
        self.assertTrue(plan.veto_applied)
        self.assertEqual(plan.position_quantity, 0)
        self.assertTrue(any("POSITION_SIZE_ZERO" in r for r in plan.veto_reasons))

    # 30. Provenance preservation
    def test_30_provenance_preservation(self):
        engine = RiskEngine()
        plan = engine.evaluate_and_size(self.decision, self.ctx)
        self.assertGreater(len(plan.provenance), 0)
        self.assertEqual(plan.provenance[0]["source"], "test_setup")

    # 31. context_id propagation
    def test_31_context_id_propagation(self):
        engine = RiskEngine()
        plan = engine.evaluate_and_size(self.decision, self.ctx)
        self.assertEqual(plan.context_id, "ctx-risk-p64-001")
        self.assertEqual(plan.symbol, "INFY.NS")
        self.assertEqual(plan.run_id, "run-risk-001")

    # 32. decision_id propagation
    def test_32_decision_id_propagation(self):
        engine = RiskEngine()
        plan = engine.evaluate_and_size(self.decision, self.ctx)
        self.assertEqual(plan.decision_id, "dec-risk-p64-001")

    # 33. Deterministic repeatability
    def test_33_deterministic_repeatability(self):
        engine = RiskEngine()
        p1 = engine.evaluate_and_size(self.decision, self.ctx)
        p2 = engine.evaluate_and_size(self.decision, self.ctx)
        self.assertEqual(p1.position_quantity, p2.position_quantity)
        self.assertEqual(p1.position_notional, p2.position_notional)
        self.assertEqual(p1.risk_budget, p2.risk_budget)
        self.assertEqual(p1.stop_loss_price, p2.stop_loss_price)
        self.assertEqual(p1.veto_applied, p2.veto_applied)

    # 34. MarketContext immutability
    def test_34_market_context_immutability(self):
        before = deepcopy(self.ctx.model_dump())
        engine = RiskEngine()
        _ = engine.evaluate_and_size(self.decision, self.ctx)
        after = deepcopy(self.ctx.model_dump())
        self.assertEqual(before, after)

    # 35. Backward compatibility
    async def test_35_backward_compatibility(self):
        from backend.agents.risk_agent import RiskAssessment as LegacyRiskAssessment
        legacy_obj = LegacyRiskAssessment(
            symbol="INFY.NS",
            risk_level="LOW",
            max_position_size_pct=10.0,
            stop_loss_pct=2.5,
            risk_summary="Safe",
        )
        self.assertEqual(legacy_obj.symbol, "INFY.NS")
        self.assertEqual(legacy_obj.max_position_size_pct, 10.0)

    # 36. Complete end-to-end integration test
    async def test_36_complete_end_to_end(self):
        """
        Integration test verifying:
        MarketContext
        -> Specialists (Technical, Momentum, Quant, Fundamental)
        -> EvidenceAggregator -> EvidenceSummary
        -> DebateEngine -> DebateResult
        -> InvestmentCommittee -> CommitteeDecision
        -> RiskEngine -> PositionSizingPlan
        All sharing the exact same context_id.
        """
        e2e_ctx = MarketContext(
            context_id="ctx-e2e-risk-full-001",
            symbol="TCS.NS",
            data_timestamp=self.now,
            current_price=3500.0,
            provider="mock-e2e",
            ohlcv_historical=[
                {"timestamp": "2024-01-01T00:00:00+00:00", "open": 3400.0, "high": 3450.0, "low": 3390.0, "close": 3420.0, "volume": 100000},
                {"timestamp": "2024-01-02T00:00:00+00:00", "open": 3420.0, "high": 3480.0, "low": 3410.0, "close": 3460.0, "volume": 120000},
                {"timestamp": "2024-01-03T00:00:00+00:00", "open": 3460.0, "high": 3500.0, "low": 3450.0, "close": 3480.0, "volume": 110000},
                {"timestamp": "2024-01-04T00:00:00+00:00", "open": 3480.0, "high": 3520.0, "low": 3470.0, "close": 3500.0, "volume": 130000},
                {"timestamp": "2024-01-05T00:00:00+00:00", "open": 3500.0, "high": 3550.0, "low": 3490.0, "close": 3520.0, "volume": 140000},
            ],
            technical_indicators={"rsi": 62.0, "ema20": 3450.0, "ema50": 3400.0, "20_day_high": 3700.0, "20_day_low": 3350.0},
            fundamental_data={
                "period": "FY2024",
                "report_date": "2024-01-15",
                "revenue": 10000.0,
                "prior_revenue": 8500.0,
                "operating_profit": 2500.0,
                "net_income": 1900.0,
                "eps": 25.0,
                "prior_eps": 20.0,
                "total_debt": 500.0,
                "total_equity": 8000.0,
                "operating_cash_flow": 2200.0,
                "capex": 500.0,
                "current_assets": 5000.0,
                "current_liabilities": 1500.0,
                "cash": 2000.0,
                "gross_profit": 4500.0,
            },
        )

        agent_input = AgentInput(
            symbol="TCS.NS",
            market_context=e2e_ctx,
            historical_ohlcv=e2e_ctx.ohlcv_historical,
            indicators=e2e_ctx.technical_indicators,
            additional_data={"pe_ratio": 24.5, "net_margin": 19.2, "volatility_annualized": 18.5},
        )

        # 1. Specialists
        tech_spec = TechnicalSpecialist(llm_client=MockLLMClient(fixed_response=_TechnicalLLMResponse(
            trend=TrendDirection.BULLISH,
            setup=SetupType.BREAKOUT,
            technical_score=8.0,
            confirmation=True,
            conclusion="Bullish breakout above key moving averages.",
            invalidation_conditions=["Break below EMA20"],
            risks=["Overbought pullbacks"],
            assumptions=["Trend continues"],
            confidence=0.85,
        )))
        mom_spec = MomentumSpecialist(llm_client=MockLLMClient(fixed_response=_MomentumLLMResponse(
            momentum_direction=MomentumDirection.BULLISH,
            momentum_strength=MomentumStrength.STRONG,
            confirmation=True,
            conclusion="Accelerating momentum confirmed.",
            invalidation_conditions=["Momentum stall"],
            risks=["Exhaustion"],
            assumptions=["Volume sustained"],
            confidence=0.85,
        )))
        quant_spec = QuantSpecialist(llm_client=MockLLMClient(fixed_response=_QuantLLMResponse(
            statistical_regime=QuantStatisticalRegime.NORMAL_VOLATILITY,
            risk_characterization=QuantRiskCharacterization.SUBDUED,
            anomaly_detected=False,
            statistical_strength=0.75,
            conclusion="Normal volatility regime with positive drift.",
            invalidation_conditions=["Volatility surge"],
            risks=["Fat tail"],
            assumptions=["Variance stability"],
            confidence=0.80,
        )))
        fund_spec = FundamentalSpecialist(llm_client=MockLLMClient(fixed_response=_FundamentalLLMResponse(
            fundamental_quality=FundamentalQuality.STRONG,
            growth_assessment=GrowthAssessment.HIGH_GROWTH,
            profitability_assessment=ProfitabilityAssessment.HIGHLY_PROFITABLE,
            balance_sheet_assessment=BalanceSheetAssessment.HEALTHY,
            financial_strength=0.85,
            conclusion="High margins and low leverage provide balance sheet strength.",
            invalidation_conditions=["Margin drop"],
            risks=["Pricing pressure"],
            assumptions=["Enterprise demand holds"],
            confidence=0.85,
        )))

        outputs = [
            await tech_spec.execute(agent_input),
            await mom_spec.execute(agent_input),
            await quant_spec.execute(agent_input),
            await fund_spec.execute(agent_input),
        ]
        records = [
            AgentExecutionRecord(
                agent_name=out.agent_name,
                agent_version=out.version,
                context_id="ctx-e2e-risk-full-001",
                started_at=self.now,
                completed_at=self.now,
                status=out.status,
                duration_seconds=0.01,
                output=out,
            )
            for out in outputs
        ]
        run_result = SpecialistRunResult(
            run_id="run-e2e-risk-001",
            context_id="ctx-e2e-risk-full-001",
            symbol="TCS.NS",
            started_at=self.now,
            completed_at=self.now,
            duration_seconds=0.04,
            total_agents=4,
            successful_agents=4,
            failed_agents=0,
            timed_out_agents=0,
            degraded_agents=0,
            records=records,
            outputs=outputs,
        )

        # 2. Evidence Layer
        aggregator = EvidenceAggregator()
        evidence_summary = aggregator.aggregate_evidence(run_result, market_context=e2e_ctx)

        # 3. Debate Engine
        debate_engine = DebateEngine(llm_client=None)
        debate_result = await debate_engine.run_debate(evidence_summary, market_context=e2e_ctx)

        # 4. Investment Committee
        committee = InvestmentCommittee(llm_client=None)
        decision = await committee.synthesize_decision(evidence_summary, debate_result, market_context=e2e_ctx)
        self.assertEqual(decision.context_id, "ctx-e2e-risk-full-001")

        # 5. Risk Engine -> PositionSizingPlan
        risk_engine = RiskEngine(config=RiskConfiguration(account_capital=200000.0, max_position_pct=0.25))

        # Test A: Unmodified pipeline output (WATCH) -> safe flat position with veto
        watch_plan = await risk_engine.evaluate_and_size(decision, market_context=e2e_ctx)
        self.assertIsInstance(watch_plan, PositionSizingPlan)
        self.assertEqual(watch_plan.context_id, "ctx-e2e-risk-full-001")
        self.assertEqual(watch_plan.symbol, "TCS.NS")
        self.assertEqual(watch_plan.direction, PositionDirection.FLAT)
        self.assertTrue(watch_plan.veto_applied)
        self.assertEqual(watch_plan.position_quantity, 0)

        # Test B: Approved BUY recommendation -> active long position sized with constraints
        decision_approved = decision.model_copy(update={
            "recommendation": CommitteeRecommendation.BUY,
            "conviction_score": 0.85,
            "risk_score": 0.20,
            "risk_veto_applied": False,
        })
        plan = await risk_engine.evaluate_and_size(decision_approved, market_context=e2e_ctx)

        # 6. Verify Complete End-to-End Pipeline
        self.assertIsInstance(plan, PositionSizingPlan)
        self.assertEqual(plan.context_id, "ctx-e2e-risk-full-001")
        self.assertEqual(plan.symbol, "TCS.NS")
        self.assertEqual(plan.decision_id, decision.decision_id)
        self.assertEqual(plan.direction, PositionDirection.LONG)
        self.assertFalse(plan.veto_applied)
        self.assertGreater(plan.position_quantity, 0)
        self.assertEqual(plan.entry_price, 3500.0)
        self.assertLess(plan.stop_loss_price, 3500.0)
        self.assertGreater(plan.position_notional, 0.0)
        self.assertLessEqual(plan.position_notional, 200000.0 * 0.25)
        self.assertGreater(len(plan.constraints_applied), 0)


if __name__ == "__main__":
    unittest.main()
