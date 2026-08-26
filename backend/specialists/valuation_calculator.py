"""
valuation_calculator.py — Phase 3.6

Pure Python deterministic valuation calculator.
Zero external network calls, zero LLM dependency, zero yfinance.

Responsibilities
----------------
- Compute relative valuation multiples: P/E, P/S, P/B, EV/EBITDA, PEG
- Compute absolute yield measures: FCF Yield
- Enforce strict mathematical guards: EPS=0, EPS<0, NaN, Inf, division-by-zero,
  negative denominators where applicable.
- Track complete provenance for each metric: method name, formula, inputs used,
  assumptions, result, context_id, data_timestamp.
- Handle missing inputs transparently with explicit unavailable_reason strings.
- NEVER invent, estimate, or hallucinate any value.

Data availability (Phase 3.6 baseline)
---------------------------------------
AVAILABLE when fundamental_data is supplied:
  - P/E Ratio         [current_price, eps]
  - P/S Ratio         [current_price, revenue, shares_outstanding]
  - P/B Ratio         [current_price, total_equity, shares_outstanding]
  - EV/EBITDA         [current_price, shares_outstanding, total_debt, cash, ebitda]
  - FCF Yield         [operating_cash_flow, capex, shares_outstanding, current_price]
  - PEG Ratio         [pe_ratio_value, eps, prior_eps] or explicit eps_growth_rate

NOT IMPLEMENTED (documented — requires future providers):
  - DCF (Discounted Cash Flow)   — requires long-range FCF forecast + discount rate + terminal growth;
                                   too many assumptions without a dedicated assumptions provider.
  - Sector P/E comparison        — requires sector reference data provider.
  - EV/Sales                     — available if revenue + shares_outstanding present; omitted for clarity.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class ValuationMetric:
    """
    In-memory representation of a single computed or unavailable valuation metric.
    Maps directly to ValuationMetricRecord schema in domain/schemas.py.
    """
    metric_name: str
    value: Optional[float]
    unit: str                     # "x" for multiples, "%" for yields
    method: str                   # Human-readable valuation method name
    formula: str                  # Exact formula applied
    inputs: Dict[str, Any]        # Named inputs with their exact numeric values
    available: bool
    unavailable_reason: str
    assumptions: List[str]
    context_id: str
    data_timestamp: str


def _clean_number(val: Any) -> Optional[float]:
    """Convert input to float, rejecting None, NaN, and Inf. Unpacks FinancialObservation."""
    if val is None:
        return None
        
    # Handle FinancialObservation (or dict representation)
    if hasattr(val, "value"):
        val = val.value
    elif isinstance(val, dict) and "value" in val:
        val = val["value"]
        
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
    method: str,
    formula: str,
    reason: str,
    context_id: str,
    data_timestamp: str,
    inputs: Optional[Dict[str, Any]] = None,
) -> ValuationMetric:
    """Construct a consistently-structured unavailable ValuationMetric."""
    return ValuationMetric(
        metric_name=metric_name,
        value=None,
        unit=unit,
        method=method,
        formula=formula,
        inputs=inputs or {},
        available=False,
        unavailable_reason=reason,
        assumptions=[],
        context_id=context_id,
        data_timestamp=data_timestamp,
    )


# ── 1. Price-to-Earnings (P/E) ────────────────────────────────────────────────

def calc_pe_ratio(
    data: Dict[str, Any],
    current_price: float,
    context_id: str,
    data_timestamp: Optional[datetime] = None,
) -> ValuationMetric:
    """
    P/E Ratio = Current Price / Earnings Per Share (EPS)

    Guards:
    - EPS must be a valid positive number (negative EPS → P/E is economically meaningless).
    - EPS == 0 → division by zero.
    - Missing EPS → unavailable.
    """
    ts = _format_timestamp(data_timestamp)
    metric_name = "pe_ratio"
    method = "Price-to-Earnings (P/E)"
    formula = "current_price / eps"
    unit = "x"

    eps = _clean_number(data.get("eps"))

    if eps is None:
        return _unavailable(
            metric_name, unit, method, formula,
            reason="eps is missing or non-numeric in fundamental_data",
            context_id=context_id, data_timestamp=ts,
            inputs={"current_price": current_price, "eps": None},
        )
    if eps == 0.0:
        return _unavailable(
            metric_name, unit, method, formula,
            reason="eps == 0 — division by zero; P/E is undefined for zero earnings",
            context_id=context_id, data_timestamp=ts,
            inputs={"current_price": current_price, "eps": eps},
        )
    if eps < 0.0:
        return _unavailable(
            metric_name, unit, method, formula,
            reason=f"eps={eps:.4f} is negative — P/E is economically meaningless for loss-making companies",
            context_id=context_id, data_timestamp=ts,
            inputs={"current_price": current_price, "eps": eps},
        )

    pe = current_price / eps
    return ValuationMetric(
        metric_name=metric_name,
        value=round(pe, 4),
        unit=unit,
        method=method,
        formula=formula,
        inputs={"current_price": current_price, "eps": eps},
        available=True,
        unavailable_reason="",
        assumptions=["EPS represents trailing-twelve-month (TTM) diluted earnings per share"],
        context_id=context_id,
        data_timestamp=ts,
    )


# ── 2. Price-to-Sales (P/S) ───────────────────────────────────────────────────

def calc_ps_ratio(
    data: Dict[str, Any],
    current_price: float,
    context_id: str,
    data_timestamp: Optional[datetime] = None,
) -> ValuationMetric:
    """
    P/S Ratio = Current Price / Revenue Per Share
    Revenue Per Share = Revenue / Shares Outstanding

    Guards:
    - Revenue must be positive.
    - Shares outstanding must be positive.
    """
    ts = _format_timestamp(data_timestamp)
    metric_name = "ps_ratio"
    method = "Price-to-Sales (P/S)"
    formula = "current_price / (revenue / shares_outstanding)"
    unit = "x"

    revenue = _clean_number(data.get("revenue"))
    shares = _clean_number(data.get("shares_outstanding"))

    if revenue is None:
        return _unavailable(
            metric_name, unit, method, formula,
            reason="revenue is missing or non-numeric in fundamental_data",
            context_id=context_id, data_timestamp=ts,
            inputs={"current_price": current_price, "revenue": None, "shares_outstanding": shares},
        )
    if shares is None:
        return _unavailable(
            metric_name, unit, method, formula,
            reason="shares_outstanding is missing or non-numeric in fundamental_data",
            context_id=context_id, data_timestamp=ts,
            inputs={"current_price": current_price, "revenue": revenue, "shares_outstanding": None},
        )
    if shares <= 0:
        return _unavailable(
            metric_name, unit, method, formula,
            reason=f"shares_outstanding={shares:.0f} is non-positive — cannot compute revenue per share",
            context_id=context_id, data_timestamp=ts,
            inputs={"current_price": current_price, "revenue": revenue, "shares_outstanding": shares},
        )
    if revenue <= 0:
        return _unavailable(
            metric_name, unit, method, formula,
            reason=f"revenue={revenue:.2f} is non-positive — P/S is undefined for zero or negative revenue",
            context_id=context_id, data_timestamp=ts,
            inputs={"current_price": current_price, "revenue": revenue, "shares_outstanding": shares},
        )

    revenue_per_share = revenue / shares
    ps = current_price / revenue_per_share
    return ValuationMetric(
        metric_name=metric_name,
        value=round(ps, 4),
        unit=unit,
        method=method,
        formula=formula,
        inputs={"current_price": current_price, "revenue": revenue, "shares_outstanding": shares,
                "revenue_per_share": round(revenue_per_share, 4)},
        available=True,
        unavailable_reason="",
        assumptions=["Revenue represents the most recent annual or TTM figure"],
        context_id=context_id,
        data_timestamp=ts,
    )


# ── 3. Price-to-Book (P/B) ────────────────────────────────────────────────────

def calc_pb_ratio(
    data: Dict[str, Any],
    current_price: float,
    context_id: str,
    data_timestamp: Optional[datetime] = None,
) -> ValuationMetric:
    """
    P/B Ratio = Current Price / Book Value Per Share
    Book Value Per Share = Total Equity / Shares Outstanding

    Guards:
    - Total equity must be positive (negative book value = technically insolvent).
    - Shares outstanding must be positive.
    """
    ts = _format_timestamp(data_timestamp)
    metric_name = "pb_ratio"
    method = "Price-to-Book (P/B)"
    formula = "current_price / (total_equity / shares_outstanding)"
    unit = "x"

    total_equity = _clean_number(data.get("total_equity"))
    shares = _clean_number(data.get("shares_outstanding"))

    if total_equity is None:
        return _unavailable(
            metric_name, unit, method, formula,
            reason="total_equity is missing or non-numeric in fundamental_data",
            context_id=context_id, data_timestamp=ts,
            inputs={"current_price": current_price, "total_equity": None, "shares_outstanding": shares},
        )
    if shares is None:
        return _unavailable(
            metric_name, unit, method, formula,
            reason="shares_outstanding is missing or non-numeric in fundamental_data",
            context_id=context_id, data_timestamp=ts,
            inputs={"current_price": current_price, "total_equity": total_equity, "shares_outstanding": None},
        )
    if shares <= 0:
        return _unavailable(
            metric_name, unit, method, formula,
            reason=f"shares_outstanding={shares:.0f} is non-positive — cannot compute book value per share",
            context_id=context_id, data_timestamp=ts,
            inputs={"current_price": current_price, "total_equity": total_equity, "shares_outstanding": shares},
        )
    if total_equity <= 0:
        return _unavailable(
            metric_name, unit, method, formula,
            reason=(
                f"total_equity={total_equity:.2f} is non-positive — "
                "P/B is economically distorted for negative or zero book value"
            ),
            context_id=context_id, data_timestamp=ts,
            inputs={"current_price": current_price, "total_equity": total_equity, "shares_outstanding": shares},
        )

    bvps = total_equity / shares
    pb = current_price / bvps
    return ValuationMetric(
        metric_name=metric_name,
        value=round(pb, 4),
        unit=unit,
        method=method,
        formula=formula,
        inputs={"current_price": current_price, "total_equity": total_equity,
                "shares_outstanding": shares, "book_value_per_share": round(bvps, 4)},
        available=True,
        unavailable_reason="",
        assumptions=["Book value is derived from balance sheet total equity (shareholders equity)"],
        context_id=context_id,
        data_timestamp=ts,
    )


# ── 4. EV/EBITDA ──────────────────────────────────────────────────────────────

def calc_ev_ebitda(
    data: Dict[str, Any],
    current_price: float,
    context_id: str,
    data_timestamp: Optional[datetime] = None,
) -> ValuationMetric:
    """
    EV/EBITDA = Enterprise Value / EBITDA
    Enterprise Value = Market Cap + Total Debt - Cash
    Market Cap = Current Price × Shares Outstanding

    Guards:
    - EBITDA must be positive (negative EBITDA → EV/EBITDA meaningless).
    - EBITDA == 0 → division by zero.
    - Shares outstanding must be positive.
    """
    ts = _format_timestamp(data_timestamp)
    metric_name = "ev_ebitda"
    method = "EV/EBITDA"
    formula = "(current_price * shares_outstanding + total_debt - cash) / ebitda"
    unit = "x"

    shares = _clean_number(data.get("shares_outstanding"))
    total_debt = _clean_number(data.get("total_debt"))
    cash = _clean_number(data.get("cash"))
    ebitda = _clean_number(data.get("ebitda"))

    if shares is None:
        return _unavailable(
            metric_name, unit, method, formula,
            reason="shares_outstanding is missing or non-numeric in fundamental_data",
            context_id=context_id, data_timestamp=ts,
        )
    if shares <= 0:
        return _unavailable(
            metric_name, unit, method, formula,
            reason=f"shares_outstanding={shares:.0f} is non-positive — cannot compute market cap",
            context_id=context_id, data_timestamp=ts,
        )
    if ebitda is None:
        return _unavailable(
            metric_name, unit, method, formula,
            reason="ebitda is missing or non-numeric in fundamental_data",
            context_id=context_id, data_timestamp=ts,
        )
    if ebitda == 0.0:
        return _unavailable(
            metric_name, unit, method, formula,
            reason="ebitda == 0 — division by zero; EV/EBITDA is undefined",
            context_id=context_id, data_timestamp=ts,
        )
    if ebitda < 0.0:
        return _unavailable(
            metric_name, unit, method, formula,
            reason=f"ebitda={ebitda:.2f} is negative — EV/EBITDA is economically meaningless for negative EBITDA",
            context_id=context_id, data_timestamp=ts,
        )

    # Default missing debt/cash to 0 (conservative, documented as assumption)
    resolved_debt = total_debt if total_debt is not None else 0.0
    resolved_cash = cash if cash is not None else 0.0

    market_cap = current_price * shares
    ev = market_cap + resolved_debt - resolved_cash
    ev_ebitda = ev / ebitda

    assumptions = ["EBITDA represents trailing-twelve-month (TTM) figure"]
    if total_debt is None:
        assumptions.append("total_debt assumed 0.0 (not provided in fundamental_data)")
    if cash is None:
        assumptions.append("cash assumed 0.0 (not provided in fundamental_data)")

    return ValuationMetric(
        metric_name=metric_name,
        value=round(ev_ebitda, 4),
        unit=unit,
        method=method,
        formula=formula,
        inputs={
            "current_price": current_price,
            "shares_outstanding": shares,
            "total_debt": resolved_debt,
            "cash": resolved_cash,
            "ebitda": ebitda,
            "market_cap": round(market_cap, 2),
            "enterprise_value": round(ev, 2),
        },
        available=True,
        unavailable_reason="",
        assumptions=assumptions,
        context_id=context_id,
        data_timestamp=ts,
    )


# ── 5. FCF Yield ──────────────────────────────────────────────────────────────

def calc_fcf_yield(
    data: Dict[str, Any],
    current_price: float,
    context_id: str,
    data_timestamp: Optional[datetime] = None,
) -> ValuationMetric:
    """
    FCF Yield = (FCF Per Share / Current Price) × 100
    FCF = Operating Cash Flow − CapEx
    FCF Per Share = FCF / Shares Outstanding

    Guards:
    - Operating cash flow must be present.
    - Shares outstanding must be positive.
    - Current price must be positive (validated upstream, but guarded here too).
    """
    ts = _format_timestamp(data_timestamp)
    metric_name = "fcf_yield"
    method = "Free Cash Flow Yield (FCF Yield)"
    formula = "((operating_cash_flow - capex) / shares_outstanding) / current_price * 100"
    unit = "%"

    ocf = _clean_number(data.get("operating_cash_flow"))
    capex = _clean_number(data.get("capex"))
    shares = _clean_number(data.get("shares_outstanding"))

    if ocf is None:
        return _unavailable(
            metric_name, unit, method, formula,
            reason="operating_cash_flow is missing or non-numeric in fundamental_data",
            context_id=context_id, data_timestamp=ts,
        )
    if shares is None:
        return _unavailable(
            metric_name, unit, method, formula,
            reason="shares_outstanding is missing or non-numeric in fundamental_data",
            context_id=context_id, data_timestamp=ts,
        )
    if shares <= 0:
        return _unavailable(
            metric_name, unit, method, formula,
            reason=f"shares_outstanding={shares:.0f} is non-positive — cannot compute FCF per share",
            context_id=context_id, data_timestamp=ts,
        )
    if current_price <= 0:
        return _unavailable(
            metric_name, unit, method, formula,
            reason=f"current_price={current_price:.4f} is non-positive — cannot compute FCF yield",
            context_id=context_id, data_timestamp=ts,
        )

    # capex defaults to 0 if not provided (conservative, documented)
    resolved_capex = capex if capex is not None else 0.0

    fcf = ocf - resolved_capex
    fcf_per_share = fcf / shares
    fcf_yield = (fcf_per_share / current_price) * 100.0

    assumptions = ["FCF = Operating Cash Flow − CapEx (maintenance and growth capex combined)"]
    if capex is None:
        assumptions.append("capex assumed 0.0 (not provided in fundamental_data)")

    return ValuationMetric(
        metric_name=metric_name,
        value=round(fcf_yield, 4),
        unit=unit,
        method=method,
        formula=formula,
        inputs={
            "operating_cash_flow": ocf,
            "capex": resolved_capex,
            "shares_outstanding": shares,
            "current_price": current_price,
            "free_cash_flow": round(fcf, 2),
            "fcf_per_share": round(fcf_per_share, 4),
        },
        available=True,
        unavailable_reason="",
        assumptions=assumptions,
        context_id=context_id,
        data_timestamp=ts,
    )


# ── 6. PEG Ratio ──────────────────────────────────────────────────────────────

def calc_peg_ratio(
    data: Dict[str, Any],
    current_price: float,
    context_id: str,
    data_timestamp: Optional[datetime] = None,
) -> ValuationMetric:
    """
    PEG Ratio = P/E Ratio / EPS Growth Rate (%)

    EPS Growth Rate (%) = ((eps - prior_eps) / abs(prior_eps)) * 100
    Or uses explicit 'eps_growth_rate' if provided.

    Guards:
    - P/E must be available (positive EPS).
    - EPS growth rate must be positive (negative growth → PEG economically distorted).
    - Growth rate == 0 → division by zero.
    - prior_eps == 0 or None → growth rate undefined.
    """
    ts = _format_timestamp(data_timestamp)
    metric_name = "peg_ratio"
    method = "Price/Earnings-to-Growth (PEG)"
    formula = "pe_ratio / eps_growth_rate_pct"
    unit = "x"

    # First compute the P/E component
    pe_metric = calc_pe_ratio(data, current_price, context_id, data_timestamp)
    if not pe_metric.available:
        return _unavailable(
            metric_name, unit, method, formula,
            reason=f"P/E ratio unavailable (required for PEG): {pe_metric.unavailable_reason}",
            context_id=context_id, data_timestamp=ts,
        )

    pe_value = pe_metric.value  # guaranteed non-None if available

    # Determine EPS growth rate
    explicit_growth = _clean_number(data.get("eps_growth_rate"))
    if explicit_growth is not None:
        growth_rate_pct = explicit_growth
        growth_source = "explicit eps_growth_rate field"
    else:
        eps = _clean_number(data.get("eps"))
        prior_eps = _clean_number(data.get("prior_eps"))

        if eps is None:
            return _unavailable(
                metric_name, unit, method, formula,
                reason="eps is missing — cannot compute EPS growth rate for PEG",
                context_id=context_id, data_timestamp=ts,
            )
        if prior_eps is None:
            return _unavailable(
                metric_name, unit, method, formula,
                reason="prior_eps is missing — cannot compute EPS growth rate for PEG",
                context_id=context_id, data_timestamp=ts,
            )
        if prior_eps == 0.0:
            return _unavailable(
                metric_name, unit, method, formula,
                reason="prior_eps == 0 — EPS growth rate is undefined (division by zero)",
                context_id=context_id, data_timestamp=ts,
            )

        growth_rate_pct = ((eps - prior_eps) / abs(prior_eps)) * 100.0
        growth_source = "derived from (eps - prior_eps) / abs(prior_eps) * 100"

    if growth_rate_pct == 0.0:
        return _unavailable(
            metric_name, unit, method, formula,
            reason="eps_growth_rate == 0% — PEG undefined (division by zero)",
            context_id=context_id, data_timestamp=ts,
        )
    if growth_rate_pct < 0.0:
        return _unavailable(
            metric_name, unit, method, formula,
            reason=(
                f"eps_growth_rate={growth_rate_pct:.2f}% is negative — "
                "PEG is economically distorted for declining earnings"
            ),
            context_id=context_id, data_timestamp=ts,
        )

    peg = pe_value / growth_rate_pct
    return ValuationMetric(
        metric_name=metric_name,
        value=round(peg, 4),
        unit=unit,
        method=method,
        formula=formula,
        inputs={
            "pe_ratio": pe_value,
            "eps_growth_rate_pct": round(growth_rate_pct, 4),
            "growth_source": growth_source,
        },
        available=True,
        unavailable_reason="",
        assumptions=[
            "EPS growth rate is annualized based on trailing YoY comparison",
            "PEG < 1 conventionally suggests undervaluation relative to growth",
        ],
        context_id=context_id,
        data_timestamp=ts,
    )


# ── Master Runner ─────────────────────────────────────────────────────────────

def compute_all_valuation_metrics(
    fundamental_data: Dict[str, Any],
    current_price: float,
    context_id: str,
    data_timestamp: Optional[datetime] = None,
) -> List[ValuationMetric]:
    """
    Compute the full suite of valuation metrics deterministically.

    Returns a list of ValuationMetric records (available or unavailable).
    Order: P/E, P/S, P/B, EV/EBITDA, FCF Yield, PEG.

    Parameters
    ----------
    fundamental_data : dict
        Financial statement data from MarketContext.fundamental_data.
    current_price : float
        Current share price from MarketContext.current_price.
    context_id : str
        MarketContext.context_id — preserved for full provenance.
    data_timestamp : datetime, optional
        MarketContext.data_timestamp for traceability.
    """
    metrics: List[ValuationMetric] = []
    kwargs = dict(
        data=fundamental_data,
        current_price=current_price,
        context_id=context_id,
        data_timestamp=data_timestamp,
    )

    metrics.append(calc_pe_ratio(**kwargs))
    metrics.append(calc_ps_ratio(**kwargs))
    metrics.append(calc_pb_ratio(**kwargs))
    metrics.append(calc_ev_ebitda(**kwargs))
    metrics.append(calc_fcf_yield(**kwargs))
    metrics.append(calc_peg_ratio(**kwargs))

    return metrics


def summarize_available(metrics: List[ValuationMetric]) -> Tuple[List[str], int]:
    """
    Return a list of available method names and the count of available metrics.

    Parameters
    ----------
    metrics : list[ValuationMetric]

    Returns
    -------
    available_methods : list[str]
    available_count : int
    """
    available = [m for m in metrics if m.available]
    return [m.method for m in available], len(available)
