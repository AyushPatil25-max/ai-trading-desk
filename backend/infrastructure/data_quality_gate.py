"""
Phase 21 — Market Data Quality Gate

Centralized validation gate that rigorously evaluates market context payloads
for numerical integrity, geometric OHLC invariants, timestamp validity,
duplicate/out-of-order sequence errors, and completeness.
"""

from datetime import datetime, timezone, timedelta
import math
from typing import Any, Dict, List, Optional, Set
import dateutil.parser

from backend.domain.schemas import MarketContext, HistoricalWindow, DataQualityStatus
from backend.domain.provider_schemas import (
    DataQualityCheckType,
    ValidationResult,
)


class DataQualityGate:
    """
    Centralized data quality assurance validator for all market data ingestion.
    Prevents corrupt, malformed, synthetic, or impossible market data from
    silently entering downstream research, debate, and execution pipelines.
    """

    def __init__(
        self,
        max_staleness_seconds: float = 7 * 86400,  # 7 days default
        future_tolerance_seconds: float = 300.0,    # 5 minutes clock drift
        max_price_discontinuity_ratio: float = 10.0, # 10x ratio jump
    ):
        self.max_staleness_seconds = max_staleness_seconds
        self.future_tolerance_seconds = future_tolerance_seconds
        self.max_price_discontinuity_ratio = max_price_discontinuity_ratio

    def validate(
        self,
        context: MarketContext,
        expected_symbol: Optional[str] = None,
        requested_window: Optional[HistoricalWindow] = None,
    ) -> ValidationResult:
        failure_reasons: List[str] = []
        warnings: List[str] = []
        checks_passed: List[DataQualityCheckType] = []
        checks_failed: List[DataQualityCheckType] = []

        # 1. Symbol & Context Completeness Check
        completeness_failed = False
        if not context.symbol or (expected_symbol and context.symbol.upper() != expected_symbol.upper()):
            failure_reasons.append(f"Symbol mismatch or missing: expected '{expected_symbol}', got '{context.symbol}'")
            completeness_failed = True

        if not context.ohlcv_historical:
            failure_reasons.append("Historical OHLCV observations list is empty")
            completeness_failed = True

        if completeness_failed:
            checks_failed.append(DataQualityCheckType.CONTEXT_COMPLETENESS)
        else:
            checks_passed.append(DataQualityCheckType.CONTEXT_COMPLETENESS)

        # 2. Price Bounds Check
        price = context.current_price
        price_bounds_failed = False
        if price is None:
            failure_reasons.append("Current price is missing (None)")
            price_bounds_failed = True
        elif not isinstance(price, (int, float)):
            failure_reasons.append(f"Current price is not numeric: {type(price)}")
            price_bounds_failed = True
        elif price <= 0.0:
            failure_reasons.append(f"Invalid non-positive current price: {price}")
            price_bounds_failed = True

        if price_bounds_failed:
            checks_failed.append(DataQualityCheckType.PRICE_BOUNDS)
        else:
            checks_passed.append(DataQualityCheckType.PRICE_BOUNDS)

        # 3. Numerical Integrity Check (NaN, Inf)
        numerical_failed = False
        def _check_nan_inf(val: Any, path: str) -> bool:
            if isinstance(val, (int, float)):
                if math.isnan(val) or math.isinf(val):
                    failure_reasons.append(f"Non-finite value (NaN or Inf) detected at {path}: {val}")
                    return True
            return False

        if _check_nan_inf(price, "context.current_price"):
            numerical_failed = True

        for idx, bar in enumerate(context.ohlcv_historical):
            for field in ["open", "high", "low", "close", "volume"]:
                val = bar.get(field)
                if val is not None and _check_nan_inf(val, f"ohlcv[{idx}].{field}"):
                    numerical_failed = True

        for k, v in context.technical_indicators.items():
            if v is not None and _check_nan_inf(v, f"technical_indicators.{k}"):
                numerical_failed = True

        if numerical_failed:
            checks_failed.append(DataQualityCheckType.NUMERICAL_INTEGRITY)
        else:
            checks_passed.append(DataQualityCheckType.NUMERICAL_INTEGRITY)

        # 4. Timestamp Freshness & Future Checks
        now_utc = datetime.now(timezone.utc)
        ts = context.data_timestamp
        if ts is not None:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            # Future check
            if ts > (now_utc + timedelta(seconds=self.future_tolerance_seconds)):
                failure_reasons.append(f"Future timestamp detected: {ts.isoformat()} > now + {self.future_tolerance_seconds}s")
                checks_failed.append(DataQualityCheckType.TIMESTAMP_FUTURE)
            else:
                checks_passed.append(DataQualityCheckType.TIMESTAMP_FUTURE)

            # Staleness check
            age_sec = (now_utc - ts).total_seconds()
            if age_sec > self.max_staleness_seconds:
                failure_reasons.append(f"Stale timestamp: age is {age_sec:.1f}s, exceeding max {self.max_staleness_seconds}s")
                checks_failed.append(DataQualityCheckType.TIMESTAMP_FRESHNESS)
            else:
                checks_passed.append(DataQualityCheckType.TIMESTAMP_FRESHNESS)
        else:
            failure_reasons.append("data_timestamp is None")
            checks_failed.append(DataQualityCheckType.TIMESTAMP_FRESHNESS)

        # 5. OHLC Invariants Check
        ohlc_failed = False
        for idx, bar in enumerate(context.ohlcv_historical):
            o = bar.get("open")
            h = bar.get("high")
            l = bar.get("low")
            c = bar.get("close")
            vol = bar.get("volume", 0.0)

            if None in (o, h, l, c):
                failure_reasons.append(f"Malformed OHLC at bar {idx}: missing required fields")
                ohlc_failed = True
                continue

            try:
                o, h, l, c = float(o), float(h), float(l), float(c)
            except (ValueError, TypeError):
                failure_reasons.append(f"Non-numeric OHLC values at bar {idx}")
                ohlc_failed = True
                continue

            if h < l:
                failure_reasons.append(f"Impossible OHLC at bar {idx}: high ({h}) < low ({l})")
                ohlc_failed = True
            if h < o or h < c:
                failure_reasons.append(f"Impossible OHLC at bar {idx}: high ({h}) is less than open ({o}) or close ({c})")
                ohlc_failed = True
            if l > o or l > c:
                failure_reasons.append(f"Impossible OHLC at bar {idx}: low ({l}) is greater than open ({o}) or close ({c})")
                ohlc_failed = True
            if vol is not None and vol < 0:
                failure_reasons.append(f"Negative volume at bar {idx}: {vol}")
                ohlc_failed = True

        if ohlc_failed:
            checks_failed.append(DataQualityCheckType.OHLC_RELATIONSHIPS)
        else:
            checks_passed.append(DataQualityCheckType.OHLC_RELATIONSHIPS)

        # 6. Duplicate & Out-of-Order Observations
        seen_dates: Set[str] = set()
        has_duplicates = False
        has_out_of_order = False
        parsed_dates: List[datetime] = []

        for idx, bar in enumerate(context.ohlcv_historical):
            raw_d = bar.get("date") or bar.get("timestamp")
            if raw_d:
                d_str = str(raw_d)
                if d_str in seen_dates:
                    failure_reasons.append(f"Duplicate observation detected at bar {idx}: date {d_str}")
                    has_duplicates = True
                seen_dates.add(d_str)

                try:
                    dt_val = dateutil.parser.isoparse(d_str) if isinstance(raw_d, str) else raw_d
                    if dt_val.tzinfo is None:
                        dt_val = dt_val.replace(tzinfo=timezone.utc)
                    parsed_dates.append(dt_val)
                except Exception:
                    pass

        if has_duplicates:
            checks_failed.append(DataQualityCheckType.DUPLICATE_OBSERVATIONS)
        else:
            checks_passed.append(DataQualityCheckType.DUPLICATE_OBSERVATIONS)

        # Check chronology
        for i in range(1, len(parsed_dates)):
            if parsed_dates[i] < parsed_dates[i - 1]:
                failure_reasons.append(
                    f"Out-of-order sequence detected at bar {i}: {parsed_dates[i].isoformat()} < {parsed_dates[i-1].isoformat()}"
                )
                has_out_of_order = True
                break

        if has_out_of_order:
            checks_failed.append(DataQualityCheckType.SEQUENCE_ORDER)
        else:
            checks_passed.append(DataQualityCheckType.SEQUENCE_ORDER)

        # 7. Discontinuity Check
        discontinuity_failed = False
        closes = [bar.get("close") for bar in context.ohlcv_historical if isinstance(bar.get("close"), (int, float)) and bar.get("close") > 0]
        for i in range(1, len(closes)):
            prev_c, curr_c = closes[i - 1], closes[i]
            ratio = curr_c / prev_c if prev_c > 0 else 1.0
            if ratio > self.max_price_discontinuity_ratio or ratio < (1.0 / self.max_price_discontinuity_ratio):
                failure_reasons.append(
                    f"Suspicious price discontinuity between bar {i-1} ({prev_c}) and bar {i} ({curr_c}): ratio {ratio:.2f}"
                )
                discontinuity_failed = True
                break

        if discontinuity_failed:
            checks_failed.append(DataQualityCheckType.DISCONTINUITY)
        else:
            checks_passed.append(DataQualityCheckType.DISCONTINUITY)

        is_valid = len(failure_reasons) == 0

        return ValidationResult(
            is_valid=is_valid,
            failure_reasons=failure_reasons,
            warnings=warnings,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
            evaluated_at=datetime.now(timezone.utc),
        )
