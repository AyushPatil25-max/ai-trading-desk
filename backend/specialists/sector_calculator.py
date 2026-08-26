"""
sector_calculator.py — Phase 3.7

Pure Python deterministic sector and relative performance calculator.
Zero external network calls, zero LLM dependency, zero yfinance.

Responsibilities
----------------
- Compute point-in-time and windowed return metrics:
  - Company return (%)
  - Sector return (%)
  - Benchmark return (%)
- Compute relative performance spreads:
  - Relative performance vs Sector (% points) = Company Return - Sector Return
  - Relative performance vs Benchmark (% points) = Company Return - Benchmark Return
  - Sector vs Benchmark spread (% points) = Sector Return - Benchmark Return
- Extract sector & industry metadata (sector, industry, benchmark symbol).
- Enforce strict mathematical guards: zero prices, negative base prices, NaN/Inf,
  empty or short OHLCV series.
- Track complete provenance: metric name, value, unit, period, source,
  calculation method, inputs, assumptions, context_id, data_timestamp.
- Handle missing inputs transparently with explicit unavailable_reason strings.
- NEVER invent, estimate, or hallucinate any value.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class SectorMetric:
    """
    In-memory representation of a single computed or unavailable sector metric.
    Maps directly to SectorMetricRecord schema in domain/schemas.py.
    """
    metric_name: str
    value: Optional[float]
    unit: str
    period: str
    source: str
    calculation_method: str
    inputs: Dict[str, Any]
    available: bool
    unavailable_reason: str
    context_id: str
    data_timestamp: str


def _clean_number(val: Any) -> Optional[float]:
    """Convert input to float, rejecting None, NaN, and Inf."""
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def _format_timestamp(ts: Optional[datetime]) -> str:
    """Format datetime to ISO string. Falls back to current UTC time."""
    if ts is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(ts, datetime):
        return ts.isoformat()
    return str(ts)


def _unavailable(
    metric_name: str,
    unit: str,
    period: str,
    source: str,
    method: str,
    reason: str,
    context_id: str,
    data_timestamp: str,
    inputs: Optional[Dict[str, Any]] = None,
) -> SectorMetric:
    """Construct a consistently-structured unavailable SectorMetric."""
    return SectorMetric(
        metric_name=metric_name,
        value=None,
        unit=unit,
        period=period,
        source=source,
        calculation_method=method,
        inputs=inputs or {},
        available=False,
        unavailable_reason=reason,
        context_id=context_id,
        data_timestamp=data_timestamp,
    )


# ── 1. Company Return Calculation ───────────────────────────────────────────

def calc_company_return(
    ohlcv_historical: List[Dict[str, Any]],
    context_id: str,
    data_timestamp: Optional[datetime] = None,
    period: str = "RECENT",
) -> SectorMetric:
    """
    Calculate company return over the supplied OHLCV window.
    Formula: ((last_close - first_close) / first_close) * 100

    Guards:
    - At least 2 OHLCV rows required.
    - First close must be positive.
    - Close prices must be valid numbers (not NaN/Inf).
    """
    ts = _format_timestamp(data_timestamp)
    metric_name = "company_return"
    unit = "%"
    source = "ohlcv_historical"
    method = "((last_close - first_close) / first_close) * 100"

    if not ohlcv_historical or len(ohlcv_historical) < 2:
        return _unavailable(
            metric_name, unit, period, source, method,
            reason=f"Insufficient OHLCV history: {len(ohlcv_historical) if ohlcv_historical else 0} row(s) (minimum 2 required)",
            context_id=context_id, data_timestamp=ts,
            inputs={"rows_count": len(ohlcv_historical) if ohlcv_historical else 0},
        )

    first_close = _clean_number(ohlcv_historical[0].get("close"))
    last_close = _clean_number(ohlcv_historical[-1].get("close"))

    if first_close is None:
        return _unavailable(
            metric_name, unit, period, source, method,
            reason="first_close is missing or non-numeric in ohlcv_historical",
            context_id=context_id, data_timestamp=ts,
            inputs={"first_close": None, "last_close": last_close},
        )
    if last_close is None:
        return _unavailable(
            metric_name, unit, period, source, method,
            reason="last_close is missing or non-numeric in ohlcv_historical",
            context_id=context_id, data_timestamp=ts,
            inputs={"first_close": first_close, "last_close": None},
        )
    if first_close <= 0:
        return _unavailable(
            metric_name, unit, period, source, method,
            reason=f"first_close={first_close} is non-positive — division by zero / meaningless return",
            context_id=context_id, data_timestamp=ts,
            inputs={"first_close": first_close, "last_close": last_close},
        )

    ret = ((last_close - first_close) / first_close) * 100.0
    return SectorMetric(
        metric_name=metric_name,
        value=round(ret, 4),
        unit=unit,
        period=period,
        source=source,
        calculation_method=method,
        inputs={"first_close": first_close, "last_close": last_close, "rows": len(ohlcv_historical)},
        available=True,
        unavailable_reason="",
        context_id=context_id,
        data_timestamp=ts,
    )


# ── 2. Sector Return ─────────────────────────────────────────────────────────

def calc_sector_return(
    sector_data: Dict[str, Any],
    context_id: str,
    data_timestamp: Optional[datetime] = None,
    period: str = "RECENT",
) -> SectorMetric:
    """
    Extract sector return from sector_data.
    """
    ts = _format_timestamp(data_timestamp)
    metric_name = "sector_return"
    unit = "%"
    source = "sector_data"
    method = "Extracted from sector_data['sector_return_pct']"

    sec_ret = _clean_number(sector_data.get("sector_return_pct"))
    sector_name = sector_data.get("sector", "UNKNOWN")

    if sec_ret is None:
        return _unavailable(
            metric_name, unit, period, source, method,
            reason="sector_return_pct is missing or non-numeric in sector_data",
            context_id=context_id, data_timestamp=ts,
            inputs={"sector": sector_name},
        )

    return SectorMetric(
        metric_name=metric_name,
        value=round(sec_ret, 4),
        unit=unit,
        period=period,
        source=source,
        calculation_method=method,
        inputs={"sector": sector_name, "sector_return_pct": sec_ret},
        available=True,
        unavailable_reason="",
        context_id=context_id,
        data_timestamp=ts,
    )


# ── 3. Benchmark Return ──────────────────────────────────────────────────────

def calc_benchmark_return(
    sector_data: Dict[str, Any],
    context_id: str,
    data_timestamp: Optional[datetime] = None,
    period: str = "RECENT",
) -> SectorMetric:
    """
    Extract broad market benchmark return from sector_data.
    """
    ts = _format_timestamp(data_timestamp)
    metric_name = "benchmark_return"
    unit = "%"
    source = "sector_data"
    method = "Extracted from sector_data['benchmark_return_pct']"

    bm_ret = _clean_number(sector_data.get("benchmark_return_pct"))
    benchmark_symbol = sector_data.get("benchmark_symbol", "BENCHMARK")

    if bm_ret is None:
        return _unavailable(
            metric_name, unit, period, source, method,
            reason="benchmark_return_pct is missing or non-numeric in sector_data",
            context_id=context_id, data_timestamp=ts,
            inputs={"benchmark_symbol": benchmark_symbol},
        )

    return SectorMetric(
        metric_name=metric_name,
        value=round(bm_ret, 4),
        unit=unit,
        period=period,
        source=source,
        calculation_method=method,
        inputs={"benchmark_symbol": benchmark_symbol, "benchmark_return_pct": bm_ret},
        available=True,
        unavailable_reason="",
        context_id=context_id,
        data_timestamp=ts,
    )


# ── 4. Relative Performance Spreads ──────────────────────────────────────────

def calc_relative_to_sector(
    company_metric: SectorMetric,
    sector_metric: SectorMetric,
    context_id: str,
    data_timestamp: Optional[datetime] = None,
    period: str = "RECENT",
) -> SectorMetric:
    """
    Relative performance vs Sector (% points) = Company Return - Sector Return
    """
    ts = _format_timestamp(data_timestamp)
    metric_name = "relative_to_sector"
    unit = "%"
    source = "calculated"
    method = "company_return - sector_return"

    if not company_metric.available:
        return _unavailable(
            metric_name, unit, period, source, method,
            reason=f"company_return unavailable: {company_metric.unavailable_reason}",
            context_id=context_id, data_timestamp=ts,
        )
    if not sector_metric.available:
        return _unavailable(
            metric_name, unit, period, source, method,
            reason=f"sector_return unavailable: {sector_metric.unavailable_reason}",
            context_id=context_id, data_timestamp=ts,
        )

    spread = company_metric.value - sector_metric.value
    return SectorMetric(
        metric_name=metric_name,
        value=round(spread, 4),
        unit=unit,
        period=period,
        source=source,
        calculation_method=method,
        inputs={"company_return": company_metric.value, "sector_return": sector_metric.value},
        available=True,
        unavailable_reason="",
        context_id=context_id,
        data_timestamp=ts,
    )


def calc_relative_to_benchmark(
    company_metric: SectorMetric,
    benchmark_metric: SectorMetric,
    context_id: str,
    data_timestamp: Optional[datetime] = None,
    period: str = "RECENT",
) -> SectorMetric:
    """
    Relative performance vs Benchmark (% points) = Company Return - Benchmark Return
    """
    ts = _format_timestamp(data_timestamp)
    metric_name = "relative_to_benchmark"
    unit = "%"
    source = "calculated"
    method = "company_return - benchmark_return"

    if not company_metric.available:
        return _unavailable(
            metric_name, unit, period, source, method,
            reason=f"company_return unavailable: {company_metric.unavailable_reason}",
            context_id=context_id, data_timestamp=ts,
        )
    if not benchmark_metric.available:
        return _unavailable(
            metric_name, unit, period, source, method,
            reason=f"benchmark_return unavailable: {benchmark_metric.unavailable_reason}",
            context_id=context_id, data_timestamp=ts,
        )

    spread = company_metric.value - benchmark_metric.value
    return SectorMetric(
        metric_name=metric_name,
        value=round(spread, 4),
        unit=unit,
        period=period,
        source=source,
        calculation_method=method,
        inputs={"company_return": company_metric.value, "benchmark_return": benchmark_metric.value},
        available=True,
        unavailable_reason="",
        context_id=context_id,
        data_timestamp=ts,
    )


def calc_sector_to_benchmark_spread(
    sector_metric: SectorMetric,
    benchmark_metric: SectorMetric,
    context_id: str,
    data_timestamp: Optional[datetime] = None,
    period: str = "RECENT",
) -> SectorMetric:
    """
    Sector vs Benchmark Spread (% points) = Sector Return - Benchmark Return
    """
    ts = _format_timestamp(data_timestamp)
    metric_name = "sector_to_benchmark_spread"
    unit = "%"
    source = "calculated"
    method = "sector_return - benchmark_return"

    if not sector_metric.available:
        return _unavailable(
            metric_name, unit, period, source, method,
            reason=f"sector_return unavailable: {sector_metric.unavailable_reason}",
            context_id=context_id, data_timestamp=ts,
        )
    if not benchmark_metric.available:
        return _unavailable(
            metric_name, unit, period, source, method,
            reason=f"benchmark_return unavailable: {benchmark_metric.unavailable_reason}",
            context_id=context_id, data_timestamp=ts,
        )

    spread = sector_metric.value - benchmark_metric.value
    return SectorMetric(
        metric_name=metric_name,
        value=round(spread, 4),
        unit=unit,
        period=period,
        source=source,
        calculation_method=method,
        inputs={"sector_return": sector_metric.value, "benchmark_return": benchmark_metric.value},
        available=True,
        unavailable_reason="",
        context_id=context_id,
        data_timestamp=ts,
    )


# ── 5. Master Runner ─────────────────────────────────────────────────────────

def compute_all_sector_metrics(
    sector_data: Dict[str, Any],
    ohlcv_historical: List[Dict[str, Any]],
    context_id: str,
    data_timestamp: Optional[datetime] = None,
    period: str = "RECENT",
) -> List[SectorMetric]:
    """
    Compute all deterministic sector performance metrics and relative spreads.

    Order returned:
    1. company_return
    2. sector_return
    3. benchmark_return
    4. relative_to_sector
    5. relative_to_benchmark
    6. sector_to_benchmark_spread
    """
    comp_m = calc_company_return(
        ohlcv_historical=ohlcv_historical,
        context_id=context_id,
        data_timestamp=data_timestamp,
        period=period,
    )
    sec_m = calc_sector_return(
        sector_data=sector_data,
        context_id=context_id,
        data_timestamp=data_timestamp,
        period=period,
    )
    bm_m = calc_benchmark_return(
        sector_data=sector_data,
        context_id=context_id,
        data_timestamp=data_timestamp,
        period=period,
    )
    rel_sec_m = calc_relative_to_sector(
        company_metric=comp_m,
        sector_metric=sec_m,
        context_id=context_id,
        data_timestamp=data_timestamp,
        period=period,
    )
    rel_bm_m = calc_relative_to_benchmark(
        company_metric=comp_m,
        benchmark_metric=bm_m,
        context_id=context_id,
        data_timestamp=data_timestamp,
        period=period,
    )
    sec_bm_m = calc_sector_to_benchmark_spread(
        sector_metric=sec_m,
        benchmark_metric=bm_m,
        context_id=context_id,
        data_timestamp=data_timestamp,
        period=period,
    )

    return [comp_m, sec_m, bm_m, rel_sec_m, rel_bm_m, sec_bm_m]


def extract_sector_metadata(sector_data: Dict[str, Any]) -> Tuple[str, str, str]:
    """
    Extract categorical sector metadata: (sector, industry, benchmark_symbol).
    Defaults to 'UNKNOWN' or 'N/A' if missing.
    """
    sector = str(sector_data.get("sector") or "UNKNOWN")
    industry = str(sector_data.get("industry") or "UNKNOWN")
    benchmark = str(sector_data.get("benchmark_symbol") or "N/A")
    return sector, industry, benchmark
