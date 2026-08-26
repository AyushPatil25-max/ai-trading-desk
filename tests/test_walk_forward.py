"""
Unit tests for Walk-Forward Engine — Phase 5.4

Validates window generation, chronological non-overlapping partitions,
and multi-window out-of-sample execution.
"""

from datetime import datetime, timedelta
import unittest

from backend.scanner.universe import StockUniverse, UniverseConstituent, UniverseType
from backend.validation.validation_config import WalkForwardConfig
from backend.validation.walk_forward import WalkForwardEngine


class TestWalkForward(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.t_start = datetime(2020, 1, 1)
        self.t_end = datetime(2025, 1, 1)
        self.config = WalkForwardConfig(
            train_window_days=756,  # 3y
            val_window_days=252,    # 1y
            test_window_days=252,   # 1y
            step_days=252,          # 1y
        )
        self.engine = WalkForwardEngine(config=self.config)

    def test_window_generation_chronological_and_sequential(self):
        windows = self.engine.generate_windows(self.t_start, self.t_end)
        self.assertGreater(len(windows), 0)

        for i, win in enumerate(windows):
            self.assertEqual(win.window_index, i)
            # Strict chronological order within window
            self.assertLess(win.train_start, win.train_end)
            self.assertLessEqual(win.train_end, win.val_start)
            self.assertLess(win.val_start, win.val_end)
            self.assertLessEqual(win.val_end, win.test_start)
            self.assertLess(win.test_start, win.test_end)

            # Check next window steps forward
            if i > 0:
                prev_win = windows[i - 1]
                self.assertGreater(win.train_start, prev_win.train_start)

    def test_short_range_window_generation_fallback(self):
        short_start = datetime(2023, 1, 1)
        short_end = datetime(2023, 12, 31)
        windows = self.engine.generate_windows(short_start, short_end)
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].train_start, short_start)
        self.assertEqual(windows[0].test_end, short_end)

    async def test_walk_forward_execution_generates_result_and_metrics(self):
        custom_constituents = [
            UniverseConstituent(symbol="TCS.NS", company_name="TCS", effective_from=datetime(2022, 1, 1)),
        ]
        universe = StockUniverse(UniverseType.CUSTOM, constituents=custom_constituents)
        engine = WalkForwardEngine(config=self.config, universe=universe)

        datasets = {
            "TCS.NS": {
                "current_price": 3000.0,
                "ohlcv_historical": [
                    {"timestamp": "2023-01-01 10:00:00", "close": 3000.0},
                    {"timestamp": "2023-04-01 10:00:00", "close": 3100.0},
                    {"timestamp": "2023-07-01 10:00:00", "close": 3200.0},
                    {"timestamp": "2023-10-01 10:00:00", "close": 3300.0},
                ] * 10,
                "fundamental_data": {"pe_ratio": 22.0, "net_profit": 5000.0},
                "news_data": {},
                "institutional_data": [],
            }
        }

        res = await engine.run_walk_forward(
            historical_datasets=datasets,
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 12, 31),
        )
        self.assertIsNotNone(res.run_id)
        self.assertGreater(len(res.windows), 0)
        self.assertIsNotNone(res.overall_out_of_sample_metrics)
        self.assertIsNotNone(res.scorecard)
        self.assertTrue(res.scorecard.passed_validation)


if __name__ == "__main__":
    unittest.main()
