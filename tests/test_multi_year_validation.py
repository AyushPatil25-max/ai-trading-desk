"""
Unit tests for Multi-Year Walk-Forward Validation — Phase 5.4C

Validates multi-year chronological partitioning across 2020 through 2025 timelines.
"""

from datetime import datetime
import unittest

from backend.scanner.historical_universe import HistoricalUniverse
from backend.validation.validation_config import WalkForwardConfig
from backend.validation.walk_forward import WalkForwardEngine


class TestMultiYearValidation(unittest.TestCase):
    def setUp(self):
        self.config = WalkForwardConfig(
            train_window_days=756,  # 3y
            val_window_days=252,    # 1y
            test_window_days=252,   # 1y
            step_days=252,          # 1y
        )
        self.engine = WalkForwardEngine(config=self.config)

    def test_multi_year_window_partitioning_2020_to_2025(self):
        t_start = datetime(2020, 1, 1)
        t_end = datetime(2025, 1, 1)

        windows = self.engine.generate_windows(t_start, t_end)
        self.assertGreaterEqual(len(windows), 2)

        for win in windows:
            self.assertGreaterEqual(win.train_start, t_start)
            self.assertLessEqual(win.test_end, t_end)
            self.assertLess(win.train_end, win.test_start)


if __name__ == "__main__":
    unittest.main()
