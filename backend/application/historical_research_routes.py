from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Any

from backend.domain.backtest_schemas import (
    BacktestConfig,
    SingleDecisionBacktestResult,
)
from backend.application.historical_research_service import (
    HistoricalResearchService,
    HistoricalResearchRequest
)

router = APIRouter(prefix="/api/historical-research", tags=["Historical Research"])

def get_historical_research_service() -> HistoricalResearchService:
    return HistoricalResearchService()

@router.post("/run", response_model=SingleDecisionBacktestResult)
async def run_historical_research(
    request: HistoricalResearchRequest,
    service: HistoricalResearchService = Depends(get_historical_research_service)
):
    """Run a new historical research / backtest"""
    try:
        result = await service.run_historical_research(request)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to run historical research: {str(e)}")

@router.get("/results", response_model=List[Dict[str, Any]])
async def list_historical_results(
    service: HistoricalResearchService = Depends(get_historical_research_service)
):
    """List all completed historical research results"""
    return service.list_results()

@router.get("/results/{backtest_id}", response_model=SingleDecisionBacktestResult)
async def get_historical_result(
    backtest_id: str,
    service: HistoricalResearchService = Depends(get_historical_research_service)
):
    """Get full details of a specific historical research result"""
    result = service.get_result(backtest_id)
    if not result:
        raise HTTPException(status_code=404, detail="Historical research result not found")
    return result
