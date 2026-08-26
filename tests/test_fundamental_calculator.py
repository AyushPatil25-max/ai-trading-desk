"""
Tests for fundamental_calculator.py — Phase 3.5.

Pure deterministic math and provenance tests. No LLM, no network, no mocks.
Every test uses fixed numerical fixtures with known expected outputs.
"""

import unittest
from datetime import datetime, timezone

from backend.specialists.fundamental_calculator import (
    FundamentalMetric,
    assess_data_freshness,
    calc_current_ratio,
    calc_debt_to_equity,
    calc_eps_growth_yoy,
    calc_free_cash_flow,
    calc_gross_margin,
    calc_net_margin,
    calc_operating_margin,
    calc_pe_ratio,
    calc_revenue_growth_yoy,
    calc_roe,
    compute_all_fundamental_metrics,
    extract_passthrough_metric,
)


class TestFundamentalMargins(unittest.TestCase):
    def test_gross_margin_known_value(self):
        # Rev: 1000, GP: 400 -> 40.0%
        data = {"revenue": 1000.0, "gross_profit": 400.0, "period": "FY2023"}
        metric = calc_gross_margin(data)
        self.assertTrue(metric.available)
        self.assertEqual(metric.value, 40.0)
        self.assertEqual(metric.unit, "%")
        self.assertEqual(metric.period, "FY2023")
        self.assertEqual(metric.source, "income_statement")

    def test_gross_margin_missing_data(self):
        data = {"revenue": 1000.0}
        metric = calc_gross_margin(data)
        self.assertFalse(metric.available)
        self.assertIsNone(metric.value)
        self.assertIn("Missing", metric.unavailable_reason)

    def test_gross_margin_zero_revenue(self):
        data = {"revenue": 0.0, "gross_profit": 0.0}
        metric = calc_gross_margin(data)
        self.assertFalse(metric.available)
        self.assertIn("Non-positive", metric.unavailable_reason)

    def test_operating_margin_known_value(self):
        # Rev: 2500, Op Profit: 625 -> 25.0%
        data = {"revenue": 2500.0, "operating_profit": 625.0}
        metric = calc_operating_margin(data)
        self.assertTrue(metric.available)
        self.assertEqual(metric.value, 25.0)

    def test_net_margin_known_value(self):
        # Rev: 10000, Net Income: 1500 -> 15.0%
        data = {"revenue": 10000.0, "net_income": 1500.0}
        metric = calc_net_margin(data)
        self.assertTrue(metric.available)
        self.assertEqual(metric.value, 15.0)


class TestFundamentalGrowth(unittest.TestCase):
    def test_revenue_growth_known_value(self):
        # Prior: 1000, Current: 1200 -> +20.0%
        data = {"revenue": 1200.0, "prior_revenue": 1000.0}
        metric = calc_revenue_growth_yoy(data)
        self.assertTrue(metric.available)
        self.assertEqual(metric.value, 20.0)

    def test_revenue_growth_direct_field(self):
        data = {"revenue_growth_yoy": 18.5}
        metric = calc_revenue_growth_yoy(data)
        self.assertTrue(metric.available)
        self.assertEqual(metric.value, 18.5)

    def test_revenue_growth_missing_prior(self):
        data = {"revenue": 1200.0}
        metric = calc_revenue_growth_yoy(data)
        self.assertFalse(metric.available)

    def test_eps_growth_known_value(self):
        # Prior: 10.0, Current: 15.0 -> +50.0%
        data = {"eps": 15.0, "prior_eps": 10.0}
        metric = calc_eps_growth_yoy(data)
        self.assertTrue(metric.available)
        self.assertEqual(metric.value, 50.0)

    def test_eps_growth_negative_prior(self):
        # Prior: -5.0, Current: 5.0 -> ((5 - (-5)) / abs(-5)) * 100 = 200.0%
        data = {"eps": 5.0, "prior_eps": -5.0}
        metric = calc_eps_growth_yoy(data)
        self.assertTrue(metric.available)
        self.assertEqual(metric.value, 200.0)


class TestBalanceSheetSolvency(unittest.TestCase):
    def test_debt_to_equity_known_value(self):
        # Debt: 500, Equity: 1000 -> 0.50
        data = {"total_debt": 500.0, "total_equity": 1000.0}
        metric = calc_debt_to_equity(data)
        self.assertTrue(metric.available)
        self.assertEqual(metric.value, 0.50)
        self.assertEqual(metric.unit, "ratio")

    def test_debt_to_equity_zero_debt(self):
        # Debt: 0, Equity: 1000 -> 0.0 (Debt free)
        data = {"total_debt": 0.0, "total_equity": 1000.0}
        metric = calc_debt_to_equity(data)
        self.assertTrue(metric.available)
        self.assertEqual(metric.value, 0.0)

    def test_current_ratio_known_value(self):
        # Assets: 1500, Liab: 1000 -> 1.50
        data = {"current_assets": 1500.0, "current_liabilities": 1000.0}
        metric = calc_current_ratio(data)
        self.assertTrue(metric.available)
        self.assertEqual(metric.value, 1.50)

    def test_roe_known_value(self):
        # Net income: 200, Equity: 1000 -> 20.0%
        data = {"net_income": 200.0, "total_equity": 1000.0}
        metric = calc_roe(data)
        self.assertTrue(metric.available)
        self.assertEqual(metric.value, 20.0)


