import logging
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional

from backend.domain.chart_schemas import ChartResponse
from backend.application.chart_service import ChartService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/charts", tags=["charts"])

def get_chart_service():
    return ChartService()

@router.get("/{symbol}", response_model=ChartResponse)
async def get_chart_data(
    symbol: str,
    timeframe: str = Query("1D", description="1m, 5m, 15m, 30m, 1h, 1D, 1W"),
    service: ChartService = Depends(get_chart_service)
):
    valid_tfs = ["1m", "5m", "15m", "30m", "1h", "1D", "1W"]
    if timeframe not in valid_tfs:
        raise HTTPException(status_code=400, detail=f"Invalid timeframe. Must be one of {valid_tfs}")
        
    try:
        response = await service.get_chart_data(symbol, timeframe)
        if not response:
            raise HTTPException(status_code=404, detail="Symbol not found")
        return response
    except Exception as e:
        logger.error(f"Error serving chart data for {symbol}: {e}")
        raise HTTPException(status_code=500, detail="Internal chart processing error")
