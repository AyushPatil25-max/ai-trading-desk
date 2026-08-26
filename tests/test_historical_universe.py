"""
Unit tests for Historical Point-In-Time Universe — Phase 5.4C

Validates point-in-time constituent membership, entry/exit timestamp enforcement,
and historical reconstitution event tracking.
"""

from datetime import datetime
import unittest

from backend.scanner.historical_universe import HistoricalUniverse


class TestHistoricalUniverse(unittest.TestCase):
    def setUp(self):
        self.hu = HistoricalUniverse()

    def test_core_continuous_constituents_active_across_all_dates(self):
        t2020 = datetime(2020, 1, 1)
        t2024 = datetime(2024, 1, 1)

        self.assertTrue(self.hu.is_constituent_at("RELIANCE.NS", t2020))
        self.assertTrue(self.hu.is_constituent_at("RELIANCE.NS", t2024))
        self.assertTrue(self.hu.is_constituent_at("TCS.NS", t2020))
        self.assertTrue(self.hu.is_constituent_at("TCS.NS", t2024))

    def test_historical_additions_not_active_before_effective_date(self):
        # TATACONSUM added March 2021
        t_before = datetime(2020, 1, 1)
        t_after = datetime(2022, 1, 1)

        self.assertFalse(self.hu.is_constituent_at("TATACONSUM.NS", t_before))
        self.assertTrue(self.hu.is_constituent_at("TATACONSUM.NS", t_after))

    def test_historical_deletions_not_active_after_exit_date(self):
        # GAIL removed March 2021
        t_before = datetime(2020, 1, 1)
        t_after = datetime(2022, 1, 1)

        self.assertTrue(self.hu.is_constituent_at("GAIL.NS", t_before))
        self.assertFalse(self.hu.is_constituent_at("GAIL.NS", t_after))

    def test_future_addition_rejection(self):
        # TRENT added Sept 2024
        t2023 = datetime(2023, 1, 1)
        t2025 = datetime(2025, 1, 1)

        self.assertFalse(self.hu.is_constituent_at("TRENT.NS", t2023))
        self.assertTrue(self.hu.is_constituent_at("TRENT.NS", t2025))


if __name__ == "__main__":
    unittest.main()
