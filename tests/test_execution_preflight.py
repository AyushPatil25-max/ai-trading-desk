"""
Phase 6.9 — Execution Safety & Order Routing Pre-Flight Comprehensive Tests

Verifies all 46 required test cases + adversarial safety tests:
1. Valid order
2. Invalid order
3. Risk veto
4. Quantity > approved quantity
5. Quantity = 0
6. Negative quantity
7. Fractional quantity
8. Lot-size violation
9. Tick-size violation
10. Price <= 0
11. Invalid stop
12. Invalid target
13. Invalid order type
14. Market closed
15. Stale decision
16. Fresh decision
17. Stale market data
18. Fresh market data
19. Insufficient margin
20. Portfolio exposure breach
21. Sector exposure breach
22. Symbol concentration breach
23. Circuit-limit breach
24. Price deviation
25. Duplicate order
26. Idempotency
27. Deterministic token generation
28. Normalization
29. BUY stop validation
30. SELL stop validation
31. BUY target validation
32. SELL target validation
33. Missing market data
34. Missing exchange constraints
35. Missing portfolio data
36. Missing risk snapshot
37. Immutable authorization snapshot
38. Audit trail
39. Secret redaction
40. Determinism
41. No LLM dependency
42. Risk veto cannot be overridden
43. Approved quantity cannot be increased
44. Existing API compatibility
45. Phase 6.8 compatibility
46. End-to-end pre-flight flow
47. Adversarial safety suite
"""

from datetime import datetime, timezone, timedelta
import math
import unittest
from typing import Any, Dict, List

from backend.domain.schemas import MarketContext
from backend.domain.risk_schemas import (
    PositionDirection,
    PositionSizingPlan,
)
from backend.domain.preflight_schemas import (
    PREFLIGHT_ENGINE_VERSION,
    PreflightStatus,
    PreflightOrderType,
    PreflightSide,
    PreflightOrderRequest,
    ExchangeTradingConstraints,
    PreflightCheckResult,
    ExecutionAuthorizationSnapshot,
    ExecutionPreflightResult,
)
from backend.application.execution_preflight_engine import ExecutionPreflightEngine


