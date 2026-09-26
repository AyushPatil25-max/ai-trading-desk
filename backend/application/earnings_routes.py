from fastapi import APIRouter, Query, HTTPException
from backend.application.earnings_engine import get_earnings_engine
from backend.domain.earnings_schemas import EarningsResponse, EarningsEventStatus

router = APIRouter(prefix="/api/v1/earnings", tags=["Earnings Intelligence"])

@router.get("/{symbol}/calendar", response_model=EarningsResponse)
async def get_earnings_calendar(symbol: str):
    engine = get_earnings_engine()
    res = await engine.get_earnings_calendar(symbol)
    if res.status == EarningsEventStatus.PROVIDER_ERROR:
        # We still return the object, frontend will check status
        pass
    return res

@router.get("/{symbol}/results", response_model=EarningsResponse)
async def get_earnings_results(symbol: str):
    engine = get_earnings_engine()
    res = await engine.get_earnings_results(symbol)
    return res
