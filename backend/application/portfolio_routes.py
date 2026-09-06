from fastapi import APIRouter, HTTPException, Depends
from backend.domain.portfolio_schemas import PortfolioResponse, PortfolioAIInsight
from backend.application.portfolio_engine import get_portfolio_engine, PortfolioIntelligenceEngine

router = APIRouter(prefix="/api/v1/portfolio", tags=["Portfolio Intelligence"])

def get_engine() -> PortfolioIntelligenceEngine:
    return get_portfolio_engine()

@router.get("", response_model=PortfolioResponse)
async def get_portfolio(engine: PortfolioIntelligenceEngine = Depends(get_engine)):
    return engine.get_portfolio()

@router.get("/ai-analysis", response_model=PortfolioAIInsight)
async def get_portfolio_ai_analysis(engine: PortfolioIntelligenceEngine = Depends(get_engine)):
    port_resp = engine.get_portfolio()
    if not port_resp.data:
        raise HTTPException(status_code=404, detail="Portfolio data unavailable")
    return await engine.generate_ai_analysis(port_resp.data)

