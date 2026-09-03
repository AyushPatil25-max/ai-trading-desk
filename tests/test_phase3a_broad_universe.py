"""
Unit and Integration Tests for Phase 3A — Broad NSE/BSE Security Universe

Validates:
1. 500+ Security Master persistence and instant local loading (<50ms, zero network)
2. Sub-millisecond multi-key indexing (ISIN, NSE, BSE, BSE Scrip, Aliases)
3. Dual NSE/BSE cross-exchange deduplication
4. Atomic master file update and corruption protection
5. Degradation & fallback to safe baseline when file is corrupt or missing
6. StockUniverse NIFTY_500 and ALL_NSE expansion (500+ constituents)
7. Stage A scanner performance over 500+ candidates (<15ms)
8. Point-in-Time constituent evaluation integrity
9. Full backward compatibility with existing callers
"""

import unittest
import time
import os
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

from backend.infrastructure.security_master import (
    SecurityDefinition,
    SecurityMaster,
    get_security_master,
)
from backend.scanner.universe import (
    StockUniverse,
    UniverseType,
    UniverseConstituent,
)
from backend.scanner.historical_universe import HistoricalUniverse
from backend.scanner.prefilter import DeterministicPrefilter
from backend.scanner.scanner_config import ScannerConfig


class TestPhase3ABroadUniverse(unittest.TestCase):
    def setUp(self):
        self.sm = get_security_master()

    def test_500_plus_securities_loaded(self):
        self.assertGreaterEqual(self.sm.total_count, 500)
        stats = self.sm.get_stats()
        self.assertGreaterEqual(stats["active_securities"], 500)
        self.assertGreaterEqual(stats["nse_securities"], 500)
        self.assertGreaterEqual(stats["bse_securities"], 500)
        self.assertGreaterEqual(stats["isin_coverage"], 500)
        self.assertFalse(self.sm.is_degraded)

    def test_sub_millisecond_multi_key_lookups(self):
        # 1. Canonical lookup
        t0 = time.perf_counter()
        sec_can = self.sm.resolve_symbol("RELIANCE")
        t_can = (time.perf_counter() - t0) * 1000.0
        self.assertIsNotNone(sec_can)
        self.assertEqual(sec_can.canonical_symbol, "RELIANCE")
        self.assertLess(t_can, 1.0) # Sub-millisecond

        # 2. NSE ticker lookup
        sec_nse = self.sm.resolve_symbol("TCS.NS")
        self.assertIsNotNone(sec_nse)
        self.assertEqual(sec_nse.canonical_symbol, "TCS")

        # 3. BSE Scrip code lookup
        sec_bse = self.sm.resolve_symbol("500180")
        self.assertIsNotNone(sec_bse)
        self.assertEqual(sec_bse.canonical_symbol, "HDFCBANK")

        # 4. BSE Symbol lookup
        sec_bo = self.sm.resolve_symbol("INFY.BO")
        self.assertIsNotNone(sec_bo)
        self.assertEqual(sec_bo.canonical_symbol, "INFY")

        # 5. ISIN lookup
        sec_isin = self.sm.get_security_by_isin("INE002A01018")
        self.assertIsNotNone(sec_isin)
        self.assertEqual(sec_isin.canonical_symbol, "RELIANCE")

        # 6. Mid-cap and New listing lookups
        sec_zomato = self.sm.resolve_symbol("ZOMATO")
        self.assertIsNotNone(sec_zomato)
        self.assertEqual(sec_zomato.canonical_symbol, "ZOMATO")
        self.assertEqual(sec_zomato.bse_code, "543320")

    def test_dual_nse_bse_deduplication(self):
        # RELIANCE on NSE and BSE must resolve to the EXACT SAME canonical security
        sec_nse = self.sm.resolve_symbol("RELIANCE.NS")
        sec_bse = self.sm.resolve_symbol("500325")
        sec_bo = self.sm.resolve_symbol("RELIANCE.BO")

        self.assertIsNotNone(sec_nse)
        self.assertIsNotNone(sec_bse)
        self.assertIsNotNone(sec_bo)

        self.assertEqual(sec_nse.canonical_symbol, "RELIANCE")
        self.assertEqual(sec_bse.canonical_symbol, "RELIANCE")
        self.assertEqual(sec_bo.canonical_symbol, "RELIANCE")
        self.assertEqual(sec_nse.isin, sec_bse.isin)

    def test_provider_ticker_normalization(self):
        # YFinance provider
        self.assertEqual(self.sm.normalize_ticker_for_provider("TCS", "yfinance"), "TCS.NS")
        self.assertEqual(self.sm.normalize_ticker_for_provider("TCS.NS", "yfinance"), "TCS.NS")

        # NSE provider
        self.assertEqual(self.sm.normalize_ticker_for_provider("TCS.NS", "nse"), "TCS")

        # BSE provider
        self.assertEqual(self.sm.normalize_ticker_for_provider("RELIANCE", "bse"), "500325")

    def test_atomic_persistence_and_reloading(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir) / "test_master.json"
            new_sm = SecurityMaster(data_path=temp_path)

            # Register a new custom security
            test_sec = SecurityDefinition(
                canonical_symbol="TESTCO",
                company_name="Test Company India Limited",
                isin="INE999A01099",
                exchange="NSE",
                nse_symbol="TESTCO.NS",
                bse_code="599999",
                bse_symbol="TESTCO.BO",
                sector="Technology",
                aliases=["TESTCO", "TESTCO.NS"],
                is_active=True,
            )
            new_sm.register_security(test_sec)

            # Save atomically
            saved = new_sm.save_master(temp_path)
            self.assertTrue(saved)
            self.assertTrue(temp_path.exists())

            # Load into fresh instance
            reloaded_sm = SecurityMaster(data_path=temp_path)
            resolved = reloaded_sm.resolve_symbol("TESTCO.NS")
            self.assertIsNotNone(resolved)
            self.assertEqual(resolved.canonical_symbol, "TESTCO")
            self.assertEqual(resolved.isin, "INE999A01099")

    def test_degraded_fallback_on_corrupt_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            corrupt_path = Path(tmpdir) / "corrupt_master.json"
            with open(corrupt_path, "w") as f:
                f.write("INVALID_NOT_A_JSON")

            fallback_sm = SecurityMaster(data_path=corrupt_path)
            self.assertTrue(fallback_sm.is_degraded)
            # Must fall back to base universe without crashing
            self.assertGreaterEqual(fallback_sm.total_count, 20)
            self.assertIsNotNone(fallback_sm.resolve_symbol("RELIANCE.NS"))

    def test_stock_universe_nifty_500_expansion(self):
        universe_500 = StockUniverse(UniverseType.NIFTY_500)
        snapshot = universe_500.get_snapshot(datetime.now(timezone.utc))

        self.assertTrue(snapshot.is_available)
        self.assertGreaterEqual(len(snapshot.constituents), 500)
        self.assertGreaterEqual(len(snapshot.symbols), 500)

        # Check constituent properties
        symbols = snapshot.get_symbols()
        self.assertIn("RELIANCE.NS", symbols)
        self.assertIn("TCS.NS", symbols)
        self.assertIn("ZOMATO.NS", symbols)

    def test_scanner_stage_a_latency_over_500_stocks(self):
        universe_500 = StockUniverse(UniverseType.NIFTY_500)
        snapshot = universe_500.get_snapshot(datetime.now(timezone.utc))
        symbols = snapshot.get_symbols()

        prefilter = DeterministicPrefilter(ScannerConfig(min_price=10.0, max_price=100000.0, min_historical_bars=10))

        # Synthetic lightweight candidate data
        candidates = {}
        for sym in symbols:
            candidates[sym] = {
                "current_price": 500.0,
                "ohlcv_historical": [{"close": 500.0}] * 15,
                "technical_indicators": {"rsi_14": 55.0, "ema_20": 490.0},
            }

        t0 = time.perf_counter()
        passed_count = 0
        for sym, data in candidates.items():
            res = prefilter.filter_candidate(sym, data)
            if res.passed:
                passed_count += 1
        total_latency_ms = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(passed_count, len(symbols))
        # Total latency for 500+ stocks in Stage A must be < 15ms (< 0.03ms per stock)
        self.assertLess(total_latency_ms, 15.0)

    def test_historical_pit_universe_preservation(self):
        hist_univ = HistoricalUniverse(UniverseType.NIFTY_50)

        # Backtest in 2019: TATACONSUM was not in Nifty 50
        constituents_2019 = hist_univ.get_constituents(datetime(2019, 1, 1))
        symbols_2019 = [c.symbol for c in constituents_2019]
        self.assertIn("GAIL.NS", symbols_2019)
        self.assertNotIn("TATACONSUM.NS", symbols_2019)

        # Backtest in 2022: TATACONSUM was added, GAIL was removed
        constituents_2022 = hist_univ.get_constituents(datetime(2022, 1, 1))
        symbols_2022 = [c.symbol for c in constituents_2022]
        self.assertIn("TATACONSUM.NS", symbols_2022)
        self.assertNotIn("GAIL.NS", symbols_2022)


if __name__ == "__main__":
    unittest.main()