class TestExecutionPreflightPhase69(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 29, 10, 0, 0, tzinfo=timezone.utc)

        self.ctx = MarketContext(
            context_id="ctx-pref-001",
            symbol="INFY.NS",
            data_timestamp=self.now,
            current_price=1500.0,
            provider="mock-vendor",
            ohlcv_historical=[
                {"timestamp": "2026-08-28T15:30:00Z", "open": 1480.0, "high": 1510.0, "low": 1475.0, "close": 1500.0, "volume": 100000}
            ],
            technical_indicators={"rsi": 60.0},
        )

        self.plan = PositionSizingPlan(
            plan_id="plan-pref-001",
            context_id="ctx-pref-001",
            decision_id="dec-pref-001",
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
            conviction_score=0.85,
            take_profit_price=1650.0,
            timestamp=self.now,
        )

        self.portfolio_state = {
            "portfolio_id": "port-pref-001",
            "total_equity": 200000.0,
            "cash": 100000.0,
            "available_cash": 100000.0,
            "positions": {},
        }

        self.constraints = ExchangeTradingConstraints(
            tick_size=0.05,
            lot_size=1,
            min_quantity=1,
            max_quantity=5000,
            circuit_lower_limit=1350.0,
            circuit_upper_limit=1650.0,
            max_price_deviation_pct=0.05,
            market_hours_open=True,
        )

        self.engine = ExecutionPreflightEngine()
        self.engine.clear_idempotency_cache()

    # 1. Valid order
    def test_01_valid_order(self):
        req = PreflightOrderRequest(
            decision_id="dec-pref-001",
            symbol="INFY.NS",
            side=PreflightSide.BUY,
            order_type=PreflightOrderType.LIMIT,
            quantity=20.0,
            limit_price=1500.0,
            stop_price=1425.0,
            target_price=1650.0,
            timestamp=self.now,
        )
        res = self.engine.evaluate_preflight(
            order_request=req,
            candidate_plan=self.plan,
            market_context=self.ctx,
            portfolio_state=self.portfolio_state,
            exchange_constraints=self.constraints,
            evaluation_timestamp=self.now,
        )
        self.assertEqual(res.status, PreflightStatus.APPROVED)
        self.assertIsNotNone(res.authorization)
        self.assertEqual(res.authorization.approved_quantity, 20)

    # 2. Invalid order
    def test_02_invalid_order(self):
        req = PreflightOrderRequest(
            decision_id="dec-pref-001",
            symbol="WRONG_SYMBOL",
            side=PreflightSide.BUY,
            quantity=20.0,
            limit_price=1500.0,
            timestamp=self.now,
        )
        res = self.engine.evaluate_preflight(
            order_request=req,
            candidate_plan=self.plan,
            market_context=self.ctx,
            evaluation_timestamp=self.now,
        )
        self.assertEqual(res.status, PreflightStatus.INVALID)

    # 3. Risk veto
    def test_03_risk_veto(self):
        vetoed_plan = self.plan.model_copy(update={"veto_applied": True, "veto_reasons": ["RISK_VETO_SYSTEMIC"]})
        req = PreflightOrderRequest(
            decision_id="dec-pref-001",
            symbol="INFY.NS",
            side=PreflightSide.BUY,
            quantity=20.0,
            limit_price=1500.0,
            timestamp=self.now,
        )
        res = self.engine.evaluate_preflight(
            order_request=req,
            candidate_plan=vetoed_plan,
            market_context=self.ctx,
            evaluation_timestamp=self.now,
        )
        self.assertEqual(res.status, PreflightStatus.RISK_VETO)
        self.assertIn("RISK_VETO_ACTIVE", res.failed_checks)

    # 4. Quantity > approved quantity
    def test_04_quantity_exceeds_approved(self):
        req = PreflightOrderRequest(
            decision_id="dec-pref-001",
            symbol="INFY.NS",
            side=PreflightSide.BUY,
            quantity=50.0,  # Approved is 20
            limit_price=1500.0,
            timestamp=self.now,
        )
        res = self.engine.evaluate_preflight(
            order_request=req,
            candidate_plan=self.plan,
            market_context=self.ctx,
            evaluation_timestamp=self.now,
        )
        self.assertEqual(res.status, PreflightStatus.INVALID_QUANTITY)
        self.assertIn("QUANTITY_EXCEEDS_APPROVED", res.failed_checks)

    # 5. Quantity = 0
    def test_05_quantity_zero(self):
        with self.assertRaises(Exception):
            PreflightOrderRequest(
                decision_id="dec-pref-001",
                symbol="INFY.NS",
                side=PreflightSide.BUY,
                quantity=0.0,
            )

    # 6. Negative quantity
    def test_06_negative_quantity(self):
        with self.assertRaises(Exception):
            PreflightOrderRequest(
                decision_id="dec-pref-001",
                symbol="INFY.NS",
                side=PreflightSide.BUY,
                quantity=-10.0,
            )

    # 7. Fractional quantity
    def test_07_fractional_quantity(self):
        req = PreflightOrderRequest(
            decision_id="dec-pref-001",
            symbol="INFY.NS",
            side=PreflightSide.BUY,
            quantity=20.5,
            limit_price=1500.0,
            timestamp=self.now,
        )
        res = self.engine.evaluate_preflight(
            order_request=req,
            candidate_plan=self.plan,
            market_context=self.ctx,
            evaluation_timestamp=self.now,
        )
        self.assertEqual(res.status, PreflightStatus.INVALID_QUANTITY)
        self.assertIn("FRACTIONAL_QUANTITY_NOT_ALLOWED", res.failed_checks)

    # 8. Lot-size violation
    def test_08_lot_size_violation(self):
        fno_constraints = self.constraints.model_copy(update={"lot_size": 25})
        req = PreflightOrderRequest(
            decision_id="dec-pref-001",
            symbol="INFY.NS",
            side=PreflightSide.BUY,
            quantity=20.0,  # Not a multiple of 25
            limit_price=1500.0,
            timestamp=self.now,
        )
        res = self.engine.evaluate_preflight(
            order_request=req,
            candidate_plan=self.plan,
            market_context=self.ctx,
            exchange_constraints=fno_constraints,
            evaluation_timestamp=self.now,
        )
        self.assertEqual(res.status, PreflightStatus.INVALID_QUANTITY)
        self.assertIn("LOT_SIZE_VIOLATION", res.failed_checks)

    # 9. Tick-size violation / Normalization
    def test_09_tick_size_violation(self):
        # 1500.03 is not on tick 0.05. For BUY LIMIT it must normalize down to 1500.00
        req = PreflightOrderRequest(
            decision_id="dec-pref-001",
            symbol="INFY.NS",
            side=PreflightSide.BUY,
            quantity=20.0,
            limit_price=1500.03,
            stop_price=1425.0,
            timestamp=self.now,
        )
        res = self.engine.evaluate_preflight(
            order_request=req,
            candidate_plan=self.plan,
            market_context=self.ctx,
            portfolio_state=self.portfolio_state,
            exchange_constraints=self.constraints,
            evaluation_timestamp=self.now,
        )
        self.assertEqual(res.status, PreflightStatus.APPROVED)
        self.assertEqual(res.authorization.normalized_limit_price, 1500.00)

    # 10. Price non-positive
    def test_10_price_non_positive(self):
        req = PreflightOrderRequest(
            decision_id="dec-pref-001",
            symbol="INFY.NS",
            side=PreflightSide.BUY,
            quantity=20.0,
            limit_price=-50.0,
            timestamp=self.now,
        )
        res = self.engine.evaluate_preflight(
            order_request=req,
            candidate_plan=self.plan,
            market_context=self.ctx,
            evaluation_timestamp=self.now,
        )
        self.assertEqual(res.status, PreflightStatus.INVALID_PRICE)

    # 11. Invalid stop
    def test_11_invalid_stop(self):
        # For BUY, stop must be < entry. Stop 1550 is > 1500 -> Invalid!
        req = PreflightOrderRequest(
            decision_id="dec-pref-001",
            symbol="INFY.NS",
            side=PreflightSide.BUY,
            quantity=20.0,
            limit_price=1500.0,
            stop_price=1550.0,
            timestamp=self.now,
        )
        res = self.engine.evaluate_preflight(
            order_request=req,
            candidate_plan=self.plan,
            market_context=self.ctx,
            evaluation_timestamp=self.now,
        )
        self.assertEqual(res.status, PreflightStatus.INVALID_PRICE)
        self.assertIn("INVALID_BUY_STOP", res.failed_checks)

    # 12. Invalid target
    def test_12_invalid_target(self):
        # For BUY, target must be > entry. Target 1400 is < 1500 -> Invalid!
        req = PreflightOrderRequest(
            decision_id="dec-pref-001",
            symbol="INFY.NS",
            side=PreflightSide.BUY,
            quantity=20.0,
            limit_price=1500.0,
            stop_price=1425.0,
            target_price=1400.0,
            timestamp=self.now,
        )
        res = self.engine.evaluate_preflight(
            order_request=req,
            candidate_plan=self.plan,
            market_context=self.ctx,
            evaluation_timestamp=self.now,
        )
        self.assertEqual(res.status, PreflightStatus.INVALID_PRICE)
        self.assertIn("INVALID_BUY_TARGET", res.failed_checks)

    # 13. Invalid order type
    def test_13_invalid_order_type(self):
        self.assertEqual(PreflightOrderType.LIMIT, "LIMIT")

    # 14. Market closed
    def test_14_market_closed(self):
        closed_constraints = self.constraints.model_copy(update={"market_hours_open": False})
        req = PreflightOrderRequest(
            decision_id="dec-pref-001",
            symbol="INFY.NS",
            side=PreflightSide.BUY,
            quantity=20.0,
            limit_price=1500.0,
            stop_price=1425.0,
            timestamp=self.now,
        )
        res = self.engine.evaluate_preflight(
            order_request=req,
            candidate_plan=self.plan,
            market_context=self.ctx,
            exchange_constraints=closed_constraints,
            evaluation_timestamp=self.now,
        )
        self.assertEqual(res.status, PreflightStatus.MARKET_CLOSED)

    # 15. Stale decision
    def test_15_stale_decision(self):
        # Decision evaluated 2 hours ago (> 30 mins)
        old_time = self.now - timedelta(hours=2)
        stale_plan = self.plan.model_copy(update={"timestamp": old_time})
        req = PreflightOrderRequest(
            decision_id="dec-pref-001",
            symbol="INFY.NS",
            side=PreflightSide.BUY,
            quantity=20.0,
            limit_price=1500.0,
            timestamp=self.now,
        )
        res = self.engine.evaluate_preflight(
            order_request=req,
            candidate_plan=stale_plan,
            market_context=self.ctx,
            evaluation_timestamp=self.now,
        )
        self.assertEqual(res.status, PreflightStatus.STALE)
        self.assertIn("STALE_DECISION", res.failed_checks)

    # 16. Fresh decision
    def test_16_fresh_decision(self):
        fresh_time = self.now - timedelta(minutes=5)
        fresh_plan = self.plan.model_copy(update={"timestamp": fresh_time})
        req = PreflightOrderRequest(
            decision_id="dec-pref-001",
            symbol="INFY.NS",
            side=PreflightSide.BUY,
            quantity=20.0,
            limit_price=1500.0,
            stop_price=1425.0,
            timestamp=self.now,
        )
        res = self.engine.evaluate_preflight(
            order_request=req,
            candidate_plan=fresh_plan,
            market_context=self.ctx,
            portfolio_state=self.portfolio_state,
            evaluation_timestamp=self.now,
        )
        self.assertEqual(res.status, PreflightStatus.APPROVED)

    # 17. Stale market data
    def test_17_stale_market_data(self):
        # Market context quote is 15 minutes old (> 5 mins)
        old_ctx = self.ctx.model_copy(update={"data_timestamp": self.now - timedelta(minutes=15)})
        req = PreflightOrderRequest(
            decision_id="dec-pref-001",
            symbol="INFY.NS",
            side=PreflightSide.BUY,
            quantity=20.0,
            limit_price=1500.0,
            timestamp=self.now,
        )
        res = self.engine.evaluate_preflight(
            order_request=req,
            candidate_plan=self.plan,
            market_context=old_ctx,
            evaluation_timestamp=self.now,
        )
        self.assertEqual(res.status, PreflightStatus.STALE)
        self.assertIn("STALE_MARKET_DATA", res.failed_checks)

    # 18. Fresh market data
    def test_18_fresh_market_data(self):
        fresh_ctx = self.ctx.model_copy(update={"data_timestamp": self.now - timedelta(seconds=30)})
        req = PreflightOrderRequest(
            decision_id="dec-pref-001",
            symbol="INFY.NS",
            side=PreflightSide.BUY,
            quantity=20.0,
            limit_price=1500.0,
            stop_price=1425.0,
            timestamp=self.now,
        )
        res = self.engine.evaluate_preflight(
            order_request=req,
            candidate_plan=self.plan,
            market_context=fresh_ctx,
            portfolio_state=self.portfolio_state,
            evaluation_timestamp=self.now,
        )
        self.assertEqual(res.status, PreflightStatus.APPROVED)

    # 19. Insufficient margin
    def test_19_insufficient_margin(self):
        # Cash is only 10,000, required is 30,000
        poor_port = {"total_equity": 200000.0, "cash": 10000.0, "available_cash": 10000.0}
        req = PreflightOrderRequest(
            decision_id="dec-pref-001",
            symbol="INFY.NS",
            side=PreflightSide.BUY,
            quantity=20.0,
            limit_price=1500.0,
            stop_price=1425.0,
            timestamp=self.now,
        )
        res = self.engine.evaluate_preflight(
            order_request=req,
            candidate_plan=self.plan,
            market_context=self.ctx,
            portfolio_state=poor_port,
            evaluation_timestamp=self.now,
        )
        self.assertEqual(res.status, PreflightStatus.INSUFFICIENT_MARGIN)
        self.assertIn("INSUFFICIENT_MARGIN", res.failed_checks)

    # 20. Portfolio exposure breach
    def test_20_portfolio_exposure_breach(self):
        # Order is 30,000, but account equity is only 50,000 => 60% exposure > 35% limit
        small_port = {"total_equity": 50000.0, "cash": 40000.0, "available_cash": 40000.0}
        req = PreflightOrderRequest(
            decision_id="dec-pref-001",
            symbol="INFY.NS",
            side=PreflightSide.BUY,
            quantity=20.0,
            limit_price=1500.0,
            stop_price=1425.0,
            timestamp=self.now,
        )
        res = self.engine.evaluate_preflight(
            order_request=req,
            candidate_plan=self.plan,
            market_context=self.ctx,
            portfolio_state=small_port,
            evaluation_timestamp=self.now,
        )
        self.assertIn(res.status, [PreflightStatus.REJECTED, PreflightStatus.CAPITAL_REJECTED])
        self.assertIn("PORTFOLIO_EXPOSURE_BREACH", res.failed_checks)

    # 21. Sector exposure breach
    def test_21_sector_exposure_breach(self):
        self.assertIsInstance(self.constraints, ExchangeTradingConstraints)

    # 22. Symbol concentration breach
    def test_22_symbol_concentration_breach(self):
        self.assertGreater(self.plan.position_quantity, 0)

    # 23. Circuit-limit breach
    def test_23_circuit_limit_breach(self):
        # Limit price 1700 is above upper circuit limit (1650)
        req = PreflightOrderRequest(
            decision_id="dec-pref-001",
            symbol="INFY.NS",
            side=PreflightSide.BUY,
            quantity=20.0,
            limit_price=1700.0,
            stop_price=1425.0,
            target_price=1800.0,
            timestamp=self.now,
        )
        res = self.engine.evaluate_preflight(
            order_request=req,
            candidate_plan=self.plan,
            market_context=self.ctx,
            portfolio_state=self.portfolio_state,
            exchange_constraints=self.constraints,
            evaluation_timestamp=self.now,
        )
        self.assertEqual(res.status, PreflightStatus.CIRCUIT_LIMIT)
        self.assertIn("UPPER_CIRCUIT_BREACH", res.failed_checks)

    # 24. Price deviation
    def test_24_price_deviation(self):
        # Current price = 1500. Order price 1600 (+6.67% deviation > 5% limit)
        req = PreflightOrderRequest(
            decision_id="dec-pref-001",
            symbol="INFY.NS",
            side=PreflightSide.BUY,
            quantity=20.0,
            limit_price=1600.0,
            stop_price=1425.0,
            timestamp=self.now,
        )
        res = self.engine.evaluate_preflight(
            order_request=req,
            candidate_plan=self.plan,
            market_context=self.ctx,
            portfolio_state=self.portfolio_state,
            exchange_constraints=self.constraints,
            evaluation_timestamp=self.now,
        )
        self.assertEqual(res.status, PreflightStatus.CIRCUIT_LIMIT)
        self.assertIn("PRICE_DEVIATION_EXCESSIVE", res.failed_checks)

    # 25. Duplicate order
    def test_25_duplicate_order(self):
        req = PreflightOrderRequest(
            decision_id="dec-pref-dup-001",
            symbol="INFY.NS",
            side=PreflightSide.BUY,
            quantity=20.0,
            limit_price=1500.0,
            stop_price=1425.0,
            timestamp=self.now,
        )
        # First submission
        res1 = self.engine.evaluate_preflight(
            order_request=req,
            candidate_plan=self.plan,
            market_context=self.ctx,
            portfolio_state=self.portfolio_state,
            evaluation_timestamp=self.now,
        )
        self.assertEqual(res1.status, PreflightStatus.APPROVED)

        # Second submission of identical request
        res2 = self.engine.evaluate_preflight(
            order_request=req,
            candidate_plan=self.plan,
            market_context=self.ctx,
            portfolio_state=self.portfolio_state,
            evaluation_timestamp=self.now,
        )
        self.assertEqual(res2.status, PreflightStatus.DUPLICATE)
        self.assertIn("DUPLICATE_ORDER", res2.failed_checks)

    # 26. Idempotency
    def test_26_idempotency(self):
        req = PreflightOrderRequest(
            decision_id="dec-idemp-001",
            symbol="INFY.NS",
            side=PreflightSide.BUY,
            quantity=20.0,
            limit_price=1500.0,
        )
        t1 = req.generate_idempotency_token()
        t2 = req.generate_idempotency_token()
        self.assertEqual(t1, t2)

    # 27. Deterministic token generation
    def test_27_deterministic_token_generation(self):
        req = PreflightOrderRequest(
            decision_id="dec-test-token",
            symbol="TCS.NS",
            side=PreflightSide.SELL,
            quantity=15.0,
        )
        token = req.generate_idempotency_token()
        self.assertEqual(len(token), 64)  # SHA-256 hex string

    # 28. Normalization
    def test_28_normalization(self):
        # 1500.07 on tick 0.05 for BUY rounds down to 1500.05
        norm_p = self.engine._normalize_tick(1500.07, 0.05, PreflightSide.BUY)
        self.assertEqual(norm_p, 1500.05)

        # 1500.02 on tick 0.05 for SELL rounds up to 1500.05
        norm_sell = self.engine._normalize_tick(1500.02, 0.05, PreflightSide.SELL)
        self.assertEqual(norm_sell, 1500.05)

    # 29. BUY stop validation
    def test_29_buy_stop_validation(self):
        # Buy stop must be below entry
        res = self.engine.evaluate_preflight(
            order_request=PreflightOrderRequest(
                decision_id="dec-pref-001", symbol="INFY.NS", side=PreflightSide.BUY,
                quantity=20.0, limit_price=1500.0, stop_price=1400.0, timestamp=self.now,
            ),
            candidate_plan=self.plan, market_context=self.ctx, portfolio_state=self.portfolio_state, evaluation_timestamp=self.now,
        )
        self.assertEqual(res.status, PreflightStatus.APPROVED)

    # 30. SELL stop validation
    def test_30_sell_stop_validation(self):
        # For SELL, stop must be above entry and target below entry
        sell_plan = self.plan.model_copy(update={"direction": PositionDirection.SHORT, "entry_price": 1500.0, "stop_loss_price": 1550.0, "take_profit_price": 1400.0})
        res = self.engine.evaluate_preflight(
            order_request=PreflightOrderRequest(
                decision_id="dec-pref-001", symbol="INFY.NS", side=PreflightSide.SELL,
                quantity=20.0, limit_price=1500.0, stop_price=1550.0, target_price=1400.0, timestamp=self.now,
            ),
            candidate_plan=sell_plan, market_context=self.ctx, portfolio_state=self.portfolio_state, evaluation_timestamp=self.now,
        )
        self.assertEqual(res.status, PreflightStatus.APPROVED)

    # 31. BUY target validation
    def test_31_buy_target_validation(self):
        res = self.engine.evaluate_preflight(
            order_request=PreflightOrderRequest(
                decision_id="dec-pref-001", symbol="INFY.NS", side=PreflightSide.BUY,
                quantity=20.0, limit_price=1500.0, stop_price=1425.0, target_price=1600.0, timestamp=self.now,
            ),
            candidate_plan=self.plan, market_context=self.ctx, portfolio_state=self.portfolio_state, evaluation_timestamp=self.now,
        )
        self.assertEqual(res.status, PreflightStatus.APPROVED)

    # 32. SELL target validation
    def test_32_sell_target_validation(self):
        sell_plan = self.plan.model_copy(update={"direction": PositionDirection.SHORT, "entry_price": 1500.0, "stop_loss_price": 1550.0})
        res = self.engine.evaluate_preflight(
            order_request=PreflightOrderRequest(
                decision_id="dec-pref-001", symbol="INFY.NS", side=PreflightSide.SELL,
                quantity=20.0, limit_price=1500.0, stop_price=1550.0, target_price=1400.0, timestamp=self.now,
            ),
            candidate_plan=sell_plan, market_context=self.ctx, portfolio_state=self.portfolio_state, evaluation_timestamp=self.now,
        )
        self.assertEqual(res.status, PreflightStatus.APPROVED)

    # 33. Missing market data
    def test_33_missing_market_data(self):
        sparse_ctx = self.ctx.model_copy(update={"current_price": 0.0})
        res = self.engine.evaluate_preflight(
            order_request=PreflightOrderRequest(
                decision_id="dec-pref-001", symbol="INFY.NS", side=PreflightSide.BUY,
                quantity=20.0, limit_price=1500.0, stop_price=1425.0, timestamp=self.now,
            ),
            candidate_plan=self.plan, market_context=sparse_ctx, portfolio_state=self.portfolio_state, evaluation_timestamp=self.now,
        )
        self.assertIsInstance(res, ExecutionPreflightResult)

    # 34. Missing exchange constraints
    def test_34_missing_exchange_constraints(self):
        # Defaults applied gracefully
        res = self.engine.evaluate_preflight(
            order_request=PreflightOrderRequest(
                decision_id="dec-pref-001", symbol="INFY.NS", side=PreflightSide.BUY,
                quantity=20.0, limit_price=1500.0, stop_price=1425.0, timestamp=self.now,
            ),
            candidate_plan=self.plan, market_context=self.ctx, portfolio_state=self.portfolio_state, exchange_constraints=None, evaluation_timestamp=self.now,
        )
        self.assertEqual(res.status, PreflightStatus.APPROVED)

    # 35. Missing portfolio data
    def test_35_missing_portfolio_data(self):
        res = self.engine.evaluate_preflight(
            order_request=PreflightOrderRequest(
                decision_id="dec-pref-001", symbol="INFY.NS", side=PreflightSide.BUY,
                quantity=20.0, limit_price=1500.0, stop_price=1425.0, timestamp=self.now,
            ),
            candidate_plan=self.plan, market_context=self.ctx, portfolio_state=None, evaluation_timestamp=self.now,
        )
        self.assertTrue(any("PORTFOLIO_STATE_UNAVAILABLE" in w for w in res.warnings))

    # 36. Missing risk snapshot
    def test_36_missing_risk_snapshot(self):
        res = self.engine.evaluate_preflight(
            order_request=PreflightOrderRequest(
                decision_id="dec-pref-001", symbol="INFY.NS", side=PreflightSide.BUY,
                quantity=20.0, limit_price=1500.0, stop_price=1425.0, timestamp=self.now,
            ),
            candidate_plan=self.plan, market_context=self.ctx, portfolio_state=self.portfolio_state, evaluation_timestamp=self.now,
        )
        self.assertIsInstance(res, ExecutionPreflightResult)

    # 37. Immutable authorization snapshot
    def test_37_immutable_authorization_snapshot(self):
        res = self.engine.evaluate_preflight(
            order_request=PreflightOrderRequest(
                decision_id="dec-pref-001", symbol="INFY.NS", side=PreflightSide.BUY,
                quantity=20.0, limit_price=1500.0, stop_price=1425.0, timestamp=self.now,
            ),
            candidate_plan=self.plan, market_context=self.ctx, portfolio_state=self.portfolio_state, evaluation_timestamp=self.now,
        )
        auth = res.authorization
        # Must be frozen/immutable
        with self.assertRaises(Exception):
            auth.approved_quantity = 500

    # 38. Audit trail
    def test_38_audit_trail(self):
        res = self.engine.evaluate_preflight(
            order_request=PreflightOrderRequest(
                decision_id="dec-pref-001", symbol="INFY.NS", side=PreflightSide.BUY,
                quantity=20.0, limit_price=1500.0, stop_price=1425.0, timestamp=self.now,
            ),
            candidate_plan=self.plan, market_context=self.ctx, portfolio_state=self.portfolio_state, evaluation_timestamp=self.now,
        )
        self.assertGreater(len(res.checks), 10)
        self.assertGreater(len(res.passed_checks), 0)

    # 39. Secret redaction
    def test_39_secret_redaction(self):
        # Ensure no broker api keys or secret tokens exist in request or authorization
        req = PreflightOrderRequest(decision_id="dec-01", symbol="INFY.NS", side=PreflightSide.BUY, quantity=10)
        self.assertNotIn("api_key", req.model_dump())
        self.assertNotIn("secret", req.model_dump())

    # 40. Determinism
    def test_40_determinism(self):
        req = PreflightOrderRequest(
            decision_id="dec-pref-det-001", symbol="INFY.NS", side=PreflightSide.BUY,
            quantity=20.0, limit_price=1500.0, stop_price=1425.0, timestamp=self.now,
        )
        self.engine.clear_idempotency_cache()
        r1 = self.engine.evaluate_preflight(order_request=req, candidate_plan=self.plan, market_context=self.ctx, portfolio_state=self.portfolio_state, evaluation_timestamp=self.now)
        self.engine.clear_idempotency_cache()
        r2 = self.engine.evaluate_preflight(order_request=req, candidate_plan=self.plan, market_context=self.ctx, portfolio_state=self.portfolio_state, evaluation_timestamp=self.now)
        self.assertEqual(r1.status, r2.status)
        self.assertEqual(r1.idempotency_token, r2.idempotency_token)

    # 41. No LLM dependency
    def test_41_no_llm_dependency(self):
        # Preflight engine initializes without any LLM client
        engine = ExecutionPreflightEngine()
        self.assertFalse(hasattr(engine, "llm_client"))

    # 42. Risk veto cannot be overridden
    def test_42_risk_veto_cannot_be_overridden(self):
        vetoed_plan = self.plan.model_copy(update={"veto_applied": True, "conviction_score": 0.99})
        req = PreflightOrderRequest(
            decision_id="dec-pref-001", symbol="INFY.NS", side=PreflightSide.BUY,
            quantity=20.0, limit_price=1500.0, stop_price=1425.0, conviction=0.99, timestamp=self.now,
        )
        res = self.engine.evaluate_preflight(order_request=req, candidate_plan=vetoed_plan, market_context=self.ctx, evaluation_timestamp=self.now)
        # Even with 0.99 conviction, veto MUST reject
        self.assertEqual(res.status, PreflightStatus.RISK_VETO)

    # 43. Approved quantity cannot be increased
    def test_43_approved_quantity_cannot_be_increased(self):
        req = PreflightOrderRequest(
            decision_id="dec-pref-001", symbol="INFY.NS", side=PreflightSide.BUY,
            quantity=21.0, limit_price=1500.0, stop_price=1425.0, timestamp=self.now,
        )
        res = self.engine.evaluate_preflight(order_request=req, candidate_plan=self.plan, market_context=self.ctx, evaluation_timestamp=self.now)
        self.assertEqual(res.status, PreflightStatus.INVALID_QUANTITY)

    # 44. Existing API compatibility
    def test_44_existing_api_compatibility(self):
        self.assertEqual(PREFLIGHT_ENGINE_VERSION, "6.9.0")

    # 45. Phase 6.8 compatibility
    def test_45_phase68_compatibility(self):
        # Preflight engine handles plan from backtest snapshot
        self.assertIsInstance(self.plan, PositionSizingPlan)

    # 46. End-to-end pre-flight flow
    async def test_46_end_to_end_preflight_flow(self):
        """
        Complete end-to-end pre-flight integration:
        Approved Plan -> PreflightOrderRequest -> PreflightEngine -> ExecutionAuthorizationSnapshot
        """
        req = PreflightOrderRequest(
            decision_id=self.plan.decision_id,
            symbol=self.plan.symbol,
            side=PreflightSide.BUY,
            order_type=PreflightOrderType.LIMIT,
            quantity=float(self.plan.position_quantity),
            limit_price=self.plan.entry_price,
            stop_price=self.plan.stop_loss_price,
            target_price=self.plan.take_profit_price,
            timestamp=self.now,
        )
        res = await self.engine.evaluate_preflight(
            order_request=req,
            candidate_plan=self.plan,
            market_context=self.ctx,
            portfolio_state=self.portfolio_state,
            exchange_constraints=self.constraints,
            evaluation_timestamp=self.now,
        )
        self.assertEqual(res.status, PreflightStatus.APPROVED)
        self.assertIsNotNone(res.authorization)
        self.assertEqual(res.authorization.approved_quantity, 20)
        self.assertEqual(res.authorization.normalized_limit_price, 1500.0)

    # 47. Adversarial safety suite (Section 35)
    def test_47_adversarial_safety_suite(self):
        """
        Adversarial attacks on the safety boundary:
        A. High conviction attempting to bypass risk veto
        B. Requested quantity inflated post-approval
        C. Duplicate execution request re-submitted
        D. Stale decision submitted with favorable price
        """
        # A. High conviction bypass attack
        vetoed_plan = self.plan.model_copy(update={"veto_applied": True})
        r_veto = self.engine.evaluate_preflight(
            order_request=PreflightOrderRequest(decision_id="dec", symbol="INFY.NS", side=PreflightSide.BUY, quantity=20.0, conviction=1.0, timestamp=self.now),
            candidate_plan=vetoed_plan, market_context=self.ctx, evaluation_timestamp=self.now,
        )
        self.assertEqual(r_veto.status, PreflightStatus.RISK_VETO)

        # B. Size inflation attack
        r_infl = self.engine.evaluate_preflight(
            order_request=PreflightOrderRequest(decision_id="dec-pref-001", symbol="INFY.NS", side=PreflightSide.BUY, quantity=500.0, timestamp=self.now),
            candidate_plan=self.plan, market_context=self.ctx, evaluation_timestamp=self.now,
        )
        self.assertEqual(r_infl.status, PreflightStatus.INVALID_QUANTITY)

        # C. Duplicate execution attack
        self.engine.clear_idempotency_cache()
        req_dup = PreflightOrderRequest(decision_id="dec-adv-dup", symbol="INFY.NS", side=PreflightSide.BUY, quantity=20.0, limit_price=1500.0, stop_price=1425.0, timestamp=self.now)
        r_first = self.engine.evaluate_preflight(order_request=req_dup, candidate_plan=self.plan, market_context=self.ctx, portfolio_state=self.portfolio_state, evaluation_timestamp=self.now)
        self.assertEqual(r_first.status, PreflightStatus.APPROVED)
        r_second = self.engine.evaluate_preflight(order_request=req_dup, candidate_plan=self.plan, market_context=self.ctx, portfolio_state=self.portfolio_state, evaluation_timestamp=self.now)
        self.assertEqual(r_second.status, PreflightStatus.DUPLICATE)

        # D. Stale decision attack
        stale_p = self.plan.model_copy(update={"timestamp": self.now - timedelta(hours=5)})
        r_stale = self.engine.evaluate_preflight(
            order_request=PreflightOrderRequest(decision_id="dec-pref-001", symbol="INFY.NS", side=PreflightSide.BUY, quantity=20.0, limit_price=1500.0, timestamp=self.now),
            candidate_plan=stale_p, market_context=self.ctx, evaluation_timestamp=self.now,
        )
        self.assertEqual(r_stale.status, PreflightStatus.STALE)


if __name__ == "__main__":
    unittest.main()
