"""
Tests for quant_calculator.py — Phase 3.4.

Pure deterministic math tests. No LLM, no network, no mocks.
Every test uses fixed numerical fixtures with known expected outputs.
"""

import math
import unittest
from datetime import datetime

from backend.specialists.quant_calculator import (
    QuantMetric,
    _compute_daily_returns,
    calc_5d_cumulative_return,
    calc_5d_price_range_pct,
    calc_avg_volume_5d,
    calc_ema_spread_pct,
    calc_price_zscore_5d,
    calc_realized_volatility_5d,
    calc_return_mean_5d,
    calc_rsi_extremity,
    calc_trend_consistency_5d,
    calc_realized_volatility_20d,
    calc_max_drawdown_20d,
    calc_sharpe_ratio_annualized,
    calc_sortino_ratio_annualized,
    calc_rolling_vol_20d,
    compute_all_metrics,
)

# ── Fixture helpers ────────────────────────────────────────────────────────────

def _ohlcv(closes, volumes=None) -> list:
    """Build minimal OHLCV rows from a close price list."""
    if volumes is None:
        volumes = [1_000_000] * len(closes)
    rows = []
    for i, (c, v) in enumerate(zip(closes, volumes)):
        rows.append({
            "date": f"2024-01-{i+1:02d}T00:00:00+00:00",
            "open": c,
            "high": c * 1.005,
            "low": c * 0.995,
            "close": c,
            "volume": v,
        })
    return rows


# ── 1. Daily returns ───────────────────────────────────────────────────────────

class TestDailyReturns(unittest.TestCase):
    def test_returns_known_values(self):
        """
        100→110→99: two returns.
        r_1 = (110-100)/100 = +0.10
        r_2 = (99-110)/110 = -11/110 = -1/10 = -0.1
        """
        returns = _compute_daily_returns([100.0, 110.0, 99.0])
        self.assertEqual(len(returns), 2)
        self.assertAlmostEqual(returns[0], 0.10, places=10)
        # r_2 = (99 - 110) / 110 = -11/110 = -0.1 exactly
        self.assertAlmostEqual(returns[1], -1.0 / 10.0, places=10)

    def test_single_price_returns_empty(self):
        """Single observation → no return."""
        self.assertEqual(_compute_daily_returns([100.0]), [])

    def test_empty_returns_empty(self):
        self.assertEqual(_compute_daily_returns([]), [])

    def test_zero_denominator_skipped(self):
        """Zero close price is skipped gracefully."""
        returns = _compute_daily_returns([0.0, 100.0, 110.0])
        # Step 0→1: prev=0 skipped; step 1→2: valid → 0.10
        self.assertEqual(len(returns), 1)
        self.assertAlmostEqual(returns[0], 0.10, places=10)

    def test_constant_prices_return_zeros(self):
        """Constant price series → all returns are 0.0."""
        returns = _compute_daily_returns([50.0, 50.0, 50.0, 50.0])
        self.assertEqual(len(returns), 3)
        for r in returns:
            self.assertAlmostEqual(r, 0.0)


# ── 2. Cumulative return ───────────────────────────────────────────────────────

