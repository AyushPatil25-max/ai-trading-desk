from fastapi import APIRouter, Depends, HTTPException, status
from typing import List

from backend.domain.stock_comparison_schemas import StockComparisonRequest, StockComparisonResult
from backend.application.stock_comparison_engine import StockComparisonEngine
from backend.application.context_routes import get_context_service

router = APIRouter(prefix="/api/v1/stock-comparison", tags=["stock-comparison"])

def get_stock_comparison_engine(context_service = Depends(get_context_service)) -> StockComparisonEngine:
    return StockComparisonEngine(context_service=context_service)

@router.post("/compare", response_model=StockComparisonResult)
async def compare_stocks(
    request: StockComparisonRequest,
    engine: StockComparisonEngine = Depends(get_stock_comparison_engine)
):
    """
    Execute a side-by-side structured comparison for a set of symbols and metrics.
    """
    try:
        result = await engine.compare_securities(request)
        return result
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Comparison execution failed: {str(e)}"
        )
