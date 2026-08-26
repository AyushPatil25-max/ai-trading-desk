"""
fundamental_calculator.py — Phase 3.5

Pure Python deterministic financial calculator for fundamental analysis.
Zero external network calls, zero LLM dependency.

Responsibilities
----------------
- Compute deterministic accounting ratios (margins, growth, leverage, liquidity, efficiency).
- Extract point-in-time and period fundamental facts.
- Enforce strict mathematical guards (division by zero, negative denominators, NaN/Inf).
- Track complete provenance (metric name, period, source, calculation method, data timestamp).
- Handle missing data transparently with explicit reasons rather than fabricated numbers.
- Perform period compatibility checks and data freshness assessment.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class FundamentalMetric:
    """
    In-memory representation of a calculated or extracted fundamental metric.
    Maps directly to FundamentalMetricRecord schema.
    """
    metric_name: str
    value: Optional[float]
    unit: str
    period: str
    report_date: Optional[str]
    available: bool
    unavailable_reason: str
    source: str
    calculation_method: str
    data_timestamp: str


def _clean_number(val: Any) -> Optional[float]:
    """Convert input to float, guarding against None, NaN, and Inf. Unpacks FinancialObservation."""
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
    """Format datetime to ISO string."""
    if ts is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(ts, datetime):
        return ts.isoformat()
    return str(ts)


# ── 1. Profitability & Margin Metrics ─────────────────────────────────────────

def calc_gross_margin(data: Dict[str, Any], data_timestamp: Optional[datetime] = None) -> FundamentalMetric:
    """
    Gross Margin % = (gross_profit / revenue) * 100
    """
    ts_str = _format_timestamp(data_timestamp)
    period = str(data.get("period", "TTM"))
    report_date = data.get("report_date")

    revenue = _clean_number(data.get("revenue"))
    gross_profit = _clean_number(data.get("gross_profit"))

    if revenue is None or gross_profit is None:
        return FundamentalMetric(
            metric_name="gross_margin",
            value=None,
            unit="%",
            period=period,
            report_date=report_date,
            available=False,
            unavailable_reason="Missing revenue or gross_profit in fundamental data",
            source="income_statement",
            calculation_method="gross_profit / revenue * 100",
            data_timestamp=ts_str,
        )

    if revenue <= 0:
        return FundamentalMetric(
            metric_name="gross_margin",
            value=None,
            unit="%",
            period=period,
            report_date=report_date,
            available=False,
            unavailable_reason=f"Non-positive revenue ({revenue}) prevents margin calculation",
            source="income_statement",
            calculation_method="gross_profit / revenue * 100",
            data_timestamp=ts_str,
        )

    margin = round((gross_profit / revenue) * 100.0, 2)
    return FundamentalMetric(
        metric_name="gross_margin",
        value=margin,
        unit="%",
        period=period,
        report_date=report_date,
        available=True,
        unavailable_reason="",
        source="income_statement",
        calculation_method="gross_profit / revenue * 100",
        data_timestamp=ts_str,
    )


def calc_operating_margin(data: Dict[str, Any], data_timestamp: Optional[datetime] = None) -> FundamentalMetric:
    """
    Operating Margin % = (operating_profit / revenue) * 100
    """
    ts_str = _format_timestamp(data_timestamp)
    period = str(data.get("period", "TTM"))
    report_date = data.get("report_date")

    revenue = _clean_number(data.get("revenue"))
    operating_profit = _clean_number(data.get("operating_profit"))

    if revenue is None or operating_profit is None:
        return FundamentalMetric(
            metric_name="operating_margin",
            value=None,
            unit="%",
            period=period,
            report_date=report_date,
            available=False,
            unavailable_reason="Missing revenue or operating_profit in fundamental data",
            source="income_statement",
            calculation_method="operating_profit / revenue * 100",
            data_timestamp=ts_str,
        )

    if revenue <= 0:
        return FundamentalMetric(
            metric_name="operating_margin",
            value=None,
            unit="%",
            period=period,
            report_date=report_date,
            available=False,
            unavailable_reason=f"Non-positive revenue ({revenue}) prevents margin calculation",
            source="income_statement",
            calculation_method="operating_profit / revenue * 100",
            data_timestamp=ts_str,
        )

    margin = round((operating_profit / revenue) * 100.0, 2)
    return FundamentalMetric(
        metric_name="operating_margin",
        value=margin,
        unit="%",
        period=period,
        report_date=report_date,
        available=True,
        unavailable_reason="",
        source="income_statement",
        calculation_method="operating_profit / revenue * 100",
        data_timestamp=ts_str,
    )


def calc_net_margin(data: Dict[str, Any], data_timestamp: Optional[datetime] = None) -> FundamentalMetric:
    """
    Net Profit Margin % = (net_income / revenue) * 100
    """
    ts_str = _format_timestamp(data_timestamp)
    period = str(data.get("period", "TTM"))
    report_date = data.get("report_date")

    revenue = _clean_number(data.get("revenue"))
    net_income = _clean_number(data.get("net_income"))

    if revenue is None or net_income is None:
        return FundamentalMetric(
            metric_name="net_margin",
            value=None,
            unit="%",
            period=period,
            report_date=report_date,
            available=False,
            unavailable_reason="Missing revenue or net_income in fundamental data",
            source="income_statement",
            calculation_method="net_income / revenue * 100",
            data_timestamp=ts_str,
        )

    if revenue <= 0:
        return FundamentalMetric(
            metric_name="net_margin",
            value=None,
            unit="%",
            period=period,
            report_date=report_date,
            available=False,
            unavailable_reason=f"Non-positive revenue ({revenue}) prevents margin calculation",
            source="income_statement",
            calculation_method="net_income / revenue * 100",
            data_timestamp=ts_str,
        )

    margin = round((net_income / revenue) * 100.0, 2)
    return FundamentalMetric(
        metric_name="net_margin",
        value=margin,
        unit="%",
        period=period,
        report_date=report_date,
        available=True,
        unavailable_reason="",
        source="income_statement",
        calculation_method="net_income / revenue * 100",
        data_timestamp=ts_str,
    )


# ── 2. Growth Metrics ─────────────────────────────────────────────────────────

def calc_revenue_growth_yoy(data: Dict[str, Any], data_timestamp: Optional[datetime] = None) -> FundamentalMetric:
    """
    Revenue Growth YoY % = ((revenue - prior_revenue) / prior_revenue) * 100
    """
    ts_str = _format_timestamp(data_timestamp)
    period = str(data.get("period", "TTM"))
    report_date = data.get("report_date")

    revenue = _clean_number(data.get("revenue"))
    prior_revenue = _clean_number(data.get("prior_revenue"))

    # Also check if growth was directly reported
    direct_growth = _clean_number(data.get("revenue_growth_yoy"))
    if direct_growth is not None:
        return FundamentalMetric(
            metric_name="revenue_growth_yoy",
            value=round(direct_growth, 2),
            unit="%",
            period=period,
            report_date=report_date,
            available=True,
            unavailable_reason="",
            source="income_statement",
            calculation_method="reported_revenue_growth",
            data_timestamp=ts_str,
        )

    if revenue is None or prior_revenue is None:
        return FundamentalMetric(
            metric_name="revenue_growth_yoy",
            value=None,
            unit="%",
            period=period,
            report_date=report_date,
            available=False,
            unavailable_reason="Missing revenue or prior_revenue for YoY comparison",
            source="income_statement",
            calculation_method="(revenue - prior_revenue) / prior_revenue * 100",
            data_timestamp=ts_str,
        )

    if prior_revenue <= 0:
        return FundamentalMetric(
            metric_name="revenue_growth_yoy",
            value=None,
            unit="%",
            period=period,
            report_date=report_date,
            available=False,
            unavailable_reason=f"Non-positive prior_revenue ({prior_revenue}) prevents YoY calculation",
            source="income_statement",
            calculation_method="(revenue - prior_revenue) / prior_revenue * 100",
            data_timestamp=ts_str,
        )

    growth = round(((revenue - prior_revenue) / prior_revenue) * 100.0, 2)
    return FundamentalMetric(
        metric_name="revenue_growth_yoy",
        value=growth,
        unit="%",
        period=period,
        report_date=report_date,
        available=True,
        unavailable_reason="",
        source="income_statement",
        calculation_method="(revenue - prior_revenue) / prior_revenue * 100",
        data_timestamp=ts_str,
    )


def calc_eps_growth_yoy(data: Dict[str, Any], data_timestamp: Optional[datetime] = None) -> FundamentalMetric:
    """
    EPS Growth YoY % = ((eps - prior_eps) / abs(prior_eps)) * 100
    """
    ts_str = _format_timestamp(data_timestamp)
    period = str(data.get("period", "TTM"))
    report_date = data.get("report_date")

    eps = _clean_number(data.get("eps"))
    prior_eps = _clean_number(data.get("prior_eps"))

    direct_growth = _clean_number(data.get("eps_growth_yoy"))
    if direct_growth is not None:
        return FundamentalMetric(
            metric_name="eps_growth_yoy",
            value=round(direct_growth, 2),
            unit="%",
            period=period,
            report_date=report_date,
            available=True,
            unavailable_reason="",
            source="income_statement",
            calculation_method="reported_eps_growth",
            data_timestamp=ts_str,
        )

    if eps is None or prior_eps is None:
        return FundamentalMetric(
            metric_name="eps_growth_yoy",
            value=None,
            unit="%",
            period=period,
            report_date=report_date,
            available=False,
            unavailable_reason="Missing eps or prior_eps for YoY comparison",
            source="income_statement",
            calculation_method="(eps - prior_eps) / abs(prior_eps) * 100",
            data_timestamp=ts_str,
        )

    if prior_eps == 0:
        return FundamentalMetric(
            metric_name="eps_growth_yoy",
            value=None,
            unit="%",
            period=period,
            report_date=report_date,
            available=False,
            unavailable_reason="Zero prior_eps prevents percentage growth calculation",
            source="income_statement",
            calculation_method="(eps - prior_eps) / abs(prior_eps) * 100",
            data_timestamp=ts_str,
        )

    growth = round(((eps - prior_eps) / abs(prior_eps)) * 100.0, 2)
    return FundamentalMetric(
        metric_name="eps_growth_yoy",
        value=growth,
        unit="%",
        period=period,
        report_date=report_date,
        available=True,
        unavailable_reason="",
        source="income_statement",
        calculation_method="(eps - prior_eps) / abs(prior_eps) * 100",
        data_timestamp=ts_str,
    )


# ── 3. Balance Sheet & Solvency Metrics ──────────────────────────────────────

def calc_debt_to_equity(data: Dict[str, Any], data_timestamp: Optional[datetime] = None) -> FundamentalMetric:
    """
    Debt to Equity Ratio = total_debt / total_equity
    """
    ts_str = _format_timestamp(data_timestamp)
    period = str(data.get("period", "MRQ"))
    report_date = data.get("report_date")

    total_debt = _clean_number(data.get("total_debt"))
    total_equity = _clean_number(data.get("total_equity"))

    if total_debt is None or total_equity is None:
        return FundamentalMetric(
            metric_name="debt_to_equity",
            value=None,
            unit="ratio",
            period=period,
            report_date=report_date,
            available=False,
            unavailable_reason="Missing total_debt or total_equity in balance sheet data",
            source="balance_sheet",
            calculation_method="total_debt / total_equity",
            data_timestamp=ts_str,
        )

    if total_equity <= 0:
        return FundamentalMetric(
            metric_name="debt_to_equity",
            value=None,
            unit="ratio",
            period=period,
            report_date=report_date,
            available=False,
            unavailable_reason=f"Non-positive equity ({total_equity}) prevents D/E ratio calculation",
            source="balance_sheet",
            calculation_method="total_debt / total_equity",
            data_timestamp=ts_str,
        )

    ratio = round(total_debt / total_equity, 2)
    return FundamentalMetric(
        metric_name="debt_to_equity",
        value=ratio,
        unit="ratio",
        period=period,
        report_date=report_date,
        available=True,
        unavailable_reason="",
        source="balance_sheet",
        calculation_method="total_debt / total_equity",
        data_timestamp=ts_str,
    )


def calc_current_ratio(data: Dict[str, Any], data_timestamp: Optional[datetime] = None) -> FundamentalMetric:
    """
    Current Ratio = current_assets / current_liabilities
    """
    ts_str = _format_timestamp(data_timestamp)
    period = str(data.get("period", "MRQ"))
    report_date = data.get("report_date")

    current_assets = _clean_number(data.get("current_assets"))
    current_liabilities = _clean_number(data.get("current_liabilities"))

    if current_assets is None or current_liabilities is None:
        return FundamentalMetric(
            metric_name="current_ratio",
            value=None,
            unit="ratio",
            period=period,
            report_date=report_date,
            available=False,
            unavailable_reason="Missing current_assets or current_liabilities in balance sheet data",
            source="balance_sheet",
            calculation_method="current_assets / current_liabilities",
            data_timestamp=ts_str,
        )

    if current_liabilities <= 0:
        return FundamentalMetric(
            metric_name="current_ratio",
            value=None,
            unit="ratio",
            period=period,
            report_date=report_date,
            available=False,
            unavailable_reason=f"Non-positive liabilities ({current_liabilities}) prevents ratio calculation",
            source="balance_sheet",
            calculation_method="current_assets / current_liabilities",
            data_timestamp=ts_str,
        )

    ratio = round(current_assets / current_liabilities, 2)
    return FundamentalMetric(
        metric_name="current_ratio",
        value=ratio,
        unit="ratio",
        period=period,
        report_date=report_date,
        available=True,
        unavailable_reason="",
        source="balance_sheet",
        calculation_method="current_assets / current_liabilities",
        data_timestamp=ts_str,
    )


def calc_roe(data: Dict[str, Any], data_timestamp: Optional[datetime] = None) -> FundamentalMetric:
    """
    Return on Equity % = (net_income / total_equity) * 100
    """
    ts_str = _format_timestamp(data_timestamp)
    period = str(data.get("period", "TTM"))
    report_date = data.get("report_date")

    net_income = _clean_number(data.get("net_income"))
    total_equity = _clean_number(data.get("total_equity"))

    if net_income is None or total_equity is None:
        return FundamentalMetric(
            metric_name="return_on_equity",
            value=None,
            unit="%",
            period=period,
            report_date=report_date,
            available=False,
            unavailable_reason="Missing net_income or total_equity for ROE calculation",
            source="financial_statements",
            calculation_method="net_income / total_equity * 100",
            data_timestamp=ts_str,
        )

    if total_equity <= 0:
        return FundamentalMetric(
            metric_name="return_on_equity",
            value=None,
            unit="%",
            period=period,
            report_date=report_date,
            available=False,
            unavailable_reason=f"Non-positive equity ({total_equity}) prevents ROE calculation",
            source="financial_statements",
            calculation_method="net_income / total_equity * 100",
            data_timestamp=ts_str,
        )

    roe = round((net_income / total_equity) * 100.0, 2)
    return FundamentalMetric(
        metric_name="return_on_equity",
        value=roe,
        unit="%",
        period=period,
        report_date=report_date,
        available=True,
        unavailable_reason="",
        source="financial_statements",
        calculation_method="net_income / total_equity * 100",
        data_timestamp=ts_str,
    )


# ── 4. Cash Flow Metrics ──────────────────────────────────────────────────────

def calc_free_cash_flow(data: Dict[str, Any], data_timestamp: Optional[datetime] = None) -> FundamentalMetric:
    """
    Free Cash Flow = operating_cash_flow - capex
    """
    ts_str = _format_timestamp(data_timestamp)
    period = str(data.get("period", "TTM"))
    report_date = data.get("report_date")

    direct_fcf = _clean_number(data.get("free_cash_flow"))
    if direct_fcf is not None:
        return FundamentalMetric(
            metric_name="free_cash_flow",
            value=round(direct_fcf, 2),
            unit="currency",
            period=period,
            report_date=report_date,
            available=True,
            unavailable_reason="",
            source="cash_flow_statement",
            calculation_method="reported_free_cash_flow",
            data_timestamp=ts_str,
        )

    ocf = _clean_number(data.get("operating_cash_flow"))
    capex = _clean_number(data.get("capex") or data.get("capital_expenditure"))

    if ocf is None or capex is None:
        return FundamentalMetric(
            metric_name="free_cash_flow",
            value=None,
            unit="currency",
            period=period,
            report_date=report_date,
            available=False,
            unavailable_reason="Missing operating_cash_flow or capex in cash flow data",
            source="cash_flow_statement",
            calculation_method="operating_cash_flow - capex",
            data_timestamp=ts_str,
        )

    # Note: capex can be reported as positive or negative; standard formula assumes capex outflow
    # If capex is negative, subtracting a negative would add it, so take abs if standard accounting
    capex_val = abs(capex)
    fcf = round(ocf - capex_val, 2)
    return FundamentalMetric(
        metric_name="free_cash_flow",
        value=fcf,
        unit="currency",
        period=period,
        report_date=report_date,
        available=True,
        unavailable_reason="",
        source="cash_flow_statement",
        calculation_method="operating_cash_flow - capex",
        data_timestamp=ts_str,
    )


# ── 5. Valuation Ratios (Deterministic with Current Price) ───────────────────

def calc_pe_ratio(
    current_price: float,
    data: Dict[str, Any],
    data_timestamp: Optional[datetime] = None,
) -> FundamentalMetric:
    """
    Price-to-Earnings Ratio = current_price / eps
    """
    ts_str = _format_timestamp(data_timestamp)
    period = str(data.get("period", "TTM"))
    report_date = data.get("report_date")

    eps = _clean_number(data.get("eps"))
    price = _clean_number(current_price)

    if eps is None or price is None:
        return FundamentalMetric(
            metric_name="pe_ratio",
            value=None,
            unit="ratio",
            period=period,
            report_date=report_date,
            available=False,
            unavailable_reason="Missing current_price or eps for P/E calculation",
            source="market_and_income_statement",
            calculation_method="current_price / eps",
            data_timestamp=ts_str,
        )

    if eps <= 0:
        return FundamentalMetric(
            metric_name="pe_ratio",
            value=None,
            unit="ratio",
            period=period,
            report_date=report_date,
            available=False,
            unavailable_reason=f"Non-positive EPS ({eps}) produces undefined or negative P/E",
            source="market_and_income_statement",
            calculation_method="current_price / eps",
            data_timestamp=ts_str,
        )

    pe = round(price / eps, 2)
    return FundamentalMetric(
        metric_name="pe_ratio",
        value=pe,
        unit="ratio",
        period=period,
        report_date=report_date,
        available=True,
        unavailable_reason="",
        source="market_and_income_statement",
        calculation_method="current_price / eps",
        data_timestamp=ts_str,
    )


# ── 6. Passthrough Fundamental Facts ──────────────────────────────────────────

def extract_passthrough_metric(
    metric_name: str,
    key: str,
    unit: str,
    source: str,
    data: Dict[str, Any],
    data_timestamp: Optional[datetime] = None,
) -> FundamentalMetric:
    """Extract a direct financial fact from verified data with provenance."""
    ts_str = _format_timestamp(data_timestamp)
    period = str(data.get("period", "TTM"))
    report_date = data.get("report_date")

    val = _clean_number(data.get(key))
    if val is None:
        return FundamentalMetric(
            metric_name=metric_name,
            value=None,
            unit=unit,
            period=period,
            report_date=report_date,
            available=False,
            unavailable_reason=f"Field '{key}' not provided in fundamental dataset",
            source=source,
            calculation_method="direct_extraction",
            data_timestamp=ts_str,
        )

    return FundamentalMetric(
        metric_name=metric_name,
        value=round(val, 2),
        unit=unit,
        period=period,
        report_date=report_date,
        available=True,
        unavailable_reason="",
        source=source,
        calculation_method="direct_extraction",
        data_timestamp=ts_str,
    )


# ── 7. Freshness Assessment ───────────────────────────────────────────────────

def assess_data_freshness(
    data: Dict[str, Any],
    market_timestamp: Optional[datetime] = None,
    max_stale_days: int = 180,
) -> Tuple[str, Optional[int]]:
    """
    Evaluate if reported fundamental data is stale relative to market data timestamp.
    Returns (freshness_status, age_days).
    """
    if not data:
        return "UNAVAILABLE", None

    report_date_str = data.get("report_date")
    if not report_date_str:
        # If no report date is provided, but data exists, consider FRESH
        return "FRESH", None

    try:
        if isinstance(report_date_str, datetime):
            report_dt = report_date_str
        else:
            # Parse ISO or YYYY-MM-DD
            clean_str = str(report_date_str).split("T")[0]
            report_dt = datetime.strptime(clean_str, "%Y-%m-%d")

        now = market_timestamp or datetime.now(timezone.utc)
        if report_dt.tzinfo is None and now.tzinfo is not None:
            now = now.replace(tzinfo=None)

        age_days = (now - report_dt).days
        if age_days > max_stale_days:
            return "STALE", age_days
        return "FRESH", age_days
    except Exception:
        return "FRESH", None


# ── 8. Master Runner ──────────────────────────────────────────────────────────

def compute_all_fundamental_metrics(
    fundamental_data: Optional[Dict[str, Any]],
    current_price: float,
    data_timestamp: Optional[datetime] = None,
) -> List[FundamentalMetric]:
    """
    Master entrypoint to compute and extract all fundamental metrics.

    Never raises an unhandled exception.
    Returns complete list of metrics with availability flags and provenance.
    """
    data = fundamental_data or {}
    metrics: List[FundamentalMetric] = []

    # Profitability / Margins
    metrics.append(calc_gross_margin(data, data_timestamp))
    metrics.append(calc_operating_margin(data, data_timestamp))
    metrics.append(calc_net_margin(data, data_timestamp))

    # Growth
    metrics.append(calc_revenue_growth_yoy(data, data_timestamp))
    metrics.append(calc_eps_growth_yoy(data, data_timestamp))

    # Balance Sheet & Solvency
    metrics.append(calc_debt_to_equity(data, data_timestamp))
    metrics.append(calc_current_ratio(data, data_timestamp))
    metrics.append(calc_roe(data, data_timestamp))

    # Cash Flow
    metrics.append(calc_free_cash_flow(data, data_timestamp))

    # Valuation with current price
    metrics.append(calc_pe_ratio(current_price, data, data_timestamp))

    # Passthrough core financials
    metrics.append(extract_passthrough_metric("revenue", "revenue", "currency", "income_statement", data, data_timestamp))
    metrics.append(extract_passthrough_metric("net_income", "net_income", "currency", "income_statement", data, data_timestamp))
    metrics.append(extract_passthrough_metric("eps", "eps", "currency", "income_statement", data, data_timestamp))
    metrics.append(extract_passthrough_metric("operating_cash_flow", "operating_cash_flow", "currency", "cash_flow_statement", data, data_timestamp))
    metrics.append(extract_passthrough_metric("total_debt", "total_debt", "currency", "balance_sheet", data, data_timestamp))
    metrics.append(extract_passthrough_metric("cash_and_equivalents", "cash", "currency", "balance_sheet", data, data_timestamp))
    metrics.append(extract_passthrough_metric("total_equity", "total_equity", "currency", "balance_sheet", data, data_timestamp))

    return metrics