class TestCashFlowAndValuation(unittest.TestCase):
    def test_free_cash_flow_calculation(self):
        # OCF: 1000, capex: 300 -> FCF = 700
        data = {"operating_cash_flow": 1000.0, "capex": 300.0}
        metric = calc_free_cash_flow(data)
        self.assertTrue(metric.available)
        self.assertEqual(metric.value, 700.0)

    def test_free_cash_flow_negative_capex_handling(self):
        # Capex reported as negative outflow -300 -> FCF = 1000 - abs(-300) = 700
        data = {"operating_cash_flow": 1000.0, "capex": -300.0}
        metric = calc_free_cash_flow(data)
        self.assertTrue(metric.available)
        self.assertEqual(metric.value, 700.0)

    def test_pe_ratio_known_value(self):
        # Price: 100.0, EPS: 5.0 -> PE = 20.0
        data = {"eps": 5.0}
        metric = calc_pe_ratio(100.0, data)
        self.assertTrue(metric.available)
        self.assertEqual(metric.value, 20.0)

    def test_pe_ratio_negative_eps(self):
        # EPS <= 0 -> unavailable
        data = {"eps": -2.5}
        metric = calc_pe_ratio(100.0, data)
        self.assertFalse(metric.available)


class TestDataFreshness(unittest.TestCase):
    def test_freshness_fresh_data(self):
        # 30 days old
        data = {"report_date": "2024-01-01"}
        now = datetime(2024, 1, 31, tzinfo=timezone.utc)
        status, age = assess_data_freshness(data, market_timestamp=now, max_stale_days=180)
        self.assertEqual(status, "FRESH")
        self.assertEqual(age, 30)

    def test_freshness_stale_data(self):
        # 250 days old > 180
        data = {"report_date": "2023-01-01"}
        now = datetime(2023, 9, 15, tzinfo=timezone.utc)
        status, age = assess_data_freshness(data, market_timestamp=now, max_stale_days=180)
        self.assertEqual(status, "STALE")
        self.assertGreater(age, 180)

    def test_freshness_empty_data(self):
        status, age = assess_data_freshness({})
        self.assertEqual(status, "UNAVAILABLE")
        self.assertIsNone(age)


class TestComputeAllFundamentalMetrics(unittest.TestCase):
    def test_compute_all_empty_dict(self):
        metrics = compute_all_fundamental_metrics({}, current_price=100.0)
        self.assertIsInstance(metrics, list)
        self.assertGreater(len(metrics), 5)
        # All should be unavailable
        for m in metrics:
            self.assertFalse(m.available)
            self.assertTrue(m.unavailable_reason)

    def test_compute_all_full_dataset(self):
        data = {
            "period": "FY2023",
            "report_date": "2023-12-31",
            "revenue": 10000.0,
            "prior_revenue": 8000.0,
            "gross_profit": 4000.0,
            "operating_profit": 2000.0,
            "net_income": 1500.0,
            "eps": 15.0,
            "prior_eps": 12.0,
            "total_debt": 2000.0,
            "total_equity": 5000.0,
            "current_assets": 4000.0,
            "current_liabilities": 2000.0,
            "operating_cash_flow": 1800.0,
            "capex": 500.0,
            "cash": 1200.0,
        }
        metrics = compute_all_fundamental_metrics(data, current_price=300.0)
        rec_map = {m.metric_name: m for m in metrics}

        self.assertEqual(rec_map["gross_margin"].value, 40.0)
        self.assertEqual(rec_map["operating_margin"].value, 20.0)
        self.assertEqual(rec_map["net_margin"].value, 15.0)
        self.assertEqual(rec_map["revenue_growth_yoy"].value, 25.0)
        self.assertEqual(rec_map["eps_growth_yoy"].value, 25.0)
        self.assertEqual(rec_map["debt_to_equity"].value, 0.40)
        self.assertEqual(rec_map["current_ratio"].value, 2.0)
        self.assertEqual(rec_map["return_on_equity"].value, 30.0)
        self.assertEqual(rec_map["free_cash_flow"].value, 1300.0)
        self.assertEqual(rec_map["pe_ratio"].value, 20.0)
        self.assertEqual(rec_map["revenue"].value, 10000.0)
        self.assertEqual(rec_map["cash_and_equivalents"].value, 1200.0)


if __name__ == "__main__":
    unittest.main()
