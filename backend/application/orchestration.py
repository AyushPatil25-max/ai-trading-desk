from typing import Dict, Any
import asyncio
from backend.infrastructure.data_providers import YFinanceProvider
from backend.infrastructure.cache import InMemoryContextCache
from backend.application.context_service import ContextService
from backend.domain.schemas import AgentInput, MarketContext, DataQualityStatus
from backend.adapters.legacy_agents import TechnicalAgentAdapter, RiskAgentAdapter

_global_cache = InMemoryContextCache(ttl_seconds=60)
_global_provider = YFinanceProvider()
_context_service = ContextService(_global_provider, _global_cache)

async def analyze_symbol_application(symbol: str) -> Dict[str, Any]:
    ctx = await _context_service.get_market_context(symbol)
    
    if ctx.quality_status == DataQualityStatus.CRITICAL_FAILURE:
        return {
            "symbol": symbol,
            "market_data": {},
            "technical": {},
            "risk": {},
            "final_verdict": f"REJECTED (Critical Data Failure: {ctx.warnings})"
        }
        
    market_data_legacy = {
        "latest_close": ctx.current_price,
        "20_day_high": ctx.technical_indicators.get("20_day_high", 0.0),
        "ema20": ctx.technical_indicators.get("ema20", 0.0),
        "ema50": ctx.technical_indicators.get("ema50", 0.0),
        "rsi": ctx.technical_indicators.get("rsi", 0.0)
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
        
    return {
        "symbol": symbol,
        "market_data": market_data_legacy,
        "technical": tech_raw,
        "risk": risk_raw,
        "final_verdict": final_verdict
    }
