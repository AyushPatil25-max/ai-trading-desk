"""
Phase 12 — Live Forward Simulation & Paper-Trading REST API Endpoints

Provides HTTP endpoints to start, stop, pause, resume, inspect, and inject
forward market ticks into the Phase 12 Live Forward Simulation Engine.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.domain.forward_simulation_schemas import (
    FORWARD_SIMULATION_VERSION,
    ForwardSimulationMode,
    ForwardEngineState,
    MarketSessionState,
    MarketDataTick,
    ForwardSimulationConfig,
    ForwardSessionSummary,
)
from backend.application.forward_simulation_engine import (
    global_forward_engine,
    global_forward_worker,
    get_market_session_state,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/forward", tags=["Live Forward Paper Trading"])


class StartForwardRequest(BaseModel):
    config: Optional[ForwardSimulationConfig] = None


class ForwardCycleRequest(BaseModel):
    symbols: Optional[List[str]] = None


@router.post("/start", response_model=ForwardSessionSummary)
def start_forward_simulation(request: Optional[StartForwardRequest] = None):
    """Start continuous live forward paper-trading simulation in background worker."""
    if request and request.config:
        global_forward_engine.config = request.config
    
    session = global_forward_worker.start()
    return session


@router.post("/stop", response_model=ForwardSessionSummary)
def stop_forward_simulation():
    """Safely stop continuous live forward paper-trading simulation."""
    session = global_forward_worker.stop()
    return session


@router.post("/pause", response_model=ForwardSessionSummary)
def pause_forward_simulation():
    """Pause continuous live forward paper-trading simulation."""
    session = global_forward_worker.pause()
    return session


@router.post("/resume", response_model=ForwardSessionSummary)
def resume_forward_simulation():
    """Resume paused live forward paper-trading simulation."""
    session = global_forward_worker.resume()
    return session


@router.get("/status")
def get_forward_status():
    """Retrieve operational status, market session state, and session summary."""
    sess_state, sess_reason = get_market_session_state(
        enforce_calendar=global_forward_engine.config.market_hours_enforced
    )
    summary = global_forward_engine.get_session_summary()
    
    return {
        "engine_version": FORWARD_SIMULATION_VERSION,
        "worker_alive": global_forward_worker.is_alive,
        "engine_state": summary.state.value,
        "mode": global_forward_engine.config.mode.value,
        "session_state": sess_state.value,
        "session_reason": sess_reason,
        "ticks_processed": summary.ticks_processed,
        "cycles_completed": summary.cycles_completed,
        "candidates_discovered": summary.candidates_discovered,
        "approved_orders": summary.approved_orders,
        "rejected_orders": summary.rejected_orders,
        "simulated_fills": summary.simulated_fills,
        "cash_balance": summary.cash_balance,
        "total_equity": summary.total_equity,
        "open_positions_count": summary.open_positions_count,
        "realized_pnl": summary.realized_pnl,
        "unrealized_pnl": summary.unrealized_pnl,
        "errors_count": summary.errors_count,
    }


@router.post("/tick")
def ingest_market_tick(tick: MarketDataTick):
    """Ingest and validate an incoming forward market price update."""
    success, message, ctx = global_forward_engine.ingest_tick(tick)
    if not success:
        return {
            "status": "REJECTED",
            "message": message,
            "tick_id": tick.tick_id,
            "symbol": tick.symbol,
            "session_state": tick.session_state.value,
            "is_stale": tick.is_stale,
        }
    return {
        "status": "INGESTED",
        "message": message,
        "tick_id": tick.tick_id,
        "symbol": tick.symbol,
        "context_id": ctx.context_id if ctx else None,
        "current_price": tick.price,
        "session_state": tick.session_state.value,
    }


@router.post("/cycle")
def execute_manual_forward_cycle(request: Optional[ForwardCycleRequest] = None):
    """Execute a single forward paper-trading cycle on-demand."""
    symbols = request.symbols if request else None
    result = global_forward_engine.execute_forward_cycle(specific_symbols=symbols)
    return result


@router.get("/session", response_model=ForwardSessionSummary)
def get_current_session():
    """Retrieve full audit summary and recent lifecycle events for the active forward session."""
    return global_forward_engine.get_session_summary()
