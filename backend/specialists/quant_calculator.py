"""
quant_calculator.py — Phase 3.4

Pure deterministic quantitative calculations.

This module is entirely free of LLM calls, network I/O, and side effects.
Every function:
  - accepts only plain Python data structures (no Pydantic models)
  - returns a typed result with provenance metadata
  - explicitly handles: insufficient data, NaN, Inf, zero denominators
  - documents the mathematical formula used

Data Availability Contract (as of Phase 3.4)
--------------------------------------------
MarketContext provides:
  - ohlcv_historical : last 5 OHLCV rows (list of dicts with keys
      date, open, high, low, close, volume)
  - technical_indicators : scalar dict with ema20, ema50, rsi, 20_day_high
  - current_price : float

Metrics that REQUIRE full history (20-60+ observations) are explicitly
reported as UNAVAILABLE rather than silently degraded.

Mathematical foundations
------------------------
All formulas use population statistics on the available window unless
stated otherwise. Risk-free rate is assumed 0 unless explicitly parameterized.
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Result container ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class QuantMetric:
    """
    A single computed quantitative metric with full provenance.

    Fields
    ------
    metric_name        : Canonical identifier (snake_case)
    value              : Computed float value (None if unavailable)
    unit               : Unit of the value, e.g. "annualized_%", "ratio", "raw"
    window             : Observation window, e.g. "5D", "20D", "N/A"
    available          : False if the metric could not be computed
    unavailable_reason : Human-readable explanation when available=False
    source             : Data source used, e.g. "ohlcv_historical", "technical_indicators"
    calculation_method : One-line formula description
    data_timestamp     : ISO timestamp of the latest observation used
    """
    metric_name: str
    value: Optional[float]
    unit: str
    window: str
    available: bool
    source: str
    calculation_method: str
    data_timestamp: str
    unavailable_reason: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "value": self.value,
            "unit": self.unit,
            "window": self.window,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
            "source": self.source,
            "calculation_method": self.calculation_method,
            "data_timestamp": self.data_timestamp,
        }


def _unavailable(
    name: str,
    unit: str,
    window: str,
    source: str,
    calculation_method: str,
    reason: str,
    data_timestamp: str = "N/A",
) -> QuantMetric:
    """Convenience constructor for an unavailable metric."""
    return QuantMetric(
        metric_name=name,
        value=None,
        unit=unit,
        window=window,
        available=False,
        source=source,
        calculation_method=calculation_method,
        data_timestamp=data_timestamp,
        unavailable_reason=reason,
    )


def _guard_finite(name: str, value: float) -> bool:
    """Return True if value is a usable finite float."""
    return math.isfinite(value)


# ── OHLCV parsing ─────────────────────────────────────────────────────────────

def _extract_closes(ohlcv: List[Dict[str, Any]]) -> List[float]:
    """
    Extract close prices in chronological order, skipping NaN/Inf entries.
    """
    closes: List[float] = []
    for row in ohlcv:
        raw = row.get("close")
        if raw is None:
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(v) and v > 0:
            closes.append(v)
    return closes


def _extract_volumes(ohlcv: List[Dict[str, Any]]) -> List[float]:
    """Extract volume values, skipping NaN/Inf/negative entries."""
    volumes: List[float] = []
    for row in ohlcv:
        raw = row.get("volume")
        if raw is None:
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(v) and v >= 0:
            volumes.append(v)
    return volumes


def _extract_timestamp(ohlcv: List[Dict[str, Any]]) -> str:
    """Return ISO date of the last OHLCV row, or 'N/A'."""
    if not ohlcv:
        return "N/A"
    last = ohlcv[-1]
    return str(last.get("date", "N/A"))


# ── Metric: 5-day cumulative return ─────────────────────────────────────────
# Formula: (close[-1] - close[0]) / close[0]
# Requires: ≥ 2 close observations.

MIN_OBS_RETURN = 2

def calc_5d_cumulative_return(
    ohlcv: List[Dict[str, Any]]
) -> QuantMetric:
    closes = _extract_closes(ohlcv)
    ts = _extract_timestamp(ohlcv)

    if len(closes) < MIN_OBS_RETURN:
        return _unavailable(
            name="cumulative_return_5d",
            unit="%",
            window="5D",
            source="ohlcv_historical",
            calculation_method="(close[-1] - close[0]) / close[0] * 100",
            reason=f"Need ≥{MIN_OBS_RETURN} close observations; got {len(closes)}.",
            data_timestamp=ts,
        )

    first, last = closes[0], closes[-1]
    if first == 0 or not _guard_finite(first, first):
        return _unavailable(
            name="cumulative_return_5d",
            unit="%",
            window="5D",
            source="ohlcv_historical",
            calculation_method="(close[-1] - close[0]) / close[0] * 100",
            reason="First close is zero or non-finite; cannot compute return.",
            data_timestamp=ts,
        )

    ret = (last - first) / first * 100.0
    if not _guard_finite("cumulative_return_5d", ret):
        return _unavailable(
            name="cumulative_return_5d",
            unit="%",
            window="5D",
            source="ohlcv_historical",
            calculation_method="(close[-1] - close[0]) / close[0] * 100",
            reason="Result is non-finite (Inf/NaN).",
            data_timestamp=ts,
        )

    return QuantMetric(
        metric_name="cumulative_return_5d",
        value=round(ret, 4),
        unit="%",
        window="5D",
        available=True,
        source="ohlcv_historical",
        calculation_method="(close[-1] - close[0]) / close[0] * 100",
        data_timestamp=ts,
    )


# ── Metric: Daily returns series ─────────────────────────────────────────────
# Formula: r_t = (close_t - close_{t-1}) / close_{t-1}

def _compute_daily_returns(closes: List[float]) -> List[float]:
    """
    Compute log-simple daily returns.

    Formula: r_t = (P_t - P_{t-1}) / P_{t-1}
    Returns empty list if fewer than 2 closes.
    Skips any step where denominator is zero or non-finite.
    """
    returns: List[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        curr = closes[i]
        if prev == 0 or not _guard_finite("prev_close", prev):
            continue
        r = (curr - prev) / prev
        if _guard_finite("return", r):
            returns.append(r)
    return returns


# ── Metric: 5-day realized volatility ────────────────────────────────────────
# Formula: std(daily_returns) * sqrt(252)  [annualized, using available window]
# Requires: ≥ 2 daily returns (i.e., ≥ 3 closes)
# NOTE: With only 5 OHLCV rows → 4 returns max. This is a SHORT window.
# The annualized figure is statistically unstable over 4 observations.
# We compute it honestly and label it "5D_annualized" so downstream
# consumers understand the limitation.

MIN_OBS_VOLATILITY = 2  # returns, not closes

def calc_realized_volatility_5d(
    ohlcv: List[Dict[str, Any]]
) -> QuantMetric:
    closes = _extract_closes(ohlcv)
    ts = _extract_timestamp(ohlcv)
    source = "ohlcv_historical"
    method = "std(daily_returns) * sqrt(252); window=5D; NOTE: statistically limited"

    if len(closes) < MIN_OBS_VOLATILITY + 1:
        return _unavailable(
            name="realized_volatility_5d",
            unit="annualized_%",
            window="5D",
            source=source,
            calculation_method=method,
            reason=f"Need ≥{MIN_OBS_VOLATILITY + 1} closes; got {len(closes)}.",
            data_timestamp=ts,
        )

    returns = _compute_daily_returns(closes)
    if len(returns) < MIN_OBS_VOLATILITY:
        return _unavailable(
            name="realized_volatility_5d",
            unit="annualized_%",
            window="5D",
            source=source,
            calculation_method=method,
            reason=f"Need ≥{MIN_OBS_VOLATILITY} daily returns; computed {len(returns)}.",
            data_timestamp=ts,
        )

    n = len(returns)
    mean_r = sum(returns) / n
    variance = sum((r - mean_r) ** 2 for r in returns) / n  # population variance
    std_daily = math.sqrt(variance)
    vol_ann = std_daily * math.sqrt(252)

    if not _guard_finite("vol_ann", vol_ann):
        return _unavailable(
            name="realized_volatility_5d",
            unit="annualized_%",
            window="5D",
            source=source,
            calculation_method=method,
            reason="Annualized volatility is non-finite.",
            data_timestamp=ts,
        )

    return QuantMetric(
        metric_name="realized_volatility_5d",
        value=round(vol_ann * 100, 4),   # convert to %
        unit="annualized_%",
        window="5D",
        available=True,
        source=source,
        calculation_method=method,
        data_timestamp=ts,
    )


# ── Metric: 5-day price range (High-Low spread) ───────────────────────────────
# Formula: (max(close) - min(close)) / min(close) * 100
# Requires: ≥ 2 closes

def calc_5d_price_range_pct(
    ohlcv: List[Dict[str, Any]]
) -> QuantMetric:
    closes = _extract_closes(ohlcv)
    ts = _extract_timestamp(ohlcv)
    source = "ohlcv_historical"
    method = "(max(close) - min(close)) / min(close) * 100"

    if len(closes) < 2:
        return _unavailable(
            name="price_range_5d_pct",
            unit="%",
            window="5D",
            source=source,
            calculation_method=method,
            reason=f"Need ≥2 closes; got {len(closes)}.",
            data_timestamp=ts,
        )

    lo = min(closes)
    hi = max(closes)
    if lo <= 0 or not _guard_finite("lo", lo):
        return _unavailable(
            name="price_range_5d_pct",
            unit="%",
            window="5D",
            source=source,
            calculation_method=method,
            reason="Min close is non-positive; cannot compute range %.",
            data_timestamp=ts,
        )

    rng = (hi - lo) / lo * 100.0
    return QuantMetric(
        metric_name="price_range_5d_pct",
        value=round(rng, 4),
        unit="%",
        window="5D",
        available=True,
        source=source,
        calculation_method=method,
        data_timestamp=ts,
    )


# ── Metric: 5-day average daily volume ───────────────────────────────────────
# Formula: mean(volume_series)
# Requires: ≥ 1 volume observation

def calc_avg_volume_5d(
    ohlcv: List[Dict[str, Any]]
) -> QuantMetric:
    volumes = _extract_volumes(ohlcv)
    ts = _extract_timestamp(ohlcv)
    source = "ohlcv_historical"
    method = "mean(volume) over available window"

    if not volumes:
        return _unavailable(
            name="avg_volume_5d",
            unit="shares",
            window="5D",
            source=source,
            calculation_method=method,
            reason="No valid volume observations found.",
            data_timestamp=ts,
        )

    avg_vol = sum(volumes) / len(volumes)
    return QuantMetric(
        metric_name="avg_volume_5d",
        value=round(avg_vol, 0),
        unit="shares",
        window="5D",
        available=True,
        source=source,
        calculation_method=method,
        data_timestamp=ts,
    )


# ── Metric: Price z-score relative to 5-day rolling window ───────────────────
# Formula: (current_price - mean(closes)) / std(closes)
# Requires: ≥ 2 closes to compute std

def calc_price_zscore_5d(
    current_price: float,
    ohlcv: List[Dict[str, Any]]
) -> QuantMetric:
    closes = _extract_closes(ohlcv)
    ts = _extract_timestamp(ohlcv)
    source = "ohlcv_historical + current_price"
    method = "(current_price - mean(5d_closes)) / std(5d_closes)"

    if len(closes) < 2:
        return _unavailable(
            name="price_zscore_5d",
            unit="sigma",
            window="5D",
            source=source,
            calculation_method=method,
            reason=f"Need ≥2 closes for z-score; got {len(closes)}.",
            data_timestamp=ts,
        )

    if not (_guard_finite("current_price", current_price) and current_price > 0):
        return _unavailable(
            name="price_zscore_5d",
            unit="sigma",
            window="5D",
            source=source,
            calculation_method=method,
            reason=f"Invalid current_price={current_price}.",
            data_timestamp=ts,
        )

    n = len(closes)
    mean_c = sum(closes) / n
    variance = sum((c - mean_c) ** 2 for c in closes) / n
    std_c = math.sqrt(variance)

    if std_c < 1e-10:
        # Constant prices → zero variance → z-score undefined (or zero by convention)
        return QuantMetric(
            metric_name="price_zscore_5d",
            value=0.0,
            unit="sigma",
            window="5D",
            available=True,
            source=source,
            calculation_method=method,
            data_timestamp=ts,
            unavailable_reason="Near-zero price variance: z-score set to 0.",
        )

    z = (current_price - mean_c) / std_c
    if not _guard_finite("zscore", z):
        return _unavailable(
            name="price_zscore_5d",
            unit="sigma",
            window="5D",
            source=source,
            calculation_method=method,
            reason="Z-score result is non-finite.",
            data_timestamp=ts,
        )

    return QuantMetric(
        metric_name="price_zscore_5d",
        value=round(z, 4),
        unit="sigma",
        window="5D",
        available=True,
        source=source,
        calculation_method=method,
        data_timestamp=ts,
    )


# ── Metric: EMA spread z-score (from technical_indicators) ───────────────────
# Formula: (ema20 - ema50) / ema50 * 100
# Requires: ema20 and ema50 present and positive

def calc_ema_spread_pct(
    technical_indicators: Dict[str, Any]
) -> QuantMetric:
    source = "technical_indicators"
    method = "(ema20 - ema50) / ema50 * 100"

    ema20_raw = technical_indicators.get("ema20")
    ema50_raw = technical_indicators.get("ema50")

    if ema20_raw is None or ema50_raw is None:
        return _unavailable(
            name="ema_spread_pct",
            unit="%",
            window="N/A",
            source=source,
            calculation_method=method,
            reason="EMA20 or EMA50 not present in technical_indicators.",
        )

    try:
        ema20 = float(ema20_raw)
        ema50 = float(ema50_raw)
    except (TypeError, ValueError) as e:
        return _unavailable(
            name="ema_spread_pct",
            unit="%",
            window="N/A",
            source=source,
            calculation_method=method,
            reason=f"Non-numeric EMA values: {e}",
        )

    if not (_guard_finite("ema20", ema20) and _guard_finite("ema50", ema50)):
        return _unavailable(
            name="ema_spread_pct",
            unit="%",
            window="N/A",
            source=source,
            calculation_method=method,
            reason="EMA values are non-finite.",
        )

    if ema50 <= 0:
        return _unavailable(
            name="ema_spread_pct",
            unit="%",
            window="N/A",
            source=source,
            calculation_method=method,
            reason=f"EMA50={ema50} is non-positive; cannot compute spread.",
        )

    spread = (ema20 - ema50) / ema50 * 100.0
    return QuantMetric(
        metric_name="ema_spread_pct",
        value=round(spread, 4),
        unit="%",
        window="N/A",
        available=True,
        source=source,
        calculation_method=method,
        data_timestamp="N/A",
    )


# ── Metric: RSI extremity score ──────────────────────────────────────────────
# Formula: |RSI - 50| / 50  (normalized 0→1; higher = more extreme)
# Requires: rsi present in [0, 100]

def calc_rsi_extremity(
    technical_indicators: Dict[str, Any]
) -> QuantMetric:
    source = "technical_indicators"
    method = "abs(rsi - 50) / 50  [normalized extremity: 0=neutral, 1=fully extreme]"

    rsi_raw = technical_indicators.get("rsi")
    if rsi_raw is None:
        return _unavailable(
            name="rsi_extremity",
            unit="ratio",
            window="N/A",
            source=source,
            calculation_method=method,
            reason="RSI not present in technical_indicators.",
        )

    try:
        rsi = float(rsi_raw)
    except (TypeError, ValueError) as e:
        return _unavailable(
            name="rsi_extremity",
            unit="ratio",
            window="N/A",
            source=source,
            calculation_method=method,
            reason=f"Non-numeric RSI value: {e}",
        )

    if not _guard_finite("rsi", rsi):
        return _unavailable(
            name="rsi_extremity",
            unit="ratio",
            window="N/A",
            source=source,
            calculation_method=method,
            reason="RSI is non-finite.",
        )

    if not (0.0 <= rsi <= 100.0):
        return _unavailable(
            name="rsi_extremity",
            unit="ratio",
            window="N/A",
            source=source,
            calculation_method=method,
            reason=f"RSI={rsi} is out of valid range [0, 100].",
        )

    extremity = abs(rsi - 50.0) / 50.0
    return QuantMetric(
        metric_name="rsi_extremity",
        value=round(extremity, 4),
        unit="ratio",
        window="N/A",
        available=True,
        source=source,
        calculation_method=method,
        data_timestamp="N/A",
    )


# ── Metric: Return mean (5-day) ────────────────────────────────────────────
# Formula: mean(daily_returns)
# Requires: ≥ 2 returns

def calc_return_mean_5d(
    ohlcv: List[Dict[str, Any]]
) -> QuantMetric:
    closes = _extract_closes(ohlcv)
    ts = _extract_timestamp(ohlcv)
    source = "ohlcv_historical"
    method = "mean(daily_returns); r_t = (P_t - P_{t-1}) / P_{t-1}"

    if len(closes) < 2:
        return _unavailable(
            name="return_mean_5d",
            unit="%",
            window="5D",
            source=source,
            calculation_method=method,
            reason=f"Need ≥2 closes; got {len(closes)}.",
            data_timestamp=ts,
        )

    returns = _compute_daily_returns(closes)
    if len(returns) < 1:
        return _unavailable(
            name="return_mean_5d",
            unit="%",
            window="5D",
            source=source,
            calculation_method=method,
            reason="No valid daily returns computed.",
            data_timestamp=ts,
        )

    mean_r = sum(returns) / len(returns) * 100.0
    if not _guard_finite("mean_r", mean_r):
        return _unavailable(
            name="return_mean_5d",
            unit="%",
            window="5D",
            source=source,
            calculation_method=method,
            reason="Mean return is non-finite.",
            data_timestamp=ts,
        )

    return QuantMetric(
        metric_name="return_mean_5d",
        value=round(mean_r, 4),
        unit="%",
        window="5D",
        available=True,
        source=source,
        calculation_method=method,
        data_timestamp=ts,
    )


# ── Metric: 20-day realized volatility ───────────────────────────────────────
def calc_realized_volatility_20d(ohlcv: List[Dict[str, Any]]) -> QuantMetric:
    closes = _extract_closes(ohlcv)
    # Use only last 21 closes to get 20 returns
    closes = closes[-21:] if len(closes) > 21 else closes
    ts = _extract_timestamp(ohlcv)
    source = "ohlcv_historical"
    method = "std(daily_returns) * sqrt(252)"

    if len(closes) < 21:
        return _unavailable(
            name="realized_volatility_20d",
            unit="annualized_%",
            window="20D",
            source=source,
            calculation_method=method,
            reason=f"Need ≥21 closes; got {len(closes)}.",
            data_timestamp=ts,
        )

    returns = _compute_daily_returns(closes)
    n = len(returns)
    mean_r = sum(returns) / n
    variance = sum((r - mean_r) ** 2 for r in returns) / n
    vol_ann = math.sqrt(variance) * math.sqrt(252)

    return QuantMetric(
        metric_name="realized_volatility_20d",
        value=round(vol_ann * 100, 4),
        unit="annualized_%",
        window="20D",
        available=True,
        source=source,
        calculation_method=method,
        data_timestamp=ts,
    )

# ── Metric: 20-day maximum drawdown ──────────────────────────────────────────
def calc_max_drawdown_20d(ohlcv: List[Dict[str, Any]]) -> QuantMetric:
    closes = _extract_closes(ohlcv)
    closes = closes[-20:] if len(closes) > 20 else closes
    ts = _extract_timestamp(ohlcv)
    source = "ohlcv_historical"
    method = "min((P_t - max(P_0..P_t)) / max(P_0..P_t))"

    if len(closes) < 20:
        return _unavailable(
            name="max_drawdown_20d",
            unit="%",
            window="20D",
            source=source,
            calculation_method=method,
            reason=f"Need ≥20 closes; got {len(closes)}.",
            data_timestamp=ts,
        )

    max_dd = 0.0
    peak = closes[0]
    for p in closes:
        if p > peak:
            peak = p
        dd = (p - peak) / peak
        if dd < max_dd:
            max_dd = dd

    return QuantMetric(
        metric_name="max_drawdown_20d",
        value=round(max_dd * 100, 4),
        unit="%",
        window="20D",
        available=True,
        source=source,
        calculation_method=method,
        data_timestamp=ts,
    )

# ── Metric: Annualized Sharpe Ratio (60D window) ─────────────────────────────
def calc_sharpe_ratio_annualized(ohlcv: List[Dict[str, Any]]) -> QuantMetric:
    closes = _extract_closes(ohlcv)
    closes = closes[-61:] if len(closes) > 61 else closes
    ts = _extract_timestamp(ohlcv)
    source = "ohlcv_historical"
    method = "(mean_daily_return - Rf) / std_daily_return * sqrt(252)"

    if len(closes) < 61:
        return _unavailable(
            name="sharpe_ratio_annualized",
            unit="ratio",
            window="60D",
            source=source,
            calculation_method=method,
            reason=f"Need ≥61 closes; got {len(closes)}.",
            data_timestamp=ts,
        )

    returns = _compute_daily_returns(closes)
    n = len(returns)
    mean_r = sum(returns) / n
    variance = sum((r - mean_r) ** 2 for r in returns) / n
    std_r = math.sqrt(variance)
    
    if std_r == 0:
        sharpe = 0.0
    else:
        sharpe = (mean_r / std_r) * math.sqrt(252)

    return QuantMetric(
        metric_name="sharpe_ratio_annualized",
        value=round(sharpe, 4),
        unit="ratio",
        window="60D",
        available=True,
        source=source,
        calculation_method=method,
        data_timestamp=ts,
    )

# ── Metric: Annualized Sortino Ratio (60D window) ────────────────────────────
def calc_sortino_ratio_annualized(ohlcv: List[Dict[str, Any]]) -> QuantMetric:
    closes = _extract_closes(ohlcv)
    closes = closes[-61:] if len(closes) > 61 else closes
    ts = _extract_timestamp(ohlcv)
    source = "ohlcv_historical"
    method = "mean_excess_return / downside_std * sqrt(252)"

    if len(closes) < 61:
        return _unavailable(
            name="sortino_ratio_annualized",
            unit="ratio",
            window="60D",
            source=source,
            calculation_method=method,
            reason=f"Need ≥61 closes; got {len(closes)}.",
            data_timestamp=ts,
        )

    returns = _compute_daily_returns(closes)
    n = len(returns)
    mean_r = sum(returns) / n
    
    downside_returns = [r for r in returns if r < 0]
    if not downside_returns:
        sortino = 0.0
    else:
        downside_variance = sum(r ** 2 for r in downside_returns) / n
        downside_std = math.sqrt(downside_variance)
        if downside_std == 0:
            sortino = 0.0
        else:
            sortino = (mean_r / downside_std) * math.sqrt(252)

    return QuantMetric(
        metric_name="sortino_ratio_annualized",
        value=round(sortino, 4),
        unit="ratio",
        window="60D",
        available=True,
        source=source,
        calculation_method=method,
        data_timestamp=ts,
    )

# ── Metric: 20-day Rolling Volatility ────────────────────────────────────────
def calc_rolling_vol_20d(ohlcv: List[Dict[str, Any]]) -> QuantMetric:
    # Just returning the current 20d realized vol as the latest rolling value
    metric = calc_realized_volatility_20d(ohlcv)
    if not metric.available:
        return _unavailable(
            name="rolling_vol_20d",
            unit="annualized_%",
            window="20D",
            source="ohlcv_historical",
            calculation_method="20D rolling std(returns) * sqrt(252)",
            reason=metric.unavailable_reason,
            data_timestamp=metric.data_timestamp,
        )
    return QuantMetric(
        metric_name="rolling_vol_20d",
        value=metric.value,
        unit="annualized_%",
        window="20D",
        available=True,
        source="ohlcv_historical",
        calculation_method="20D rolling std(returns) * sqrt(252)",
        data_timestamp=metric.data_timestamp,
    )


# ── Trend consistency score ───────────────────────────────────────────────────
# Formula: fraction of daily returns that agree with the net direction
# Requires: ≥ 2 returns

def calc_trend_consistency_5d(
    ohlcv: List[Dict[str, Any]]
) -> QuantMetric:
    closes = _extract_closes(ohlcv)
    ts = _extract_timestamp(ohlcv)
    source = "ohlcv_historical"
    method = "fraction_of_returns_agreeing_with_net_direction"

    if len(closes) < 2:
        return _unavailable(
            name="trend_consistency_5d",
            unit="ratio",
            window="5D",
            source=source,
            calculation_method=method,
            reason=f"Need ≥2 closes; got {len(closes)}.",
            data_timestamp=ts,
        )

    returns = _compute_daily_returns(closes)
    if not returns:
        return _unavailable(
            name="trend_consistency_5d",
            unit="ratio",
            window="5D",
            source=source,
            calculation_method=method,
            reason="No valid daily returns computed.",
            data_timestamp=ts,
        )

    net = sum(returns)
    if net == 0:
        # Perfectly flat — zero consistency by convention
        consistency = 0.0
    elif net > 0:
        consistency = sum(1 for r in returns if r > 0) / len(returns)
    else:
        consistency = sum(1 for r in returns if r < 0) / len(returns)

    return QuantMetric(
        metric_name="trend_consistency_5d",
        value=round(consistency, 4),
        unit="ratio",
        window="5D",
        available=True,
        source=source,
        calculation_method=method,
        data_timestamp=ts,
    )


# ── Master calculation runner ──────────────────────────────────────────────────

def compute_all_metrics(
    current_price: float,
    ohlcv: List[Dict[str, Any]],
    technical_indicators: Dict[str, Any],
) -> List[QuantMetric]:
    """
    Entry point: compute all available quantitative metrics from MarketContext data.

    This function is the sole point of contact between the specialist and
    the calculator. It does not raise; all failures are returned as
    unavailable QuantMetrics.
    """
    ts = _extract_timestamp(ohlcv)
    metrics: List[QuantMetric] = []

    # OHLCV-derived metrics
    metrics.append(calc_5d_cumulative_return(ohlcv))
    metrics.append(calc_realized_volatility_5d(ohlcv))
    metrics.append(calc_5d_price_range_pct(ohlcv))
    metrics.append(calc_avg_volume_5d(ohlcv))
    metrics.append(calc_price_zscore_5d(current_price, ohlcv))
    metrics.append(calc_return_mean_5d(ohlcv))
    metrics.append(calc_trend_consistency_5d(ohlcv))

    # Technical-indicator-derived metrics
    metrics.append(calc_ema_spread_pct(technical_indicators))
    metrics.append(calc_rsi_extremity(technical_indicators))

    # Long-horizon metrics
    metrics.append(calc_realized_volatility_20d(ohlcv))
    metrics.append(calc_max_drawdown_20d(ohlcv))
    metrics.append(calc_sharpe_ratio_annualized(ohlcv))
    metrics.append(calc_sortino_ratio_annualized(ohlcv))
    metrics.append(calc_rolling_vol_20d(ohlcv))

    return metrics
