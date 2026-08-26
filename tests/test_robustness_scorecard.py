"""
Unit tests for Robustness & Validation Scorecard — Phase 5.4

Validates cost sensitivities, slippage drag calculations, and scorecard calculation logic.
"""

import unittest

from backend.simulation.simulation_state import PerformanceMetrics
from backend.validation.robustness import RobustnessEngine


class TestRobustnessScorecard(unittest.TestCase):
    def setUp(self):
        self.engine = RobustnessEngine()
        self.metrics = PerformanceMetrics(
            initial_capital=100000.0,
            final_capital=118000.0,
            total_return_pct=18.0,
            annualized_volatility=13.0,
            max_drawdown_pct=7.0,
            sharpe_ratio=1.55,
            win_rate=64.0,
            profit_factor=2.05,
            turnover=2.5,
            total_trades=15,
        )

    def test_cost_sensitivity_measures_higher_drag_at_higher_costs(self):
        bps_list = [0, 10, 50]
        slippage_list = [0.0, 0.0010]
        points = self.engine.evaluate_cost_sensitivity(self.metrics, bps_list, slippage_list)
        self.assertEqual(len(points), 6)

        zero_cost = next(p for p in points if p.commission_bps == 0 and p.slippage_pct == 0.0)
        high_cost = next(p for p in points if p.commission_bps == 50 and p.slippage_pct == 0.0010)

        self.assertGreater(zero_cost.total_return_pct, high_cost.total_return_pct)
        self.assertGreater(high_cost.total_cost_paid, zero_cost.total_cost_paid)

    def test_validation_scorecard_calculation(self):
        scorecard = self.engine.compute_scorecard(self.metrics, is_clean_pit=True)
        self.assertGreaterEqual(scorecard.overall_validation_score, 0.0)
        self.assertLessEqual(scorecard.overall_validation_score, 100.0)
        self.assertTrue(scorecard.passed_validation)
        self.assertEqual(scorecard.data_quality_score, 100.0)

    def test_scorecard_fails_if_pit_leaked(self):
        scorecard = self.engine.compute_scorecard(self.metrics, is_clean_pit=False)
        self.assertFalse(scorecard.passed_validation)
        self.assertEqual(scorecard.data_quality_score, 0.0)


if __name__ == "__main__":
    unittest.main()
