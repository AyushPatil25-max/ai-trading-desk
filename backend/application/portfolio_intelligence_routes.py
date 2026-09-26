from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any, Optional

from backend.domain.portfolio_schemas import PortfolioIntelligence
from backend.application.portfolio_intelligence_engine import PortfolioIntelligenceEngine
from backend.application.context_service import ContextService

router = APIRouter(prefix="/api/v1/portfolio/intelligence", tags=["Portfolio Intelligence"])

def get_engine() -> PortfolioIntelligenceEngine:
    return PortfolioIntelligenceEngine()

def get_context_service() -> ContextService:
    from backend.application.orchestration import _context_service
    return _context_service

@router.get("", response_model=PortfolioIntelligence)
async def get_portfolio_intelligence(
    engine: PortfolioIntelligenceEngine = Depends(get_engine),
    context_service = Depends(get_context_service)
):
    # In a real environment, we'd fetch portfolio state from BrokerManager.
    # For now, per Phase 17 limits (Execution freeze), we fetch mocked/stored portfolio state
    # or build it directly from context if it's available.
    
    # We will get cached positions from account_sync_service
    from backend.execution.account_sync_service import global_account_sync_service
    
    positions_raw = global_account_sync_service.get_cached_positions()
    holdings_raw = global_account_sync_service.get_cached_holdings()
    acc_state = global_account_sync_service.get_cached_account()
    
    # Build a simple portfolio_state dictionary
    portfolio_state: Dict[str, Any] = {
        "portfolio_id": acc_state.account_id if acc_state else "port-001",
        "total_equity": 0.0,
        "cash": acc_state.cash if acc_state else 0.0,
        "positions": {}
    }
    
    if holdings_raw:
        for h in holdings_raw:
            sym = h.get("tradingSymbol") or h.get("symbol")
            if not sym: continue
            qty = h.get("quantity") or h.get("t1Quantity", 0) + h.get("t2Quantity", 0) + h.get("collateralQuantity", 0)
            avg = h.get("averagePrice") or 0.0
            
            portfolio_state["positions"][sym] = {
                "quantity": qty,
                "average_price": avg,
            }
            
    # For any positions, try to load context
    portfolio_contexts = {}
    for sym in portfolio_state["positions"].keys():
        ctx = await context_service.get_context(sym)
        portfolio_contexts[sym] = ctx
        
        # update current price based on context if available
        if ctx and hasattr(ctx, "current_price"):
            portfolio_state["positions"][sym]["current_price"] = ctx.current_price
            
    # calculate total equity based on prices
    total_mkt = 0.0
    for sym, pos in portfolio_state["positions"].items():
        qty = pos.get("quantity", 0)
        curr_p = pos.get("current_price", pos.get("average_price", 0))
        mkt_val = qty * curr_p
        pos["market_value"] = mkt_val
        total_mkt += mkt_val
        
    portfolio_state["total_equity"] = total_mkt + portfolio_state["cash"]
    
    intel = engine.analyze_portfolio(
        portfolio_state=portfolio_state,
        portfolio_contexts=portfolio_contexts
    )
    return intel
