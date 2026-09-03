"""
Phase 9 — End-to-End Trading OS API Routes

FastAPI router exposing endpoints to trigger and query unified simulated Trading OS execution runs.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.domain.schemas import MarketContext
from backend.domain.trading_os_schemas import (
    TradingOSRun,
    TradingOSRunSummary,
)
from backend.application.trading_os_orchestrator import TradingOSOrchestrator


router = APIRouter(prefix="/api/trading-os", tags=["Trading OS Orchestrator"])

# Global shared orchestrator instance and run store
global_orchestrator = TradingOSOrchestrator()
_runs_history: Dict[str, TradingOSRun] = {}


class RunPipelineRequest(BaseModel):
    symbol: str = "TCS.NS"
    current_price: float = 3500.0
    fill_ratio: float = 1.0


@router.post("/run", response_model=TradingOSRunSummary)
def run_trading_os(req: RunPipelineRequest):
    """Execute a complete simulated end-to-end Trading OS cycle (PAPER_ONLY)."""
    now = datetime.now(timezone.utc)
    ctx = MarketContext(
        symbol=req.symbol,
        current_price=req.current_price,
        data_timestamp=now,
        provider="NSE",
        context_id=f"ctx-{req.symbol}-{int(now.timestamp())}",
    )

    run = global_orchestrator.run_pipeline(
        market_context=ctx,
        fill_ratio=req.fill_ratio,
        evaluation_timestamp=now,
    )

    _runs_history[run.run_id] = run
    return global_orchestrator.get_summary(run)


@router.get("/runs/latest", response_model=Optional[TradingOSRun])
def get_latest_run():
    """Retrieve full audit record of the most recent Trading OS run."""
    if not _runs_history:
        return None
    return list(_runs_history.values())[-1]


@router.get("/runs/{run_id}", response_model=TradingOSRun)
def get_run(run_id: str):
    """Retrieve full audit record of a specific Trading OS run."""
    if run_id not in _runs_history:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found.")
    return _runs_history[run_id]


@router.get("/runs", response_model=List[TradingOSRunSummary])
def list_runs(limit: int = Query(default=20, ge=1, le=100)):
    """List summary records of recent Trading OS runs."""
    runs = list(_runs_history.values())[-limit:]
    return [global_orchestrator.get_summary(r) for r in reversed(runs)]
