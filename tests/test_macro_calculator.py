import unittest
from datetime import datetime
from backend.domain.schemas import MarketContext, HistoricalWindow
from backend.specialists.macro_calculator import MacroCalculator

class TestMacroCalculator(unittest.TestCase):
    def setUp(self):
        self.base_context = MarketContext(
            context_id="test_macro_123",
            symbol="AAPL",
            data_timestamp=datetime(2025, 1, 1),
            provider="test",
            historical_window=HistoricalWindow.RECENT,
            current_price=150.0,
            macro_data={}
        )

    def test_calculate_with_full_data(self):
        ctx = self.base_context.model_copy(update={
            "macro_data": {
                "policy_rate": 5.25,
                "inflation_rate": 3.1,
                "treasury_10y": 4.1,
                "treasury_2y": 4.5,
                "gdp_growth": 2.5
            }
        })
        metrics = MacroCalculator.calculate_macro_metrics(ctx)
        
        # We expect policy_rate, inflation_rate, real_rate, t10, t2, spread, gdp
        available_metrics = [m for m in metrics if m.available]
        self.assertEqual(len(available_metrics), 7)
        
        metrics_dict = {m.metric_name: m.value for m in available_metrics}
        self.assertEqual(metrics_dict["policy_rate"], 5.25)
        self.assertEqual(metrics_dict["inflation_rate"], 3.1)
        self.assertAlmostEqual(metrics_dict["real_rate"], 2.15)
        self.assertAlmostEqual(metrics_dict["yield_spread_10y_2y"], -40.0) # (4.1 - 4.5) * 100
        self.assertEqual(metrics_dict["gdp_growth"], 2.5)

    def test_calculate_with_missing_data(self):
        # Empty macro data
        metrics = MacroCalculator.calculate_macro_metrics(self.base_context)
        available_metrics = [m for m in metrics if m.available]
        self.assertEqual(len(available_metrics), 0)
        
        # Verify unavailable records exist for core metrics
        metrics_dict = {m.metric_name: m.available for m in metrics}
        self.assertFalse(metrics_dict["policy_rate"])
        self.assertFalse(metrics_dict["inflation_rate"])
        self.assertFalse(metrics_dict["real_rate"])
        self.assertFalse(metrics_dict["yield_spread_10y_2y"])

if __name__ == '__main__':
    unittest.main()
