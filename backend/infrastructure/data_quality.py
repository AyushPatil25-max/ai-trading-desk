from typing import Any, Dict, Optional
from datetime import datetime
import math

from backend.domain.schemas import DataQuality, ProvenanceRecord

def validate_numeric(value: Any) -> DataQuality:
    """Validates that a value is numeric and not NaN/Inf."""
    try:
        float_val = float(value)
        if math.isnan(float_val) or math.isinf(float_val):
            return DataQuality.INVALID
        return DataQuality.HIGH
    except (ValueError, TypeError):
        return DataQuality.INVALID

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
        
    now = datetime.utcnow()
    # If tz-aware, convert now to tz-aware for comparison, or naive to naive
    if ts.tzinfo is not None:
        now = now.replace(tzinfo=ts.tzinfo) # simplified for offline check
        
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

def validate_period(period: str, expected_formats: list = None) -> DataQuality:
    """Validates standard financial reporting periods (e.g. Q1, FY23, TTM)."""
    if expected_formats is None:
        expected_formats = ["Q1", "Q2", "Q3", "Q4", "FY", "TTM", "ANNUAL", "YTD"]
        
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
        "period": validate_period(record.period)
    }
