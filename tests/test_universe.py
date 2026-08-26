"""
Unit tests for Stock Universe Abstraction — Phase 5.3

Validates Point-in-Time constituent filtering, custom universe loading,
and duplicate prevention.
"""

from datetime import datetime, timedelta
import unittest

from backend.scanner.universe import StockUniverse, UniverseConstituent, UniverseType


class TestStockUniverse(unittest.TestCase):
    def setUp(self):
        self.t0 = datetime(2023, 1, 1)
        self.t1 = datetime(2023, 6, 1)
        self.t2 = datetime(2024, 1, 1)
        self.t3 = datetime(2024, 6, 1)

    def test_default_nifty_50_universe_loading(self):
        universe = StockUniverse(UniverseType.NIFTY_50)
        snapshot = universe.get_snapshot(self.t2)
        self.assertTrue(snapshot.is_available)
        self.assertGreater(len(snapshot.constituents), 10)
        self.assertIn("RELIANCE.NS", snapshot.get_symbols())
        self.assertIn("TCS.NS", snapshot.get_symbols())

    def test_point_in_time_constituent_membership(self):
        # Constituent added on 2023-06-01 and removed on 2024-01-01
        custom_constituents = [
            UniverseConstituent(
                symbol="STOCK_A.NS",
                company_name="Stock A",
                effective_from=self.t0,
                effective_to=None,
            ),
            UniverseConstituent(
                symbol="STOCK_B.NS",
                company_name="Stock B",
                effective_from=self.t1,
                effective_to=self.t2,
            ),
        ]
        universe = StockUniverse(UniverseType.CUSTOM, constituents=custom_constituents)

        # Before T1 (2023-01-01): Only STOCK_A
        snap_t0 = universe.get_snapshot(self.t0)
        self.assertEqual(snap_t0.get_symbols(), ["STOCK_A.NS"])

        # At T1 (2023-06-01): Both STOCK_A and STOCK_B
        snap_t1 = universe.get_snapshot(self.t1)
        self.assertEqual(sorted(snap_t1.get_symbols()), ["STOCK_A.NS", "STOCK_B.NS"])

        # After T2 (2024-06-01): STOCK_B has expired -> Only STOCK_A
        snap_t3 = universe.get_snapshot(self.t3)
        self.assertEqual(snap_t3.get_symbols(), ["STOCK_A.NS"])

    def test_future_constituent_leakage_prevented(self):
        # A stock joining in the future (2024) must NOT appear in 2023 snapshot
        custom_constituents = [
            UniverseConstituent(
                symbol="FUTURE_IPO.NS",
                company_name="Future IPO",
                effective_from=self.t2,  # 2024-01-01
            )
        ]
        universe = StockUniverse(UniverseType.CUSTOM, constituents=custom_constituents)
        snapshot = universe.get_snapshot(self.t0)  # 2023-01-01
        self.assertNotIn("FUTURE_IPO.NS", snapshot.get_symbols())
        self.assertFalse(snapshot.is_available)

    def test_duplicate_symbol_deduplication(self):
        custom_constituents = [
            UniverseConstituent(symbol="TCS.NS", company_name="TCS 1", effective_from=self.t0),
            UniverseConstituent(symbol="TCS.NS", company_name="TCS 2", effective_from=self.t0),
        ]
        universe = StockUniverse(UniverseType.CUSTOM, constituents=custom_constituents)
        snapshot = universe.get_snapshot(self.t1)
        self.assertEqual(len(snapshot.get_symbols()), 1)

    def test_create_custom_universe_helper(self):
        raw_list = [
            {"symbol": "INFY.NS", "company_name": "Infosys", "sector": "Technology", "effective_from": "2022-01-01"},
            {"symbol": "HDFCBANK.NS", "company_name": "HDFC Bank", "sector": "Financials", "effective_from": "2022-01-01"},
        ]
        universe = StockUniverse.create_custom_universe(raw_list)
        snapshot = universe.get_snapshot(self.t2)
        self.assertEqual(len(snapshot.get_symbols()), 2)
        self.assertIn("INFY.NS", snapshot.get_symbols())


if __name__ == "__main__":
    unittest.main()
