"""
Phase 29 — Strategy Governance & Management REST API Routes

FastAPI router exposing deterministic strategy management and signal evaluation endpoints:
- GET  /api/strategy/list
- GET  /api/strategy/conflicts
- GET  /api/strategy/governance/status
- GET  /api/strategy/{strategy_id}
- GET  /api/strategy/{strategy_id}/health
- POST /api/strategy/register
- POST /api/strategy/{strategy_id}/activate
- POST /api/strategy/{strategy_id}/pause
- POST /api/strategy/{strategy_id}/disable
- POST /api/strategy/{strategy_id}/quarantine
- POST /api/strategy/{strategy_id}/recover
- POST /api/strategy/signal/evaluate

Safety Invariants:
- Evaluating a signal NEVER places a broker order or arms live trading.
- Strategy activation NEVER bypasses risk, preflight, or confirmation gates.
- All requests are strictly validated. Zero secrets exposed.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.domain.strategy_schemas import (
    GovernanceStatus,
    StrategyConflictRecord,
    StrategyDecision,
    StrategyDefinition,
    StrategyHealthMetrics,
    StrategySignal,
    StrategyStatus,
)
from backend.execution.strategy_registry import global_strategy_registry
from backend.execution.strategy_governance import global_strategy_governance_engine

strategy_router = APIRouter(prefix="/api/strategy", tags=["Strategy Governance"])


# ── Request / Response DTOs ──────────────────────────────────────────────────

class QuarantineRequest(BaseModel):
    reason: str = Field(min_length=3, description="Operational or safety reason for quarantining strategy")


class RecoverRequest(BaseModel):
    operator_notes: Optional[str] = Field(default=None, description="Operator notes for recovering strategy from quarantine")


# ── Strategy Management Endpoints ─────────────────────────────────────────────

@strategy_router.get(
    "/list",
    response_model=List[StrategyDefinition],
    summary="List All Registered Strategies",
)
def list_strategies(
    status: Optional[StrategyStatus] = Query(None, description="Filter by strategy status"),
) -> List[StrategyDefinition]:
    """Return all registered strategy definitions, optionally filtered by status."""
    return global_strategy_registry.list(status_filter=status)


@strategy_router.get(
    "/governance/status",
    summary="Get Strategy Governance Operational Status",
)
def get_governance_status() -> Dict[str, Any]:
    """Return overall operational status of the strategy registry and governance engine."""
    registry_status = global_strategy_registry.status()
    engine_status = global_strategy_governance_engine.status()
    return {
        "registry": registry_status,
        "governance_engine": engine_status,
    }


@strategy_router.get(
    "/conflicts",
    response_model=List[StrategyConflictRecord],
    summary="Get Recorded Strategy Conflicts",
)
def get_strategy_conflicts() -> List[StrategyConflictRecord]:
    """Return all recorded opposing strategy conflicts."""
    return global_strategy_governance_engine.get_conflicts()


@strategy_router.get(
    "/{strategy_id}",
    response_model=StrategyDefinition,
    summary="Get Strategy Definition by ID",
)
def get_strategy(strategy_id: str) -> StrategyDefinition:
    """Retrieve strategy definition by ID."""
    strat = global_strategy_registry.get(strategy_id)
    if not strat:
        raise HTTPException(status_code=404, detail=f"Strategy '{strategy_id}' not found.")
    return strat


@strategy_router.get(
    "/{strategy_id}/health",
    response_model=StrategyHealthMetrics,
    summary="Get Strategy Health and Metrics",
)
def get_strategy_health(strategy_id: str) -> StrategyHealthMetrics:
    """Retrieve health and throughput metrics for a strategy."""
    strat = global_strategy_registry.get(strategy_id)
    if not strat:
        raise HTTPException(status_code=404, detail=f"Strategy '{strategy_id}' not found.")
    health = global_strategy_governance_engine.get_health(strategy_id)
    if not health:
        health = StrategyHealthMetrics(strategy_id=strategy_id, status=strat.status)
    return health


@strategy_router.post(
    "/register",
    response_model=StrategyDefinition,
    summary="Register a Strategy",
)
def register_strategy(strategy: StrategyDefinition) -> StrategyDefinition:
    """Register a new strategy definition or valid new version."""
    try:
        return global_strategy_registry.register(strategy)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@strategy_router.post(
    "/{strategy_id}/activate",
    summary="Activate a Strategy",
)
def activate_strategy(strategy_id: str) -> Dict[str, Any]:
    """Activate a strategy from DRAFT or PAUSED status."""
    success, msg, strat = global_strategy_registry.activate(strategy_id)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "strategy": strat}


@strategy_router.post(
    "/{strategy_id}/pause",
    summary="Pause a Strategy",
)
def pause_strategy(strategy_id: str) -> Dict[str, Any]:
    """Pause an active strategy."""
    success, msg, strat = global_strategy_registry.pause(strategy_id)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "strategy": strat}


@strategy_router.post(
    "/{strategy_id}/disable",
    summary="Disable a Strategy",
)
def disable_strategy(strategy_id: str) -> Dict[str, Any]:
    """Disable a strategy administratively."""
    success, msg, strat = global_strategy_registry.disable(strategy_id)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "strategy": strat}


@strategy_router.post(
    "/{strategy_id}/quarantine",
    summary="Quarantine a Strategy",
)
def quarantine_strategy(strategy_id: str, req: QuarantineRequest) -> Dict[str, Any]:
    """Quarantine a strategy immediately, blocking all signal generation."""
    success, msg, strat = global_strategy_registry.quarantine(strategy_id, reason=req.reason)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "strategy": strat}


@strategy_router.post(
    "/{strategy_id}/recover",
    summary="Recover a Quarantined Strategy",
)
def recover_strategy(strategy_id: str, req: Optional[RecoverRequest] = None) -> Dict[str, Any]:
    """Recover a quarantined strategy back to PAUSED status upon operator review."""
    notes = req.operator_notes if req else None
    success, msg, strat = global_strategy_registry.recover(strategy_id, operator_notes=notes)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "strategy": strat}


# ── Signal Governance Evaluation Endpoint ─────────────────────────────────────

@strategy_router.post(
    "/signal/evaluate",
    response_model=StrategyDecision,
    summary="Evaluate Strategy Signal for Admissibility",
)
def evaluate_strategy_signal(signal: StrategySignal) -> StrategyDecision:
    """
    Deterministically evaluate an incoming StrategySignal against the 17 governance checks.
    
    IMPORTANT: This endpoint produces a StrategyDecision ONLY.
    It does NOT place a broker order, does NOT arm live trading, and does NOT bypass risk or confirmation.
    """
    return global_strategy_governance_engine.evaluate_signal(signal)
