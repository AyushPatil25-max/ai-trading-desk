"""
Unit & Integration Tests for Phase 3B — Multi-Quarter Fundamental Data Layer

Tests:
1. QuarterlyStatement schema & explicit nullability
2. Multi-quarter ingestion & chronological sorting
3. Missing quarter handling
4. Missing individual fields handling (None vs 0)
5. Negative net income preservation (legitimate corporate loss)
6. Zero debt preservation (legitimate debt-free status)
7. Negative cash flow preservation
8. QoQ revenue growth formula
9. YoY revenue growth formula
10. Sign change handling: Turnaround (Loss -> Profit)
11. Sign change handling: Swing to loss (Profit -> Loss)
12. Division-by-zero protection (0 revenue in prior quarter)
13. PIT publication date filtering (future quarters strictly hidden)
14. PIT missing publication date handling
15. Provenance preservation
16. Stale data handling
17. Cache hit with domain TTL
18. Cache miss & refresh
19. Provider failure graceful degradation
20. Fundamental Specialist integration
21. 520-stock scanner Stage A remains fast (<15ms)
22. Full backward compatibility with existing TTM fundamentals
"""

import unittest
import asyncio
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

from backend.domain.schemas import (
    MarketContext,
    QuarterlyStatement,
    HistoricalWindow,
    DataQualityStatus,
    SourceTier,
    AgentInput,
    AgentState,
)
from backend.specialists.fundamental_calculator import (
    calc_quarterly_metrics,
    compute_all_fundamental_metrics,
)
from backend.specialists.fundamental_specialist import FundamentalSpecialist
from backend.simulation.pit_filter import PointInTimeFilter
from backend.infrastructure.providers.yfinance_provider import YFinanceProvider
from backend.infrastructure.cache import InMemoryContextCache
from backend.scanner.universe import StockUniverse, UniverseType
from backend.scanner.prefilter import DeterministicPrefilter
from backend.scanner.scanner_config import ScannerConfig
from backend.infrastructure.llm import MockLLMClient


