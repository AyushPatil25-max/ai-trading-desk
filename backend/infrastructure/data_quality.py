"""
Data Quality Engine — Phase 2 Data Coverage Foundation

Provides deterministic validation, completeness classification, and quality scoring
across market quotes, OHLCV bars, financial observations, institutional holdings,
macro indicators, and provenance records.
"""

from enum import Enum
import math
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone, timedelta

from backend.domain.schemas import DataQuality, ProvenanceRecord, MarketContext, DataQualityStatus


class DataCompletenessState(str, Enum):
    DATA_COMPLETE = "DATA_COMPLETE"
    DATA_PARTIAL = "DATA_PARTIAL"
    DATA_STALE = "DATA_STALE"
    DATA_CONFLICT = "DATA_CONFLICT"
    DATA_INSUFFICIENT = "DATA_INSUFFICIENT"


def validate_numeric(value: Any) -> DataQuality:
    """Validates that a value is numeric and not NaN/Inf."""
    try:
        float_val = float(value)
        if math.isnan(float_val) or math.isinf(float_val):
            return DataQuality.INVALID
        return DataQuality.HIGH
    except (ValueError, TypeError):
        return DataQuality.INVALID


def is_missing_value(val: Any) -> bool:
    """
    Deterministically determines if a value is missing (None, NaN, empty).
    CRITICAL: 0.0 and negative numbers are legitimate financial values, NOT missing!
    """
    if val is None:
        return True
    if isinstance(val, str) and val.strip() == "":
        return True
    try:
        float_val = float(val)
        if math.isnan(float_val) or math.isinf(float_val):
            return True
        return False
    except (ValueError, TypeError):
        return False


def is_valid_numeric_value(val: Any, allow_negative: bool = True) -> bool:
    """
    Returns True if val is a valid finite float/int.
    """
    if is_missing_value(val):
        return False
    try:
        f = float(val)
        if not allow_negative and f < 0:
            return False
        return True
    except (ValueError, TypeError):
        return False


def validate_price(price: Any) -> DataQuality:
    """Validates a price value is strictly positive."""
    quality = validate_numeric(price)
    if quality == DataQuality.INVALID:
        return quality

    if float(price) <= 0:
        return DataQuality.INVALID
    return DataQuality.HIGH


def validate_timestamp(ts: Any, max_future_tolerance_seconds: int = 60) -> DataQuality:
    """Validates that a timestamp is a valid datetime and not unreasonably in the future."""
    if not isinstance(ts, datetime):
        return DataQuality.INVALID

    now = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        # Compare naive with UTC naive
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        delta = ts - now_naive
    else:
        delta = ts - now

    if delta.total_seconds() > max_future_tolerance_seconds:
        return DataQuality.INVALID

    return DataQuality.HIGH


def validate_currency(currency: str, expected: str = "INR") -> DataQuality:
    """Validates currency string against expected baseline."""
    if not isinstance(currency, str):
        return DataQuality.INVALID
    if currency.upper() != expected.upper():
        return DataQuality.LOW
    return DataQuality.HIGH


def validate_period(period: str, expected_formats: Optional[List[str]] = None) -> DataQuality:
    """Validates standard financial reporting periods (e.g. Q1, FY23, TTM)."""
    if expected_formats is None:
        expected_formats = ["Q1", "Q2", "Q3", "Q4", "FY", "TTM", "ANNUAL", "YTD", "MRQ"]

    if not isinstance(period, str) or not period:
        return DataQuality.INVALID

    upper_period = period.upper()
    for fmt in expected_formats:
        if fmt in upper_period:
            return DataQuality.HIGH

    return DataQuality.MEDIUM


def validate_provenance(record: ProvenanceRecord) -> Dict[str, DataQuality]:
    """Validates an entire provenance record and returns a quality summary mapping."""
    return {
        "value": validate_numeric(record.value),
        "observed_at": validate_timestamp(record.observed_at),
        "currency": validate_currency(record.currency),
        "period": validate_period(record.period),
    }


