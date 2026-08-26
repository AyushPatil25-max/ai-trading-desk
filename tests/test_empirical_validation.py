"""
Unit tests for Empirical Validation & Strategy Classification — Phase 5.4A

Validates provider availability auditing, data sufficiency percentage calculation,
deterministic strategy classification rules, and reproducibility hashing.
"""

from datetime import datetime
import unittest

from backend.domain.schemas import SourceTier
from backend.scanner.universe import StockUniverse, UniverseConstituent, UniverseType
from backend.simulation.simulation_state import PerformanceMetrics
from backend.validation.empirical_audit import (
    DataSufficiencyReport,
    DataTrustAuditor,
    StrategyClassification,
)
from backend.validation.empirical_runner import EmpiricalValidationRunner
from backend.validation.validation_config import WalkForwardConfig


class TestEmpiricalValidation(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.t0 = datetime(2023, 1, 1)
        self.t1 = datetime(2023, 12, 31)
        self.config = WalkForwardConfig()

    def test_audit_providers_covers_all_integrated_sources(self):
        entries = DataTrustAuditor.audit_providers()
        self.assertGreaterEqual(len(entries), 8)

        datasets = [e.dataset for e in entries]
        self.assertTrue(any("OHLCV" in d for d in datasets))
        self.assertTrue(any("Financial Statements" in d for d in datasets))
        self.assertTrue(any("Institutional Flows" in d for d in datasets))
        self.assertTrue(any("Macroeconomic" in d for d in datasets))
        self.assertTrue(any("Universe Constituents" in d for d in datasets))

    def test_audit_data_sufficiency_calculates_specialist_percentages(self):
        dataset = {
            "TCS.NS": {
                "ohlcv_historical": [{"timestamp": "2023-01-01", "close": 3000.0}] * 25,
                "technical_indicators": {"rsi_14": 55.0},
                "fundamental_data": {"pe_ratio": 22.0, "net_profit": 5000.0},
                "news_data": {"articles": [{"title": "News 1"}]},
                "institutional_data": [{"observed_at": datetime(2023, 1, 1), "net_value": 100.0}],
            },
            "INFY.NS": {
                "ohlcv_historical": [{"timestamp": "2023-01-01", "close": 1500.0}] * 25,
                "technical_indicators": {"rsi_14": 50.0},
                "fundamental_data": {},
                "news_data": {},
                "institutional_data": [],
            },
        }
        report = DataTrustAuditor.audit_data_sufficiency(dataset)
        self.assertGreater(report.overall_data_completeness_pct, 0.0)
        self.assertEqual(report.specialist_availability["Technical"], 100.0)  # Both have >= 20 bars
        self.assertEqual(report.specialist_availability["Fundamental"], 50.0) # 1 of 2 has fundamentals
        self.assertTrue(report.survivorship_bias_risk)

    def test_strategy_classification_rules(self):
        # 1. Insufficient data
        metrics_low_sample = PerformanceMetrics(
            initial_capital=100000.0, final_capital=105000.0, total_return_pct=5.0, total_trades=2
        )
        report_low = DataSufficiencyReport(overall_data_completeness_pct=20.0)
        c1, _ = DataTrustAuditor.classify_strategy(metrics_low_sample, report_low, is_clean_pit=True, survivorship_bias=False)
        self.assertEqual(c1, StrategyClassification.INSUFFICIENT_DATA)

        # 2. Point-in-time leakage fail
        metrics_good = PerformanceMetrics(
            initial_capital=100000.0, final_capital=115000.0, total_return_pct=15.0, sharpe_ratio=1.5,
            max_drawdown_pct=8.0, win_rate=60.0, profit_factor=2.0, total_trades=15
        )
        report_good = DataSufficiencyReport(overall_data_completeness_pct=80.0)
        c2, _ = DataTrustAuditor.classify_strategy(metrics_good, report_good, is_clean_pit=False, survivorship_bias=False)
        self.assertEqual(c2, StrategyClassification.NOT_CURRENTLY_PROMISING)

        # 3. Positive performance with survivorship bias
        c3, _ = DataTrustAuditor.classify_strategy(metrics_good, report_good, is_clean_pit=True, survivorship_bias=True)
        self.assertEqual(c3, StrategyClassification.MIXED_INCONCLUSIVE)

        # 4. Strong performance survivorship-free
        c4, _ = DataTrustAuditor.classify_strategy(metrics_good, report_good, is_clean_pit=True, survivorship_bias=False)
        self.assertEqual(c4, StrategyClassification.EMPIRICALLY_PROMISING)

        # 5. Negative return underperformance
        metrics_neg = PerformanceMetrics(
            initial_capital=100000.0, final_capital=90000.0, total_return_pct=-10.0, total_trades=10
        )
        c5, _ = DataTrustAuditor.classify_strategy(metrics_neg, report_good, is_clean_pit=True, survivorship_bias=False)
        self.assertEqual(c5, StrategyClassification.NOT_CURRENTLY_PROMISING)

    async def test_empirical_validation_runner_and_reproducibility(self):
        custom_constituents = [
            UniverseConstituent(symbol="TCS.NS", company_name="TCS", effective_from=datetime(2022, 1, 1)),
        ]
        universe = StockUniverse(UniverseType.CUSTOM, constituents=custom_constituents)
        runner = EmpiricalValidationRunner(config=self.config, universe=universe)

        dataset = {
            "TCS.NS": {
                "current_price": 3000.0,
                "ohlcv_historical": [
                    {"timestamp": "2023-01-01 10:00:00", "close": 3000.0},
                    {"timestamp": "2023-06-01 10:00:00", "close": 3200.0},
                    {"timestamp": "2023-12-01 10:00:00", "close": 3300.0},
                ] * 10,
                "fundamental_data": {"pe_ratio": 22.0, "net_profit": 5000.0},
                "news_data": {},
                "institutional_data": [],
            }
        }

        wf_res, scorecard = await runner.run_empirical_validation(dataset, start_date=self.t0, end_date=self.t1)
        self.assertIsNotNone(scorecard.reproducibility_hash)
        self.assertIn(
            scorecard.classification,
            [
                StrategyClassification.INSUFFICIENT_DATA,
                StrategyClassification.MIXED_INCONCLUSIVE,
                StrategyClassification.EMPIRICALLY_PROMISING,
            ],
        )

        md = EmpiricalValidationRunner.to_markdown(scorecard, wf_res)
        self.assertIn("# Empirical Strategy Validation Report:", md)
        self.assertIn("REAL_MARKET_DATA", md)


if __name__ == "__main__":
    unittest.main()