class TestCumulativeReturn(unittest.TestCase):
    def test_known_value(self):
        """100 → 120: return = +20%."""
        result = calc_5d_cumulative_return(_ohlcv([100.0, 105.0, 110.0, 115.0, 120.0]))
        self.assertTrue(result.available)
        self.assertAlmostEqual(result.value, 20.0, places=4)

    def test_negative_return(self):
        """100 → 80: return = -20%."""
        result = calc_5d_cumulative_return(_ohlcv([100.0, 95.0, 90.0, 85.0, 80.0]))
        self.assertTrue(result.available)
        self.assertAlmostEqual(result.value, -20.0, places=4)

    def test_insufficient_data(self):
        """Single row → unavailable."""
        result = calc_5d_cumulative_return(_ohlcv([100.0]))
        self.assertFalse(result.available)
        self.assertIsNone(result.value)
        self.assertIn("observation", result.unavailable_reason.lower())

    def test_empty_data(self):
        result = calc_5d_cumulative_return([])
        self.assertFalse(result.available)

    def test_zero_first_close_excluded_by_filter(self):
        """
        _extract_closes excludes non-positive values (v > 0).
        So ohlcv([0.0, 100.0, 105.0]) yields closes=[100.0, 105.0] → AVAILABLE.
        Zero is dropped before reaching the division guard.
        """
        result = calc_5d_cumulative_return(_ohlcv([0.0, 100.0, 105.0]))
        # After filtering: first=100, last=105 → return = +5%
        self.assertTrue(result.available)
        self.assertAlmostEqual(result.value, 5.0, places=4)

    def test_all_zero_closes_unavailable(self):
        """All-zero closes → all filtered → empty → unavailable."""
        result = calc_5d_cumulative_return(_ohlcv([0.0, 0.0, 0.0]))
        self.assertFalse(result.available)
        self.assertIsNone(result.value)

    def test_provenance_fields(self):
        result = calc_5d_cumulative_return(_ohlcv([100.0, 110.0]))
        self.assertEqual(result.metric_name, "cumulative_return_5d")
        self.assertEqual(result.unit, "%")
        self.assertEqual(result.window, "5D")
        self.assertEqual(result.source, "ohlcv_historical")
        self.assertIn("close", result.calculation_method.lower())


# ── 3. Realized volatility ────────────────────────────────────────────────────

class TestRealizedVolatility(unittest.TestCase):
    def test_constant_prices_zero_vol(self):
        """Constant prices → zero volatility (std=0 → vol=0)."""
        result = calc_realized_volatility_5d(_ohlcv([100.0, 100.0, 100.0, 100.0]))
        self.assertTrue(result.available)
        self.assertAlmostEqual(result.value, 0.0, places=6)

    def test_vol_is_non_negative(self):
        """Realized vol must be ≥ 0 (property test with varied data)."""
        for closes in [
            [100, 110, 90, 105, 95],
            [50, 51, 49, 50, 52],
            [200, 195, 205, 198, 202],
        ]:
            result = calc_realized_volatility_5d(_ohlcv([float(c) for c in closes]))
            if result.available:
                self.assertGreaterEqual(result.value, 0.0)

    def test_insufficient_data_two_closes(self):
        """Two closes → one return → below MIN_OBS_VOLATILITY; unavailable."""
        result = calc_realized_volatility_5d(_ohlcv([100.0, 105.0]))
        # Only 1 return, MIN_OBS_VOLATILITY=2 → unavailable
        self.assertFalse(result.available)

    def test_three_closes_available(self):
        """Three closes → two returns → available."""
        result = calc_realized_volatility_5d(_ohlcv([100.0, 110.0, 90.0]))
        self.assertTrue(result.available)

    def test_annualized_unit(self):
        result = calc_realized_volatility_5d(_ohlcv([100.0, 110.0, 90.0, 105.0]))
        self.assertEqual(result.unit, "annualized_%")

    def test_known_computation(self):
        """
        Hand-calculated: closes=[100, 110, 99]
        returns: [0.10, (99-110)/110] = [0.10, -0.10]
        mean = 0.0; variance = (0.01 + 0.01)/2 = 0.01; std=0.1
        vol_ann = 0.1 * sqrt(252) ≈ 1.587 → 158.7%
        """
        result = calc_realized_volatility_5d(_ohlcv([100.0, 110.0, 99.0]))
        self.assertTrue(result.available)
        expected_pct = 0.1 * math.sqrt(252) * 100
        self.assertAlmostEqual(result.value, expected_pct, places=2)


# ── 4. Price range ─────────────────────────────────────────────────────────────