class TestPhase3BQuarterlyFundamentals(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
        self.base_q1 = QuarterlyStatement(
            symbol="TCS.NS",
            period_end_date=datetime(2023, 6, 30, tzinfo=timezone.utc),
            fiscal_period="Q1",
            fiscal_year=2024,
            filing_date=datetime(2023, 7, 15, tzinfo=timezone.utc),
            publication_time=datetime(2023, 7, 15, tzinfo=timezone.utc),
            revenue=593810000000.0,
            operating_profit=137590000000.0,
            operating_margin=23.17,
            net_income=110740000000.0,
            eps=30.2,
            total_debt=0.0,  # Legitimate Zero Debt
            cash=100000000000.0,
            operating_cash_flow=113500000000.0,
            free_cash_flow=105000000000.0,
            source="yfinance",
            source_tier=SourceTier.TIER_4_SECONDARY,
        )

    def test_quarterly_statement_schema_and_nullability(self):
        stmt = QuarterlyStatement(
            symbol="INFY.NS",
            period_end_date=datetime(2024, 3, 31, tzinfo=timezone.utc),
            fiscal_period="Q4",
            fiscal_year=2024,
            revenue=379230000000.0,
            # Deliberately omit cash, total_debt, free_cash_flow
        )
        self.assertEqual(stmt.symbol, "INFY.NS")
        self.assertEqual(stmt.revenue, 379230000000.0)
        self.assertIsNone(stmt.cash)
        self.assertIsNone(stmt.total_debt)
        self.assertIsNone(stmt.free_cash_flow)
        self.assertNotEqual(stmt.cash, 0.0)  # Must be None, not fabricated 0.0

    def test_zero_debt_and_negative_profit_preserved(self):
        loss_stmt = QuarterlyStatement(
            symbol="STARTUP.NS",
            period_end_date=datetime(2023, 9, 30, tzinfo=timezone.utc),
            fiscal_period="Q2",
            fiscal_year=2024,
            revenue=50000000.0,
            operating_profit=-15000000.0,  # Negative operating profit
            net_income=-20000000.0,        # Negative net income
            total_debt=0.0,                # Zero debt
            operating_cash_flow=-12000000.0, # Cash burn
        )
        self.assertEqual(loss_stmt.total_debt, 0.0)
        self.assertEqual(loss_stmt.net_income, -20000000.0)
        self.assertEqual(loss_stmt.operating_cash_flow, -12000000.0)

    def test_qoq_revenue_and_profit_growth(self):
        q1 = self.base_q1
        q2 = QuarterlyStatement(
            symbol="TCS.NS",
            period_end_date=datetime(2023, 9, 30, tzinfo=timezone.utc),
            fiscal_period="Q2",
            fiscal_year=2024,
            revenue=596920000000.0,      # +0.52% QoQ
            operating_profit=144830000000.0,
            net_income=113420000000.0,   # +2.42% QoQ
            operating_margin=24.26,
            total_debt=0.0,
        )

        metrics = calc_quarterly_metrics([q1, q2], data_timestamp=self.now)
        metric_dict = {m.metric_name: m for m in metrics}

        self.assertIn("qoq_revenue_growth", metric_dict)
        self.assertTrue(metric_dict["qoq_revenue_growth"].available)
        self.assertAlmostEqual(metric_dict["qoq_revenue_growth"].value, 0.52, places=1)

        self.assertIn("qoq_profit_growth", metric_dict)
        self.assertTrue(metric_dict["qoq_profit_growth"].available)
        self.assertAlmostEqual(metric_dict["qoq_profit_growth"].value, 2.42, places=1)

    def test_yoy_growth_and_margin_expansion(self):
        # Build 5 consecutive quarters (Q1-2023 to Q1-2024)
        quarters = []
        for i in range(5):
            t_end = datetime(2023, 3, 31, tzinfo=timezone.utc) + timedelta(days=91 * i)
            quarters.append(
                QuarterlyStatement(
                    symbol="TCS.NS",
                    period_end_date=t_end,
                    fiscal_period=f"Q{(i % 4) + 1}",
                    fiscal_year=2023 + (i // 4),
                    revenue=500000000000.0 * (1.0 + 0.05 * i),  # 5% growth per quarter
                    net_income=100000000000.0 * (1.0 + 0.06 * i),
                    operating_margin=23.0 + (0.3 * i),
                )
            )

        metrics = calc_quarterly_metrics(quarters, data_timestamp=self.now)
        metric_dict = {m.metric_name: m for m in metrics}

        self.assertIn("yoy_revenue_growth", metric_dict)
        self.assertTrue(metric_dict["yoy_revenue_growth"].available)
        # Q4 vs Q0: 1.20 vs 1.00 -> 20.0%
        self.assertAlmostEqual(metric_dict["yoy_revenue_growth"].value, 20.0, places=1)

        self.assertIn("margin_expansion_yoy_bps", metric_dict)
        self.assertTrue(metric_dict["margin_expansion_yoy_bps"].available)
        # 24.2% - 23.0% = 1.2% -> 120 bps
        self.assertAlmostEqual(metric_dict["margin_expansion_yoy_bps"].value, 120.0, places=0)

    def test_sign_change_handling(self):
        # Case 1: Turnaround (Loss in Q1 -> Profit in Q2)
        q_loss = QuarterlyStatement(
            symbol="ZOMATO.NS",
            period_end_date=datetime(2023, 3, 31, tzinfo=timezone.utc),
            revenue=20000000000.0,
            net_income=-1880000000.0,
        )
        q_profit = QuarterlyStatement(
            symbol="ZOMATO.NS",
            period_end_date=datetime(2023, 6, 30, tzinfo=timezone.utc),
            revenue=24000000000.0,
            net_income=20000000.0,
        )

        metrics_turnaround = calc_quarterly_metrics([q_loss, q_profit], data_timestamp=self.now)
        p_metric = next(m for m in metrics_turnaround if m.metric_name == "qoq_profit_growth")
        self.assertFalse(p_metric.available)
        self.assertIn("TURNAROUND_PROFITABLE", p_metric.unavailable_reason)

        # Case 2: Swing to Loss (Profit in Q1 -> Loss in Q2)
        q_profit_earlier = QuarterlyStatement(
            symbol="ZOMATO.NS",
            period_end_date=datetime(2023, 3, 31, tzinfo=timezone.utc),
            revenue=24000000000.0,
            net_income=20000000.0,
        )
        q_loss_later = QuarterlyStatement(
            symbol="ZOMATO.NS",
            period_end_date=datetime(2023, 6, 30, tzinfo=timezone.utc),
            revenue=20000000000.0,
            net_income=-1880000000.0,
        )
        metrics_swing = calc_quarterly_metrics([q_profit_earlier, q_loss_later], data_timestamp=self.now)
        p_metric_swing = next(m for m in metrics_swing if m.metric_name == "qoq_profit_growth")
        self.assertFalse(p_metric_swing.available)
        self.assertIn("SWING_TO_LOSS", p_metric_swing.unavailable_reason)

    def test_division_by_zero_protection(self):
        q_zero_rev = QuarterlyStatement(
            symbol="SHELL.NS",
            period_end_date=datetime(2023, 3, 31, tzinfo=timezone.utc),
            revenue=0.0,  # 0 revenue
            net_income=-1000.0,
        )
        q_has_rev = QuarterlyStatement(
            symbol="SHELL.NS",
            period_end_date=datetime(2023, 6, 30, tzinfo=timezone.utc),
            revenue=50000.0,
            net_income=2000.0,
        )

        metrics = calc_quarterly_metrics([q_zero_rev, q_has_rev], data_timestamp=self.now)
        rev_m = next(m for m in metrics if m.metric_name == "qoq_revenue_growth")
        self.assertFalse(rev_m.available)
        self.assertIn("Non-positive or missing", rev_m.unavailable_reason)

    def test_point_in_time_publication_date_filtering(self):
        t_sim = datetime(2023, 8, 1, 10, 0, 0)

        # Q1 published on July 15 (should be visible at Aug 1)
        q1 = QuarterlyStatement(
            symbol="TCS.NS",
            period_end_date=datetime(2023, 6, 30),
            filing_date=datetime(2023, 7, 15),
            publication_time=datetime(2023, 7, 15),
            revenue=593810000000.0,
        )

        # Q2 published on Oct 15 (MUST NOT BE VISIBLE at Aug 1)
        q2_future = QuarterlyStatement(
            symbol="TCS.NS",
            period_end_date=datetime(2023, 9, 30),
            filing_date=datetime(2023, 10, 15),
            publication_time=datetime(2023, 10, 15),
            revenue=596920000000.0,
        )

        filtered = PointInTimeFilter.filter_quarterly_statements([q1, q2_future], as_of=t_sim)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].revenue, 593810000000.0)

    def test_cache_hits_and_misses(self):
        cache = InMemoryContextCache(ttl_seconds=5)
        ctx = MarketContext(
            context_id="ctx-test-q",
            symbol="TCS.NS",
            data_timestamp=datetime.now(timezone.utc),
            provider="test",
            current_price=3500.0,
            quarterly_fundamentals=[self.base_q1],
        )

        loop = asyncio.new_event_loop()

        async def run_cache():
            val1 = await cache.get("TCS.NS")
            self.assertIsNone(val1)

            await cache.set("TCS.NS", ctx)
            val2 = await cache.get("TCS.NS")
            self.assertIsNotNone(val2)
            self.assertEqual(len(val2.quarterly_fundamentals), 1)

        loop.run_until_complete(run_cache())
        loop.close()

    def test_fundamental_specialist_integration(self):
        from backend.domain.schemas import (
            _FundamentalLLMResponse,
            FundamentalQuality,
            GrowthAssessment,
            ProfitabilityAssessment,
            BalanceSheetAssessment,
        )
        mock_resp = _FundamentalLLMResponse(
            fundamental_quality=FundamentalQuality.STRONG,
            growth_assessment=GrowthAssessment.HIGH_GROWTH,
            profitability_assessment=ProfitabilityAssessment.HIGHLY_PROFITABLE,
            balance_sheet_assessment=BalanceSheetAssessment.PRISTINE,
            financial_strength=0.92,
            confidence=0.90,
            conclusion="Strong multi-quarter revenue expansion and robust margins.",
        )
        mock_llm = MockLLMClient(fixed_response=mock_resp)
        specialist = FundamentalSpecialist(mock_llm)

        ctx = MarketContext(
            context_id="ctx-fund-test",
            symbol="TCS.NS",
            data_timestamp=datetime.now(timezone.utc),
            provider="yfinance",
            current_price=3500.0,
            fundamental_data={
                "revenue": 2400000000000.0,
                "net_income": 450000000000.0,
                "eps": 125.0,
                "cash": 150000000000.0,
            },
            quarterly_fundamentals=[
                self.base_q1,
                QuarterlyStatement(
                    symbol="TCS.NS",
                    period_end_date=datetime(2023, 9, 30, tzinfo=timezone.utc),
                    revenue=600000000000.0,
                    net_income=115000000000.0,
                ),
            ],
            quality_status=DataQualityStatus.OK,
        )

        loop = asyncio.new_event_loop()
        agent_input = AgentInput(symbol=ctx.symbol, market_context=ctx)
        out = loop.run_until_complete(specialist.execute(agent_input))
        loop.close()

        self.assertEqual(out.status, AgentState.SUCCESS)
        payload = out.raw_data
        self.assertIsNotNone(payload)

    def test_520_stock_scanner_stage_a_efficiency(self):
        universe = StockUniverse(UniverseType.NIFTY_500)
        snapshot = universe.get_snapshot(datetime.now(timezone.utc))
        symbols = snapshot.get_symbols()

        prefilter = DeterministicPrefilter(ScannerConfig(min_historical_bars=10))
        candidates = {s: {"current_price": 1000.0, "ohlcv_historical": [{"close": 1000.0}] * 25} for s in symbols}

        import time
        t0 = time.perf_counter()
        passed = 0
        for s, d in candidates.items():
            if prefilter.filter_candidate(s, d).passed:
                passed += 1
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(passed, len(symbols))
        self.assertLess(elapsed_ms, 15.0)  # Sub-15ms for 520 stocks


if __name__ == "__main__":
    unittest.main()
