"""
institutional_calculator.py — Phase 2.4D

Pure Python deterministic financial calculator for institutional flow and ownership.
Zero external network calls, zero LLM dependency.
"""

from typing import Optional

def _clean_number(val) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        import math
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None

def calc_net_flow(buy_value: Optional[float], sell_value: Optional[float]) -> Optional[float]:
    """
    Net Flow = buy_value - sell_value
    """
    buy = _clean_number(buy_value)
    sell = _clean_number(sell_value)
    
    if buy is None or sell is None:
        return None
        
    return buy - sell

def calc_ownership_change(current_pct: Optional[float], previous_pct: Optional[float]) -> Optional[float]:
    """
    Change in ownership = current - previous
    """
    current = _clean_number(current_pct)
    previous = _clean_number(previous_pct)
    
    if current is None or previous is None:
        return None
        
    return current - previous

def calc_delivery_percentage(delivery_qty: Optional[float], traded_qty: Optional[float]) -> Optional[float]:
    """
    Delivery % = (delivery_quantity / traded_quantity) * 100
    Validates range 0-100.
    """
    delivery = _clean_number(delivery_qty)
    traded = _clean_number(traded_qty)
    
    if delivery is None or traded is None or traded <= 0:
        return None
        
    if delivery < 0:
        return None
        
    pct = (delivery / traded) * 100.0
    if pct > 100.0:
        return 100.0
    return pct

def validate_percentage(val: Optional[float]) -> Optional[float]:
    """Ensure a percentage is between 0 and 100."""
    v = _clean_number(val)
    if v is None or v < 0 or v > 100:
        return None
    return v

def validate_quantity(val: Optional[float]) -> Optional[float]:
    """Ensure a quantity or value is non-negative."""
    v = _clean_number(val)
    if v is None or v < 0:
        return None
    return v

def calc_promoter_pledge_risk(pledge_pct: Optional[float]) -> str:
    """
    Classify promoter pledge risk based on SEBI / Indian equity norms.
    < 10%: LOW, 10-30%: MODERATE, >= 30%: HIGH.
    """
    p = _clean_number(pledge_pct)
    if p is None:
        return "UNKNOWN"
    if p == 0.0:
        return "NONE"
    if p < 10.0:
        return "LOW"
    if p < 30.0:
        return "MODERATE"
    return "HIGH"

def calc_ownership_distribution(ownership_list: list) -> dict:
    """
    Extract latest percentage holdings by holder type.
    """
    res = {
        "promoter": None,
        "fii": None,
        "dii": None,
        "mutual_fund": None,
        "public": None,
        "other_institution": None,
    }
    if not ownership_list:
        return res

    for obs in ownership_list:
        h_type = getattr(obs, "holder_type", None) or (obs.get("holder_type") if isinstance(obs, dict) else None)
        pct = getattr(obs, "ownership_percentage", None) or (obs.get("ownership_percentage") if isinstance(obs, dict) else None)
        pct_clean = _clean_number(pct)
        if pct_clean is None:
            continue

        h_str = str(h_type).upper()
        if "PROMOTER" in h_str:
            res["promoter"] = pct_clean
        elif "FII" in h_str or "FPI" in h_str:
            res["fii"] = pct_clean
        elif "DII" in h_str:
            res["dii"] = pct_clean
        elif "MUTUAL_FUND" in h_str:
            res["mutual_fund"] = pct_clean
        elif "PUBLIC" in h_str:
            res["public"] = pct_clean
        elif "OTHER_INSTITUTION" in h_str:
            res["other_institution"] = pct_clean

    return res