class TestPriceRange(unittest.TestCase):
    def test_known_value(self):
        """min=90, max=110: range = 20/90*100 ≈ 22.22%."""
        result = calc_5d_price_range_pct(_ohlcv([100.0, 90.0, 110.0, 95.0, 105.0]))
        self.assertTrue(result.available)
        expected = (110.0 - 90.0) / 90.0 * 100.0
        self.assertAlmostEqual(result.value, expected, places=4)

    def test_constant_prices_zero_range(self):
        result = calc_5d_price_range_pct(_ohlcv([100.0, 100.0, 100.0]))
        self.assertTrue(result.available)
        self.assertAlmostEqual(result.value, 0.0, places=6)

    def test_insufficient_data(self):
        result = calc_5d_price_range_pct(_ohlcv([100.0]))
        self.assertFalse(result.available)


# ── 5. Average volume ──────────────────────────────────────────────────────────

class TestAvgVolume(unittest.TestCase):
    def test_known_value(self):
        ohlcv = _ohlcv([100.0, 110.0], volumes=[1_000_000, 2_000_000])
        result = calc_avg_volume_5d(ohlcv)
        self.assertTrue(result.available)
        self.assertAlmostEqual(result.value, 1_500_000.0, places=0)

    def test_empty_returns_unavailable(self):
        result = calc_avg_volume_5d([])
        self.assertFalse(result.available)

    def test_zero_volume_included(self):
        """Zero volume is valid and included in mean."""
        ohlcv = _ohlcv([100.0, 110.0, 120.0], volumes=[0, 0, 900_000])
        result = calc_avg_volume_5d(ohlcv)
        self.assertTrue(result.available)
        self.assertAlmostEqual(result.value, 300_000.0, places=0)


# ── 6. Price z-score ───────────────────────────────────────────────────────────

class TestPriceZscore(unittest.TestCase):
    def test_known_value(self):
        """
        closes=[90, 100, 110]: mean=100, std=sqrt(200/3)≈8.165
        current_price=110: z = (110-100)/8.165 ≈ 1.225
        """
        ohlcv = _ohlcv([90.0, 100.0, 110.0])
        result = calc_price_zscore_5d(110.0, ohlcv)
        self.assertTrue(result.available)
        mean_c = 100.0
        var = ((90 - 100) ** 2 + (100 - 100) ** 2 + (110 - 100) ** 2) / 3
        std_c = math.sqrt(var)
        expected_z = (110.0 - mean_c) / std_c
        self.assertAlmostEqual(result.value, expected_z, places=3)

    def test_constant_prices_returns_zero(self):
        """Constant prices → near-zero std → z=0 by convention."""
        result = calc_price_zscore_5d(100.0, _ohlcv([100.0, 100.0, 100.0]))
        self.assertTrue(result.available)
        self.assertAlmostEqual(result.value, 0.0)

    def test_insufficient_data(self):
        result = calc_price_zscore_5d(100.0, _ohlcv([100.0]))
        self.assertFalse(result.available)

    def test_invalid_price(self):
        result = calc_price_zscore_5d(-5.0, _ohlcv([100.0, 110.0, 120.0]))
        self.assertFalse(result.available)


# ── 7. EMA spread ──────────────────────────────────────────────────────────────

class TestEmaSpread(unittest.TestCase):
    def test_known_value(self):
        """EMA20=110, EMA50=100: spread=(110-100)/100*100=+10%."""
        result = calc_ema_spread_pct({"ema20": 110.0, "ema50": 100.0})
        self.assertTrue(result.available)
        self.assertAlmostEqual(result.value, 10.0, places=4)

    def test_negative_spread(self):
        result = calc_ema_spread_pct({"ema20": 90.0, "ema50": 100.0})
        self.assertTrue(result.available)
        self.assertAlmostEqual(result.value, -10.0, places=4)

    def test_missing_ema50(self):
        result = calc_ema_spread_pct({"ema20": 100.0})
        self.assertFalse(result.available)

    def test_zero_ema50(self):
        """Zero EMA50 → cannot compute; unavailable."""
        result = calc_ema_spread_pct({"ema20": 100.0, "ema50": 0.0})
        self.assertFalse(result.available)

    def test_empty_dict(self):
        result = calc_ema_spread_pct({})
        self.assertFalse(result.available)


