from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from backend.application.context_service import ContextService
from backend.infrastructure.cache import InMemoryContextCache
from backend.infrastructure.data_providers import MarketDataProvider
from backend.domain.schemas import HistoricalWindow

context_router = APIRouter()

def get_context_service() -> ContextService:
    from backend.application.orchestration import _context_service
    return _context_service

@context_router.get("/status")
async def get_context_status(service: ContextService = Depends(get_context_service)):
    cache = service.cache
    if hasattr(cache, "get_stats"):
        stats = cache.get_stats()
    else:
        stats = {"status": "Cache stats not available"}
        
    return {
        "status": "HEALTHY",
        "cache_stats": stats,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@context_router.get("/{symbol}")
async def get_symbol_context(
    symbol: str, 
    window: HistoricalWindow = Query(default=HistoricalWindow.RECENT),
    service: ContextService = Depends(get_context_service)
):
    try:
        context = await service.get_market_context(symbol, window)
        return {
            "snapshot_id": getattr(context, "snapshot_id", "MISSING"),
            "symbol": context.symbol,
            "freshness_status": getattr(context, "freshness_status", "UNKNOWN"),
            "completeness_status": getattr(context, "completeness_status", "UNKNOWN"),
            "cache_hit": getattr(context, "cache_hit", False),
            "timestamp": context.data_timestamp.isoformat(),
            "source_provider": context.source_provider,
            "context_summary": {
                "current_price": context.current_price,
                "ohlcv_points": len(context.ohlcv_historical)
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@context_router.post("/invalidate")
async def invalidate_context(
    symbol: str, 
    window: HistoricalWindow = Query(default=HistoricalWindow.RECENT),
    service: ContextService = Depends(get_context_service)
):
    key = service._generate_cache_key(symbol, window)
    await service.cache.invalidate(key)
    return {"status": "INVALIDATED", "symbol": symbol, "window": window.value, "key": key}
