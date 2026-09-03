"""
Phase 22 — System Resilience & Recovery REST API Routes

Operational and telemetry endpoints for monitoring resilience status, subsystem health,
circuit breakers, recovery histories, and automated resilience scorecards.

Safety Invariant:
- STRICTLY OBSERVATIONAL: Zero order submission authority.
- Failure injection endpoint is test/simulation only; completely isolated from real trading.
- TIER_4_LIVE_REAL_MONEY remains permanently locked and fail-closed.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.domain.resilience_schemas import (
    FailureDomainType,
    ResilienceComponent,
)
from backend.application.health_supervisor import global_health_supervisor
from backend.application.recovery_orchestrator import global_recovery_orchestrator
from backend.application.resilience_engine import global_resilience_engine
from backend.application.resilience_fault_injector import global_resilience_fault_injector

logger = logging.getLogger(__name__)

resilience_router = APIRouter(prefix="/api/resilience", tags=["System Resilience & Recovery"])


# ── Request Models ────────────────────────────────────────────────────────────

class SimulateFailureRequest(BaseModel):
    """Test/simulation-only failure injection request payload."""
    fault_type: str = Field(..., description="Target FailureDomainType string")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Simulation parameters")
    auto_recover: bool = Field(default=True, description="Whether to trigger automated recovery workflow")


# ── Resilience Status Summary ─────────────────────────────────────────────────

@resilience_router.get("/status")
def get_resilience_status() -> Dict[str, Any]:
    """Return overall operational resilience status snapshot."""
    summary = global_recovery_orchestrator.get_status_summary()
    return summary.model_dump(mode="json")


# ── Component Health Supervisor Matrix ────────────────────────────────────────

@resilience_router.get("/components")
def get_component_health() -> Dict[str, Any]:
    """Return health records across all 10 supervised subsystems."""
    components = global_health_supervisor.get_all_component_records()
    return {
        "total_components": len(components),
        "components": {k: v.model_dump(mode="json") for k, v in components.items()},
    }


# ── Active & Historic Failure Events ──────────────────────────────────────────

@resilience_router.get("/failures")
def get_failure_events(
    active_only: bool = Query(default=True, description="Return only currently active failures"),
    limit: int = Query(default=50, ge=1, le=500, description="Max history events to return"),
) -> Dict[str, Any]:
    """Retrieve active or historic failure events with correlation IDs."""
    if active_only:
        events = global_resilience_engine.get_active_failures()
    else:
        events = global_resilience_engine.get_failure_history(limit=limit)

    return {
        "count": len(events),
        "failures": [e.model_dump(mode="json") for e in events],
    }


# ── Automated Recovery History ────────────────────────────────────────────────

@resilience_router.get("/recoveries")
def get_recovery_history(
    limit: int = Query(default=50, ge=1, le=500, description="Max recovery history to return"),
) -> Dict[str, Any]:
    """Retrieve history of executed automated recovery workflows."""
    actions = global_resilience_engine.get_recovery_history(limit=limit)
    return {
        "count": len(actions),
        "recoveries": [a.model_dump(mode="json") for a in actions],
    }


# ── Operational Resilience Metrics ────────────────────────────────────────────

@resilience_router.get("/metrics")
def get_resilience_metrics() -> Dict[str, Any]:
    """Retrieve performance metrics: MTTR, circuit breaker states, and retry stats."""
    summary = global_recovery_orchestrator.get_status_summary()
    circuits = {
        name: cb.state.value for name, cb in global_resilience_engine._circuit_breakers.items()
    }
    return {
        "mean_recovery_time_ms": summary.mean_recovery_time_ms,
        "total_recoveries_executed": summary.total_recoveries_executed,
        "active_failures_count": summary.active_failures_count,
        "open_circuits_count": summary.open_circuits_count,
        "circuit_states": circuits,
        "live_trading_permanently_locked": True,
    }


# ── Automated Resilience Scorecard ────────────────────────────────────────────

@resilience_router.get("/scorecard")
def get_resilience_scorecard() -> Dict[str, Any]:
    """Evaluate and return the empirical Resilience Scorecard."""
    scorecard = global_recovery_orchestrator.generate_resilience_scorecard()
    return scorecard.model_dump(mode="json")


# ── Circuit Breaker Reset ─────────────────────────────────────────────────────

@resilience_router.post("/circuits/reset")
def reset_circuit_breakers() -> Dict[str, Any]:
    """Operator endpoint to manually reset all circuit breakers to CLOSED."""
    global_resilience_engine.reset_all_circuits()
    return {
        "status": "reset",
        "message": "All service circuit breakers manually reset to CLOSED.",
    }


# ── Test/Simulation Failure Injection (Step 6 / 11) ───────────────────────────

@resilience_router.post("/simulate-failure")
def simulate_failure(request: SimulateFailureRequest) -> Dict[str, Any]:
    """
    Simulation/test-only endpoint for injecting faults and exercising recovery workflows.
    Strictly fail-closed: zero execution authority or live broker access.
    """
    try:
        fault_enum = FailureDomainType(request.fault_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid fault_type '{request.fault_type}'. Must be one of {[e.value for e in FailureDomainType]}",
        )

    # Activate fault
    global_resilience_fault_injector.activate_fault(fault_enum, request.metadata)

    recovery_result = None
    if request.auto_recover:
        # Trigger relevant recovery workflow based on fault type
        if fault_enum == FailureDomainType.STREAM_DISCONNECT:
            recovery_result = global_recovery_orchestrator.recover_stream_disconnect()
        elif fault_enum == FailureDomainType.WORKER_FAILURE:
            sym = request.metadata.get("symbol", "TCS.NS")
            recovery_result = global_recovery_orchestrator.recover_worker_failure(symbol=sym)
        elif fault_enum == FailureDomainType.BROKER_SANDBOX_FAILURE:
            recovery_result = global_recovery_orchestrator.recover_broker_sandbox_failure()
        elif fault_enum == FailureDomainType.MODEL_FAILURE:
            recovery_result = global_recovery_orchestrator.recover_model_failure()

        # Deactivate fault after workflow exercises
        global_resilience_fault_injector.deactivate_fault(fault_enum)

    return {
        "status": "simulated",
        "fault_type": fault_enum.value,
        "auto_recovered": request.auto_recover,
        "recovery_action": recovery_result.model_dump(mode="json") if recovery_result else None,
    }
