"""
json_safety.py — Centralized JSON Safety Boundary

Recursively sanitizes Python objects prior to JSON serialization, converting
NaN, +Infinity, and -Infinity to JSON-compliant None (null).
Preserves ints, finite floats, strings, booleans, lists, and dicts without stringifying numbers.
"""

import math
from datetime import datetime
from typing import Any
import numpy as np
import pandas as pd


def sanitize_for_json(obj: Any) -> Any:
    """
    Recursively converts non-finite numbers (NaN, +inf, -inf) into None (null).
    Does NOT convert valid floats or ints to strings.
    Handles dicts, lists, tuples, sets, Pydantic models, NumPy scalars/arrays, Pandas objects, and datetimes.
    """
    if obj is None:
        return None

    # Handle datetime
    if isinstance(obj, datetime):
        return obj.isoformat()

    # Handle Pydantic models
    if hasattr(obj, "model_dump") and callable(obj.model_dump):
        return sanitize_for_json(obj.model_dump())

    # Handle Pandas NA / NaT
    if pd.isna(obj) if not isinstance(obj, (list, tuple, dict, set, np.ndarray, pd.DataFrame, pd.Series)) else False:
        return None

    # Handle Python and NumPy floats
    if isinstance(obj, (float, np.floating)):
        val = float(obj)
        if math.isnan(val) or math.isinf(val):
            return None
        return val

    # Handle Python and NumPy integers
    if isinstance(obj, (int, np.integer)) and not isinstance(obj, bool):
        return int(obj)

    # Handle booleans and strings
    if isinstance(obj, (bool, str)):
        return obj

    # Handle dicts
    if isinstance(obj, dict):
        return {str(k): sanitize_for_json(v) for k, v in obj.items()}

    # Handle lists, tuples, sets, Series, Arrays
    if isinstance(obj, (list, tuple, set, np.ndarray, pd.Series)):
        return [sanitize_for_json(item) for item in obj]

    return obj
