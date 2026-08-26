"""
Unit tests for Strategy Baselines & Regime Analysis — Phase 5.4

Validates baseline strategy evaluations (Buy & Hold, Equal Weight, Momentum, Technical, Scanner)
and market regime segmentations (Bull, Bear, Sideways, High/Low Volatility).
"""

import unittest

from backend.simulation.simulation_state import PerformanceMetrics
from backend.validation.robustness import RobustnessEngine
from backend.validation.validation_state import RegimeType


class TestStrategyBaselines(unittest.TestCase):
    def setUp(self):
        self.engine = RobustnessEngine()
        self.metrics = PerformanceMetrics(
            initial_capital=100000.0,
            final_capital=115000.0,
            total_return_pct=15.0,
            annualized_volatility=14.0,
            max_drawdown_pct=8.5,
            sharpe_ratio=1.45,
            sortino_ratio=1.85,
            win_rate=62.0,
            profit_factor=1.95,
            total_trades=20,
        )

    def test_evaluate_baselines_contains_required_strategies(self):
        baselines = self.engine.evaluate_baselines(self.metrics, benchmark_returns=10.0)
        strategy_names = [b.strategy_name for b in baselines]

        self.assertTrue(any("Buy-and-Hold" in name for name in strategy_names))
        self.assertTrue(any("Equal-Weight" in name for name in strategy_names))
        self.assertTrue(any("Technical Baseline" in name for name in strategy_names))
        self.assertTrue(any("Momentum Baseline" in name for name in strategy_names))
        self.assertTrue(any("Scanner-Only" in name for name in strategy_names))
        self.assertTrue(any("Full AI Trading Desk" in name for name in strategy_names))

        # Strategy return should match metrics
        full_ai = next(b for b in baselines if "Full AI Trading Desk" in b.strategy_name)
        self.assertEqual(full_ai.total_return_pct, 15.0)

    def test_evaluate_regimes_covers_all_regimes(self):
        regimes = self.engine.evaluate_regimes(self.metrics, benchmark_returns=10.0)
        regime_types = {r.regime for r in regimes}

        self.assertIn(RegimeType.BULL, regime_types)
        self.assertIn(RegimeType.BEAR, regime_types)
        self.assertIn(RegimeType.SIDEWAYS, regime_types)
        self.assertIn(RegimeType.HIGH_VOLATILITY, regime_types)
        self.assertIn(RegimeType.LOW_VOLATILITY, regime_types)

        bull = next(r for r in regimes if r.regime == RegimeType.BULL)
        bear = next(r for r in regimes if r.regime == RegimeType.BEAR)
        self.assertGreater(bull.total_return_pct, bear.total_return_pct)


if __name__ == "__main__":
    unittest.main()
