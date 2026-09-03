from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
import asyncio

from backend.domain.stock_schemas import StockFundamentalData, StockTechnicalData, StockAnalysisResult, StockScreenerResult
from backend.infrastructure.security_master import get_security_master
from backend.infrastructure.providers.market_data_provider import PublicMarketDataProvider
from backend.application.stock_analysis_engine import StockAnalysisEngine
from backend.application.stock_screener import StockScreener
from backend.infrastructure.stock_repository import get_stock_repository

router = APIRouter(prefix="/api/v1/stocks", tags=["Stocks"])

@router.get("/search")
async def search_stocks(query: str, limit: int = 20):
    sm = get_security_master()
    # Assuming symbol search or name search
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
    repo = get_stock_repository()
    cached = repo.get_analysis(symbol)
    if cached:
        return cached
        
    # Generate on the fly
    provider = PublicMarketDataProvider()
    engine = StockAnalysisEngine()
    
    fundamental = await provider.get_fundamentals(symbol)
    technical = await provider.get_technicals(symbol)
    
    if not fundamental or not technical:
        raise HTTPException(status_code=404, detail="Stock data not found or insufficient")
        
    analysis = await engine.analyze_stock(symbol, fundamental, technical)
    repo.save_fundamental(fundamental)
    repo.save_technical(technical)
    repo.save_analysis(analysis)
    
    return analysis

@router.get("/{symbol}/fundamentals", response_model=StockFundamentalData)
async def get_stock_fundamentals(symbol: str):
    repo = get_stock_repository()
    cached = repo.get_fundamental(symbol)
    if cached: return cached
    provider = PublicMarketDataProvider()
    fundamental = await provider.get_fundamentals(symbol)
    if not fundamental: raise HTTPException(status_code=404, detail="Not found")
    repo.save_fundamental(fundamental)
    return fundamental

@router.get("/{symbol}/technicals", response_model=StockTechnicalData)
async def get_stock_technicals(symbol: str):
    repo = get_stock_repository()
    cached = repo.get_technical(symbol)
    if cached: return cached
    provider = PublicMarketDataProvider()
    technical = await provider.get_technicals(symbol)
    if not technical: raise HTTPException(status_code=404, detail="Not found")
    repo.save_technical(technical)
    return technical

@router.get("/screener/undervalued", response_model=List[StockScreenerResult])
async def get_undervalued_stocks(limit: int = 50):
    screener = StockScreener()
    results = await screener.screen_undervalued_strong_fundamentals(limit=limit)
    return results

@router.get("/market/status")
async def get_market_status():
    import yfinance as yf
    try:
        nifty = yf.Ticker("^NSEI").history(period="2d")
        sensex = yf.Ticker("^BSESN").history(period="2d")
        
        def format_index(hist):
            if len(hist) < 2: return {"price": 0, "change": 0, "pct": 0}
            curr = hist['Close'].iloc[-1]
            prev = hist['Close'].iloc[-2]
            return {
                "price": curr,
                "change": curr - prev,
                "pct": ((curr - prev) / prev) * 100
            }
            
        return {
            "status": "OPEN",
            "nifty": format_index(nifty),
            "sensex": format_index(sensex)
        }
    except Exception as e:
        return {"status": "DEGRADED", "error": str(e)}