# ── 8. RSI extremity ───────────────────────────────────────────────────────────

class TestRsiExtremity(unittest.TestCase):
    def test_rsi_50_is_neutral(self):
        """RSI=50 → extremity=0.0 (perfectly neutral)."""
        result = calc_rsi_extremity({"rsi": 50.0})
        self.assertTrue(result.available)
        self.assertAlmostEqual(result.value, 0.0)

    def test_rsi_100_fully_extreme(self):
        """RSI=100 → extremity=1.0."""
        result = calc_rsi_extremity({"rsi": 100.0})
        self.assertTrue(result.available)
        self.assertAlmostEqual(result.value, 1.0)

    def test_rsi_0_fully_extreme(self):
        """RSI=0 → extremity=1.0."""
        result = calc_rsi_extremity({"rsi": 0.0})
        self.assertTrue(result.available)
        self.assertAlmostEqual(result.value, 1.0)

    def test_rsi_70_overbought(self):
        """RSI=70 → extremity=0.40."""
        result = calc_rsi_extremity({"rsi": 70.0})
        self.assertTrue(result.available)
        self.assertAlmostEqual(result.value, 0.40, places=4)

    def test_missing_rsi(self):
        result = calc_rsi_extremity({})
        self.assertFalse(result.available)

    def test_out_of_range_rsi(self):
        """RSI=110 is invalid."""
        result = calc_rsi_extremity({"rsi": 110.0})
        self.assertFalse(result.available)


# ── 9. Trend consistency ───────────────────────────────────────────────────────

class TestTrendConsistency(unittest.TestCase):
    def test_perfectly_up_trending(self):
        """All returns positive → consistency=1.0."""
        result = calc_trend_consistency_5d(_ohlcv([100.0, 102.0, 104.0, 106.0, 108.0]))
        self.assertTrue(result.available)
        self.assertAlmostEqual(result.value, 1.0)

    def test_perfectly_down_trending(self):
        """All returns negative → consistency=1.0."""
        result = calc_trend_consistency_5d(_ohlcv([108.0, 106.0, 104.0, 102.0, 100.0]))
        self.assertTrue(result.available)
        self.assertAlmostEqual(result.value, 1.0)

    def test_alternating_returns(self):
        """Up-down-up with net positive: 2 of 3 returns match direction."""
        result = calc_trend_consistency_5d(_ohlcv([100.0, 110.0, 105.0, 115.0]))
        # returns: +0.10, -0.0454, +0.095 → net>0 → fraction positive = 2/3
        self.assertTrue(result.available)
        self.assertAlmostEqual(result.value, 2.0 / 3.0, places=4)

    def test_insufficient_data(self):
        result = calc_trend_consistency_5d(_ohlcv([100.0]))
        self.assertFalse(result.available)


# ── 10. NaN / Inf guards ──────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):
    def test_nan_close_excluded(self):
        """NaN close values are skipped; non-NaN ones are used."""
        ohlcv = [
            {"date": "2024-01-01", "open": 100, "high": 101, "low": 99, "close": float("nan"), "volume": 1000},
            {"date": "2024-01-02", "open": 105, "high": 106, "low": 104, "close": 105.0, "volume": 1000},
            {"date": "2024-01-03", "open": 110, "high": 111, "low": 109, "close": 110.0, "volume": 1000},
        ]
        result = calc_5d_cumulative_return(ohlcv)
        # Only 2 valid closes: 105, 110 → return = (110-105)/105*100
        self.assertTrue(result.available)
        expected = (110.0 - 105.0) / 105.0 * 100.0
        self.assertAlmostEqual(result.value, expected, places=4)

    def test_negative_close_excluded(self):
        """Negative close is excluded by _extract_closes."""
        ohlcv = [
            {"date": "2024-01-01", "close": -100.0, "volume": 1000},
            {"date": "2024-01-02", "close": 100.0, "volume": 1000},
            {"date": "2024-01-03", "close": 110.0, "volume": 1000},
        ]
        result = calc_5d_cumulative_return(ohlcv)
        self.assertTrue(result.available)
        self.assertAlmostEqual(result.value, 10.0, places=4)

    def test_missing_close_field_excluded(self):
        """Row without 'close' key is skipped."""
        ohlcv = [
            {"date": "2024-01-01", "volume": 1000},
            {"date": "2024-01-02", "close": 100.0, "volume": 1000},
            {"date": "2024-01-03", "close": 110.0, "volume": 1000},
        ]
        result = calc_5d_cumulative_return(ohlcv)
        self.assertTrue(result.available)


