from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional

from backend.domain.intelligent_screener_schemas import ScreenerRequest, ScreenerResponse
from backend.application.intelligent_screener_engine import IntelligentScreenerEngine
from backend.application.context_routes import get_context_service

router = APIRouter(prefix="/api/v1/intelligent-screener", tags=["intelligent-screener"])

def get_intelligent_screener_engine(context_service = Depends(get_context_service)) -> IntelligentScreenerEngine:
    return IntelligentScreenerEngine(context_service=context_service)

@router.post("/execute", response_model=ScreenerResponse)
async def execute_screen(
    request: ScreenerRequest,
    engine: IntelligentScreenerEngine = Depends(get_intelligent_screener_engine)
):
    """
    Execute an intelligent screen against a universe based on structured criteria.
    """
    try:
        result = await engine.execute_screen(request)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Screener execution failed: {str(e)}"
        )
