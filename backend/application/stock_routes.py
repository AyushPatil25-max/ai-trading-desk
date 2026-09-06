import logging
import asyncio
from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional

from backend.domain.stock_schemas import StockFundamentalData, StockTechnicalData, StockAnalysisResult, StockScreenerResult, StockDecision
from backend.infrastructure.security_master import get_security_master
from backend.infrastructure.providers.market_data_provider import get_market_data_provider
from backend.application.stock_analysis_engine import StockAnalysisEngine
from backend.application.stock_screener import StockScreener
from backend.infrastructure.stock_repository import get_stock_repository
from datetime import datetime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/stocks", tags=["Stocks"])

@router.get("/search")
async def search_stocks(query: str, limit: int = 20):
    sm = get_security_master()
    results = []
    query = query.lower()
    for sec in sm.list_securities():
        if query in sec.canonical_symbol.lower() or query in sec.company_name.lower():
            results.append(sec)
        if len(results) >= limit:
            break
    return results

@router.get("/{symbol}/analysis", response_model=StockAnalysisResult)
async def get_stock_analysis(symbol: str):
    sm = get_security_master()
    sec = sm.resolve_symbol(symbol)
    can_sym = sec.canonical_symbol if sec else symbol
    
    repo = get_stock_repository()
    cached = repo.get_analysis(can_sym)
    if cached and cached.decision != StockDecision.INSUFFICIENT_DATA:
        return cached
        
    provider = get_market_data_provider()
    engine = StockAnalysisEngine()
    
    fundamental = await provider.get_fundamentals(can_sym)
    technical = await provider.get_technicals(can_sym)
    
    analysis = await engine.analyze_stock(can_sym, fundamental, technical)
    if fundamental and getattr(fundamental, 'pe', None) is not None:
        repo.save_fundamental(fundamental)
    if technical and technical.current_price:
        repo.save_technical(technical)
    if analysis.decision != StockDecision.INSUFFICIENT_DATA:
        repo.save_analysis(analysis)
        
    return analysis

@router.get("/{symbol}/fundamentals", response_model=Optional[StockFundamentalData])
async def get_stock_fundamentals(symbol: str):
    sm = get_security_master()
    sec = sm.resolve_symbol(symbol)
    can_sym = sec.canonical_symbol if sec else symbol
    repo = get_stock_repository()
    cached = repo.get_fundamental(can_sym)
    if cached: return cached
    provider = get_market_data_provider()
    fundamental = await provider.get_fundamentals(can_sym)
    if not fundamental:
        return StockFundamentalData(symbol=can_sym, company_name=sec.company_name if sec else symbol)
    repo.save_fundamental(fundamental)
    return fundamental

@router.get("/{symbol}/technicals", response_model=Optional[StockTechnicalData])
async def get_stock_technicals(symbol: str):
    sm = get_security_master()
    sec = sm.resolve_symbol(symbol)
    can_sym = sec.canonical_symbol if sec else symbol
    repo = get_stock_repository()
    cached = repo.get_technical(can_sym)
    if cached: return cached
    provider = get_market_data_provider()
    technical = await provider.get_technicals(can_sym)
    if not technical:
        return StockTechnicalData(symbol=can_sym)
    repo.save_technical(technical)
    return technical

@router.get("/screener/undervalued", response_model=List[StockScreenerResult])
async def get_undervalued_stocks(limit: int = 50):
    screener = StockScreener()
    results = await screener.screen_undervalued_strong_fundamentals(limit=limit)
    return results

@router.get("/market/status")
async def get_market_status():
    from backend.application.market_data_gateway import get_market_data_gateway
    gateway = get_market_data_gateway()
    
    status = "CLOSED"
    if gateway.upstox_client and gateway.upstox_client.status == "CONNECTED":
        status = "OPEN"
    elif gateway.upstox_client and gateway.upstox_client.status == "RECONNECTING":
        status = "DEGRADED"
        
    return {
        "status": status,
        "nifty": {"price": 0, "change": 0, "pct": 0},
        "sensex": {"price": 0, "change": 0, "pct": 0},
        "provider": "upstox"
    }