# ── 11. New Longer-Term Metrics ───────────────────────────────────────────────

class TestLongTermMetrics(unittest.TestCase):
    def test_20d_metrics_insufficient(self):
        ohlcv = _ohlcv([100.0] * 20)
        # needs 21 closes for 20 returns for vol
        self.assertFalse(calc_realized_volatility_20d(ohlcv).available)
        # needs 20 closes for max drawdown
        self.assertTrue(calc_max_drawdown_20d(ohlcv).available)

    def test_20d_max_drawdown(self):
        # Peak at 100, drops to 80 (20% drawdown)
        closes = [100.0] + [80.0] * 19
        ohlcv = _ohlcv(closes)
        result = calc_max_drawdown_20d(ohlcv)
        self.assertTrue(result.available)
        self.assertAlmostEqual(result.value, -20.0, places=4)

    def test_sharpe_and_sortino_insufficient(self):
        ohlcv = _ohlcv([100.0] * 60)
        # Needs 61 closes for 60 returns
        self.assertFalse(calc_sharpe_ratio_annualized(ohlcv).available)
        self.assertFalse(calc_sortino_ratio_annualized(ohlcv).available)


# ── 12. compute_all_metrics master function ──────────────────────────────────

class TestComputeAllMetrics(unittest.TestCase):
    def test_returns_all_metric_names(self):
        ohlcv = _ohlcv([100.0, 105.0, 102.0, 108.0, 110.0])
        indicators = {"ema20": 104.0, "ema50": 100.0, "rsi": 62.0}
        metrics = compute_all_metrics(110.0, ohlcv, indicators)
        names = {m.metric_name for m in metrics}
        required = {
            "cumulative_return_5d",
            "realized_volatility_5d",
            "price_range_5d_pct",
            "avg_volume_5d",
            "price_zscore_5d",
            "return_mean_5d",
            "trend_consistency_5d",
            "ema_spread_pct",
            "rsi_extremity",
            "realized_volatility_20d",
            "max_drawdown_20d",
            "sharpe_ratio_annualized",
            "sortino_ratio_annualized",
            "rolling_vol_20d",
        }
        self.assertTrue(required.issubset(names))

    def test_numerical_integrity_cumulative_return(self):
        """
        Numerical integrity: compute_all_metrics cumulative_return value
        must match direct calc_5d_cumulative_return for the same input.
        """
        closes = [100.0, 105.0, 102.0, 108.0, 110.0]
        ohlcv = _ohlcv(closes)
        indicators = {"ema20": 104.0, "ema50": 100.0, "rsi": 62.0}

        all_metrics = compute_all_metrics(110.0, ohlcv, indicators)
        direct = calc_5d_cumulative_return(ohlcv)

        master = next(m for m in all_metrics if m.metric_name == "cumulative_return_5d")
        self.assertEqual(master.value, direct.value)

    def test_no_exception_on_empty_context(self):
        """compute_all_metrics must not raise even with empty data."""
        try:
            metrics = compute_all_metrics(100.0, [], {})
            for m in metrics:
                self.assertIsInstance(m.available, bool)
        except Exception as e:
            self.fail(f"compute_all_metrics raised unexpectedly: {e}")


if __name__ == "__main__":
    unittest.main()
