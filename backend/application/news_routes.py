from fastapi import APIRouter, HTTPException, Query, Path, Body
from typing import List, Optional, Any, Dict
from datetime import datetime, timezone
import uuid

from backend.domain.news_schemas import (
    NewsItem, NewsCategory, SentimentState, ImportanceLevel, 
    EventItem, AlertRule, AlertEvent, AlertState, NewsResponse
)
from backend.application.news_engine import get_news_engine

router = APIRouter(prefix="/api/v1", tags=["News & Events"])

@router.get("/news", response_model=NewsResponse[NewsItem])
async def get_news_global(
    limit: int = Query(50, ge=1, le=200),
    symbol: Optional[str] = None
):
    # For now, just uses the symbol logic if provided, otherwise returns UNAVAILABLE
    engine = get_news_engine()
    if symbol:
        return await engine.get_company_news(symbol, limit)
    return NewsResponse(state="SUCCESS_EMPTY", data=[])

@router.get("/news/{symbol}", response_model=NewsResponse[NewsItem])
async def get_news_for_symbol(
    symbol: str, 
    limit: int = Query(50, ge=1, le=200)
):
    engine = get_news_engine()
    return await engine.get_company_news(symbol, limit)

@router.get("/events", response_model=NewsResponse[EventItem])
async def get_events_global(symbol: Optional[str] = None):
    engine = get_news_engine()
    if symbol:
        return await engine.get_corporate_actions(symbol)
    return NewsResponse(state="SUCCESS_EMPTY", data=[])

@router.get("/events/{symbol}", response_model=NewsResponse[EventItem])
async def get_events_for_symbol(symbol: str):
    engine = get_news_engine()
    return await engine.get_corporate_actions(symbol)

@router.get("/alerts", response_model=List[AlertRule])
async def get_alerts():
    engine = get_news_engine()
    return engine.get_alert_rules()

@router.post("/alerts", response_model=AlertRule)
async def create_alert(rule: AlertRule):
    engine = get_news_engine()
    if not rule.id:
        rule.id = str(uuid.uuid4())
    rule.created_at = datetime.now(timezone.utc).isoformat()
    return engine.create_alert_rule(rule)

@router.patch("/alerts/{id}", response_model=AlertRule)
async def patch_alert(id: str, updates: Dict[str, Any] = Body(...)):
    engine = get_news_engine()
    res = engine.update_alert_rule(id, updates)
    if not res:
        raise HTTPException(status_code=404, detail="Alert not found")
    return res

@router.delete("/alerts/{id}")
async def delete_alert(id: str):
    engine = get_news_engine()
    if engine.delete_alert_rule(id):
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Alert not found")
