"""
Tests for Phase 3.7 — SectorCalculator.

All tests are offline and deterministic.
No Groq calls. No Yahoo Finance calls. No external network.
Every assertion uses hand-computed expected values.
"""

import unittest
from datetime import datetime, timezone

from backend.specialists.sector_calculator import (
    SectorMetric,
    calc_benchmark_return,
    calc_company_return,
    calc_relative_to_benchmark,
    calc_relative_to_sector,
    calc_sector_return,
    calc_sector_to_benchmark_spread,
    compute_all_sector_metrics,
    extract_sector_metadata,
)

# ─── Shared Fixtures ──────────────────────────────────────────────────────────

_CONTEXT_ID = "ctx-sec-calc-001"
_TIMESTAMP = datetime(2024, 3, 15, 12, 0, 0, tzinfo=timezone.utc)

_OHLCV_5D = [
    {"date": "2024-03-11", "open": 100.0, "high": 105.0, "low": 99.0, "close": 100.0, "volume": 1000},
    {"date": "2024-03-12", "open": 101.0, "high": 106.0, "low": 100.0, "close": 103.0, "volume": 1100},
    {"date": "2024-03-13", "open": 103.0, "high": 108.0, "low": 102.0, "close": 106.0, "volume": 1200},
    {"date": "2024-03-14", "open": 106.0, "high": 110.0, "low": 105.0, "close": 108.0, "volume": 1300},
    {"date": "2024-03-15", "open": 108.0, "high": 112.0, "low": 107.0, "close": 110.0, "volume": 1400},
]  # first_close = 100.0, last_close = 110.0 -> +10.0% return

_SECTOR_DATA = {
    "sector": "Information Technology",
    "industry": "Software - Infrastructure",
    "sector_symbol": "^CNXIT",
    "benchmark_symbol": "^NSEI",
    "sector_return_pct": 6.0,
    "benchmark_return_pct": 2.5,
}


# ─── 1. Company Return ───────────────────────────────────────────────────────

class TestCompanyReturn(unittest.TestCase):

    def test_company_return_normal(self):
        """((110 - 100) / 100) * 100 = +10.0%."""
        m = calc_company_return(
            ohlcv_historical=_OHLCV_5D,
            context_id=_CONTEXT_ID,
            data_timestamp=_TIMESTAMP,
        )
        self.assertTrue(m.available)
        self.assertAlmostEqual(m.value, 10.0, places=4)
        self.assertEqual(m.metric_name, "company_return")
        self.assertEqual(m.unit, "%")
        self.assertEqual(m.context_id, _CONTEXT_ID)

    def test_company_return_insufficient_history(self):
        """1 row -> unavailable."""
        m = calc_company_return(
            ohlcv_historical=[_OHLCV_5D[0]],
            context_id=_CONTEXT_ID,
            data_timestamp=_TIMESTAMP,
        )
        self.assertFalse(m.available)
        self.assertIn("minimum 2 required", m.unavailable_reason)

    def test_company_return_empty_history(self):
        """0 rows -> unavailable."""
        m = calc_company_return(
            ohlcv_historical=[],
            context_id=_CONTEXT_ID,
            data_timestamp=_TIMESTAMP,
        )
        self.assertFalse(m.available)

    def test_company_return_non_positive_first_close(self):
        """first_close <= 0 -> unavailable."""
        bad_ohlcv = [
            {"date": "2024-03-11", "close": 0.0},
            {"date": "2024-03-12", "close": 105.0},
        ]
        m = calc_company_return(
            ohlcv_historical=bad_ohlcv,
            context_id=_CONTEXT_ID,
            data_timestamp=_TIMESTAMP,
        )
        self.assertFalse(m.available)
        self.assertIn("non-positive", m.unavailable_reason)

    def test_company_return_nan_close(self):
        """NaN close -> unavailable."""
        bad_ohlcv = [
            {"date": "2024-03-11", "close": float("nan")},
            {"date": "2024-03-12", "close": 105.0},
        ]
        m = calc_company_return(
            ohlcv_historical=bad_ohlcv,
            context_id=_CONTEXT_ID,
            data_timestamp=_TIMESTAMP,
        )
        self.assertFalse(m.available)


# ─── 2. Sector Return ────────────────────────────────────────────────────────

class TestSectorReturn(unittest.TestCase):

    def test_sector_return_normal(self):
        """sector_return_pct = 6.0%."""
        m = calc_sector_return(
            sector_data=_SECTOR_DATA,
            context_id=_CONTEXT_ID,
            data_timestamp=_TIMESTAMP,
        )
        self.assertTrue(m.available)
        self.assertAlmostEqual(m.value, 6.0, places=4)
        self.assertEqual(m.metric_name, "sector_return")

    def test_sector_return_missing(self):
        """Missing sector_return_pct -> unavailable."""
        m = calc_sector_return(
            sector_data={"sector": "IT"},
            context_id=_CONTEXT_ID,
            data_timestamp=_TIMESTAMP,
        )
        self.assertFalse(m.available)
        self.assertIn("missing", m.unavailable_reason)

    def test_sector_return_nan(self):
        """NaN sector_return_pct -> unavailable."""
        m = calc_sector_return(
            sector_data={"sector_return_pct": float("nan")},
            context_id=_CONTEXT_ID,
            data_timestamp=_TIMESTAMP,
        )
        self.assertFalse(m.available)


# ─── 3. Benchmark Return ─────────────────────────────────────────────────────

