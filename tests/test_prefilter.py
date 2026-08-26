"""
Unit tests for Deterministic Prefilter — Phase 5.3

Validates price thresholds, historical bar sufficiency, and missing-data resilience.
"""

import unittest

from backend.scanner.prefilter import DeterministicPrefilter
from backend.scanner.scanner_config import ScannerConfig


class TestDeterministicPrefilter(unittest.TestCase):
    def setUp(self):
        self.config = ScannerConfig(
            min_price=50.0,
            max_price=10000.0,
            min_historical_bars=10,
            require_positive_price=True,
        )
        self.prefilter = DeterministicPrefilter(self.config)

    def test_valid_candidate_passes_prefilter(self):
        data = {
            "current_price": 500.0,
            "ohlcv_historical": [{"close": 500.0}] * 15,
            "technical_indicators": {"rsi_14": 55.0, "ema_20": 490.0},
        }
        res = self.prefilter.filter_candidate("TCS.NS", data)
        self.assertTrue(res.passed)
        self.assertEqual(len(res.rejection_reasons), 0)
        self.assertEqual(res.current_price, 500.0)

    def test_price_below_minimum_rejected(self):
        data = {
            "current_price": 20.0,  # Below min_price 50.0
            "ohlcv_historical": [{"close": 20.0}] * 15,
        }
        res = self.prefilter.filter_candidate("PENNY.NS", data)
        self.assertFalse(res.passed)
        self.assertTrue(any("below minimum" in r for r in res.rejection_reasons))

    def test_price_above_maximum_rejected(self):
        data = {
            "current_price": 50000.0,  # Above max_price 10000.0
            "ohlcv_historical": [{"close": 50000.0}] * 15,
        }
        res = self.prefilter.filter_candidate("MRF.NS", data)
        self.assertFalse(res.passed)
        self.assertTrue(any("exceeds maximum" in r for r in res.rejection_reasons))

    def test_insufficient_bars_rejected(self):
        data = {
            "current_price": 500.0,
            "ohlcv_historical": [{"close": 500.0}] * 5,  # Only 5 bars < 10
        }
        res = self.prefilter.filter_candidate("NEW_LISTING.NS", data)
        self.assertFalse(res.passed)
        self.assertTrue(any("Insufficient historical bars" in r for r in res.rejection_reasons))

    def test_missing_fundamentals_does_not_crash_prefilter(self):
        # Missing fundamentals should not crash the cheap prefilter
        data = {
            "current_price": 1000.0,
            "ohlcv_historical": [{"close": 1000.0}] * 12,
            "fundamental_data": {},
            "news_data": {},
            "institutional_data": [],
        }
        res = self.prefilter.filter_candidate("NO_DATA.NS", data)
        self.assertTrue(res.passed)
        self.assertFalse(res.metrics_summary["has_fundamentals"])


if __name__ == "__main__":
    unittest.main()