def determine_completeness_state(
    context: MarketContext,
    as_of: Optional[datetime] = None,
    max_stale_days: int = 7,
) -> DataCompletenessState:
    """
    Deterministically computes the completeness state of a MarketContext.
    """
    # 1. Check for insufficient critical data
    if context.quality_status == DataQualityStatus.CRITICAL_FAILURE or context.current_price <= 0:
        return DataCompletenessState.DATA_INSUFFICIENT

    ohlcv = context.ohlcv_historical or []
    if len(ohlcv) < 5:
        return DataCompletenessState.DATA_INSUFFICIENT

    # 2. Check for unresolved conflicts
    if context.conflicts and len(context.conflicts) > 0:
        return DataCompletenessState.DATA_CONFLICT

    # 3. Check staleness
    ref_time = as_of or datetime.now(timezone.utc)
    ts = context.data_timestamp
    if ts:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)
        age = (ref_time - ts).total_seconds()
        if age > (max_stale_days * 86400):
            return DataCompletenessState.DATA_STALE

    # 4. Check completeness of fundamentals & technicals
    has_technicals = bool(context.technical_indicators and len(context.technical_indicators) >= 3)
    has_fundamentals = bool(context.fundamental_data and len(context.fundamental_data) >= 3)
    has_depth = len(ohlcv) >= 50

    if has_technicals and has_fundamentals and has_depth:
        return DataCompletenessState.DATA_COMPLETE

    return DataCompletenessState.DATA_PARTIAL


def compute_data_quality_score(
    context: MarketContext,
    as_of: Optional[datetime] = None,
) -> float:
    """
    Computes a deterministic, testable Data Quality Score (0.0 to 1.0).

    Components:
    - Price & Historical Depth (0.35 max)
    - Technical Indicator Completeness (0.15 max)
    - Fundamental Data Coverage (0.25 max)
    - Institutional & Alternative Data (0.15 max)
    - Source Reliability & Conflict Penalty (0.10 max)
    """
    if context.current_price <= 0:
        return 0.0

    score = 0.0

    # 1. Price and OHLCV depth (0.35)
    score += 0.15  # Valid positive price
    ohlcv_count = len(context.ohlcv_historical or [])
    if ohlcv_count >= 50:
        score += 0.20
    elif ohlcv_count >= 20:
        score += 0.10
    elif ohlcv_count >= 5:
        score += 0.05

    # 2. Technical indicator completeness (0.15)
    techs = context.technical_indicators or {}
    expected_techs = ["ema20", "ema50", "rsi", "20_day_high"]
    present_techs = sum(1 for k in expected_techs if k in techs or k.upper() in techs)
    score += (present_techs / len(expected_techs)) * 0.15

    # 3. Fundamental Data Coverage (0.25)
    funds = context.fundamental_data or {}
    if funds:
        valid_fund_metrics = 0
        fund_keys = ["revenue", "net_income", "eps", "total_debt", "cash", "operating_cash_flow", "pe_ratio"]
        for k in fund_keys:
            if k in funds and not is_missing_value(funds[k]):
                valid_fund_metrics += 1
        score += min(0.25, (valid_fund_metrics / 5.0) * 0.25)

    # 4. Institutional, Ownership, News, Macro Data (0.15)
    alt_score = 0.0
    if context.institutional_data:
        alt_score += 0.05
    if context.ownership_data:
        alt_score += 0.04
    if context.macro_data:
        alt_score += 0.03
    if context.news_data:
        alt_score += 0.03
    score += min(0.15, alt_score)

    # 5. Source reliability & Consistency (0.10)
    source_score = 0.10
    if context.conflicts and len(context.conflicts) > 0:
        source_score -= 0.05

    state = determine_completeness_state(context, as_of=as_of)
    if state == DataCompletenessState.DATA_STALE:
        source_score -= 0.05
    elif state == DataCompletenessState.DATA_INSUFFICIENT:
        source_score = 0.0

    score += max(0.0, source_score)

    return round(max(0.0, min(1.0, score)), 3)
