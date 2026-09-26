import math
from typing import Dict, Any, Optional
import asyncio
import pandas as pd
from backend.infrastructure.providers.yfinance_provider import YFinanceProvider
from backend.infrastructure.providers.market_data_provider import UpstoxMarketDataProvider
from backend.infrastructure.providers.orchestrator import MultiSourceOrchestrator
from backend.infrastructure.cache import InMemoryContextCache
from backend.application.context_service import ContextService
from backend.domain.schemas import AgentInput, MarketContext, DataQualityStatus
from backend.adapters.legacy_agents import TechnicalAgentAdapter, RiskAgentAdapter
from backend.utils.json_safety import sanitize_for_json
import os

_global_cache = InMemoryContextCache(ttl_seconds=60)
_providers = [YFinanceProvider()]
if os.getenv("UPSTOX_API_KEY") and os.getenv("UPSTOX_API_KEY") != "mock":
    _providers.insert(0, UpstoxMarketDataProvider(api_key=os.getenv("UPSTOX_API_KEY")))

_global_provider = MultiSourceOrchestrator(providers=_providers)
_context_service = ContextService(_global_provider, _global_cache)

def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        if pd.isna(val):
            return None
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, 2)
    except (ValueError, TypeError):
        return None

async def analyze_symbol_application(symbol: str) -> Dict[str, Any]:
    ctx = await _context_service.get_market_context(symbol)
    
    if ctx.quality_status == DataQualityStatus.CRITICAL_FAILURE:
        return sanitize_for_json({
            "symbol": symbol,
            "market_data": {},
            "technical": {},
            "risk": {},
            "final_verdict": f"REJECTED (Critical Data Failure: {ctx.warnings})"
        })
        
    market_data_legacy = {
        "latest_close": _safe_float(ctx.current_price),
        "20_day_high": _safe_float(ctx.technical_indicators.get("20_day_high")),
        "ema20": _safe_float(ctx.technical_indicators.get("ema20")),
        "ema50": _safe_float(ctx.technical_indicators.get("ema50")),
        "rsi": _safe_float(ctx.technical_indicators.get("rsi"))
    }
    
    tech_agent = TechnicalAgentAdapter()
    risk_agent = RiskAgentAdapter()
    
    tech_input = AgentInput(symbol=symbol, market_context=ctx)
    tech_output = await tech_agent.execute(tech_input)
    
    tech_score = tech_output.raw_data.get("technical_score", 5.0) if tech_output.raw_data else 5.0
    
    risk_input = AgentInput(symbol=symbol, market_context=ctx, additional_data={"technical_score": tech_score})
    risk_output = await risk_agent.execute(risk_input)
    
    tech_raw = tech_output.raw_data or {}
    risk_raw = risk_output.raw_data or {}
    
    confirmation = tech_raw.get("confirmation", False)
    risk_level = risk_raw.get("risk_level", "HIGH")
    
    if confirmation and risk_level in ["LOW", "MEDIUM"]:
        final_verdict = f"APPROVED {tech_raw.get('trend', '')} {tech_raw.get('setup', '')}"
    else:
        final_verdict = "REJECTED (High Risk or Unconfirmed Setup)"
        
    return sanitize_for_json({
        "symbol": symbol,
        "market_data": market_data_legacy,
        "technical": tech_raw,
        "risk": risk_raw,
        "final_verdict": final_verdict
    })