class TestBenchmarkReturn(unittest.TestCase):

    def test_benchmark_return_normal(self):
        """benchmark_return_pct = 2.5%."""
        m = calc_benchmark_return(
            sector_data=_SECTOR_DATA,
            context_id=_CONTEXT_ID,
            data_timestamp=_TIMESTAMP,
        )
        self.assertTrue(m.available)
        self.assertAlmostEqual(m.value, 2.5, places=4)
        self.assertEqual(m.metric_name, "benchmark_return")

    def test_benchmark_return_missing(self):
        """Missing benchmark_return_pct -> unavailable."""
        m = calc_benchmark_return(
            sector_data={},
            context_id=_CONTEXT_ID,
            data_timestamp=_TIMESTAMP,
        )
        self.assertFalse(m.available)


# ─── 4. Relative Performance Spreads ─────────────────────────────────────────

class TestRelativeSpreads(unittest.TestCase):

    def setUp(self):
        self.comp_m = calc_company_return(_OHLCV_5D, _CONTEXT_ID, _TIMESTAMP)  # +10.0%
        self.sec_m = calc_sector_return(_SECTOR_DATA, _CONTEXT_ID, _TIMESTAMP)  # +6.0%
        self.bm_m = calc_benchmark_return(_SECTOR_DATA, _CONTEXT_ID, _TIMESTAMP)  # +2.5%

    def test_relative_to_sector_normal(self):
        """10.0 - 6.0 = +4.0 percentage points outperformance."""
        m = calc_relative_to_sector(self.comp_m, self.sec_m, _CONTEXT_ID, _TIMESTAMP)
        self.assertTrue(m.available)
        self.assertAlmostEqual(m.value, 4.0, places=4)
        self.assertEqual(m.metric_name, "relative_to_sector")

    def test_relative_to_benchmark_normal(self):
        """10.0 - 2.5 = +7.5 percentage points outperformance."""
        m = calc_relative_to_benchmark(self.comp_m, self.bm_m, _CONTEXT_ID, _TIMESTAMP)
        self.assertTrue(m.available)
        self.assertAlmostEqual(m.value, 7.5, places=4)
        self.assertEqual(m.metric_name, "relative_to_benchmark")

    def test_sector_to_benchmark_spread_normal(self):
        """6.0 - 2.5 = +3.5 percentage points sector outperformance."""
        m = calc_sector_to_benchmark_spread(self.sec_m, self.bm_m, _CONTEXT_ID, _TIMESTAMP)
        self.assertTrue(m.available)
        self.assertAlmostEqual(m.value, 3.5, places=4)
        self.assertEqual(m.metric_name, "sector_to_benchmark_spread")

    def test_spread_propagates_unavailability(self):
        """If component metric is unavailable, spread is unavailable."""
        unavail_sec = calc_sector_return({}, _CONTEXT_ID, _TIMESTAMP)
        m = calc_relative_to_sector(self.comp_m, unavail_sec, _CONTEXT_ID, _TIMESTAMP)
        self.assertFalse(m.available)
        self.assertIn("unavailable", m.unavailable_reason.lower())


# ─── 5. Master Runner & Metadata ─────────────────────────────────────────────

class TestMasterRunner(unittest.TestCase):

    def test_compute_all_returns_six_metrics(self):
        """compute_all_sector_metrics returns exactly 6 metrics in defined order."""
        metrics = compute_all_sector_metrics(
            sector_data=_SECTOR_DATA,
            ohlcv_historical=_OHLCV_5D,
            context_id=_CONTEXT_ID,
            data_timestamp=_TIMESTAMP,
        )
        self.assertEqual(len(metrics), 6)
        expected_names = [
            "company_return",
            "sector_return",
            "benchmark_return",
            "relative_to_sector",
            "relative_to_benchmark",
            "sector_to_benchmark_spread",
        ]
        self.assertEqual([m.metric_name for m in metrics], expected_names)
        self.assertTrue(all(m.available for m in metrics))

    def test_compute_all_empty_data(self):
        """Empty sector data -> company return available, others unavailable."""
        metrics = compute_all_sector_metrics(
            sector_data={},
            ohlcv_historical=_OHLCV_5D,
            context_id=_CONTEXT_ID,
            data_timestamp=_TIMESTAMP,
        )
        self.assertEqual(len(metrics), 6)
        self.assertTrue(metrics[0].available)  # company return
        self.assertFalse(metrics[1].available)  # sector return
        self.assertFalse(metrics[2].available)  # benchmark return
        self.assertFalse(metrics[3].available)  # relative to sector
        self.assertFalse(metrics[4].available)  # relative to benchmark
        self.assertFalse(metrics[5].available)  # sector vs benchmark

    def test_extract_metadata(self):
        """extract_sector_metadata returns (sector, industry, benchmark)."""
        sector, industry, benchmark = extract_sector_metadata(_SECTOR_DATA)
        self.assertEqual(sector, "Information Technology")
        self.assertEqual(industry, "Software - Infrastructure")
        self.assertEqual(benchmark, "^NSEI")

    def test_extract_metadata_defaults(self):
        """extract_sector_metadata defaults missing fields cleanly."""
        sector, industry, benchmark = extract_sector_metadata({})
        self.assertEqual(sector, "UNKNOWN")
        self.assertEqual(industry, "UNKNOWN")
        self.assertEqual(benchmark, "N/A")


if __name__ == "__main__":
    unittest.main()
