"""
Phase 31 — Execution Orchestration & Control Plane REST API Routes

FastAPI router exposing deterministic execution orchestration, lifecycle queries,
cancellation, reconciliation, and control plane management:
- POST /api/orchestration/submit               (Submit approved ExecutionDecision for orchestration)
- GET  /api/orchestration/{execution_id}       (Retrieve execution record by ID)
- POST /api/orchestration/{execution_id}/cancel (Request cancellation of execution)
- POST /api/orchestration/{execution_id}/reconcile (Reconcile ambiguous execution state)
- GET  /api/orchestration/status               (Get orchestrator & control plane operational status)
- GET  /api/orchestration/history              (List execution history records)
- POST /api/orchestration/control/pause        (Pause execution orchestrator)
- POST /api/orchestration/control/resume       (Resume execution orchestrator)
- POST /api/orchestration/control/halt         (Emergency halt execution orchestrator)

Safety Invariants:
- Zero real broker credentials exposed.
- Does not bypass RiskEngine, Preflight, Safety Gate, or ConfirmationStore.
- LIVE_EXECUTION_ENABLED=false remains fail-closed default.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.domain.execution_orchestration_schemas import (
    ExecutionControlState,
    ExecutionControlStatus,
    ExecutionOrchestrationRequest,
    ExecutionOrchestrationResult,
)
from backend.execution.execution_orchestrator import global_execution_orchestrator

orchestration_router = APIRouter(prefix="/api/orchestration", tags=["Execution Orchestration & Control Plane"])


# ── REST API Endpoints ────────────────────────────────────────────────────────

@orchestration_router.post(
    "/submit",
    response_model=ExecutionOrchestrationResult,
    summary="Submit Approved ExecutionDecision for Orchestration",
)
def submit_execution(request: ExecutionOrchestrationRequest) -> ExecutionOrchestrationResult:
    """
    Orchestrate an approved ExecutionDecision through the appropriate Paper or Live execution pipeline.
    """
    return global_execution_orchestrator.submit_execution(request)


@orchestration_router.get(
    "/status",
    response_model=ExecutionControlStatus,
    summary="Get Execution Orchestration Control Plane Status",
)
def get_orchestration_status() -> ExecutionControlStatus:
    """Return operational metrics and control plane diagnostics."""
    return global_execution_orchestrator.status()


@orchestration_router.get(
    "/history",
    response_model=List[ExecutionOrchestrationResult],
    summary="Get Execution History Records",
)
def get_execution_history() -> List[ExecutionOrchestrationResult]:
    """Retrieve history of all execution records."""
    return global_execution_orchestrator.get_history()


@orchestration_router.get(
    "/{execution_id}",
    response_model=ExecutionOrchestrationResult,
    summary="Get Execution Record by ID",
)
def get_execution_by_id(execution_id: str) -> ExecutionOrchestrationResult:
    """Retrieve a specific execution record by ID."""
    res = global_execution_orchestrator.get_execution(execution_id)
    if not res:
        raise HTTPException(status_code=404, detail=f"Execution record '{execution_id}' not found.")
    return res


@orchestration_router.post(
    "/{execution_id}/cancel",
    response_model=ExecutionOrchestrationResult,
    summary="Cancel Active Execution",
)
def cancel_execution(execution_id: str, reason: str = "Operator cancellation") -> ExecutionOrchestrationResult:
    """Request cancellation of an active execution record."""
    try:
        return global_execution_orchestrator.cancel_execution(execution_id=execution_id, reason=reason)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@orchestration_router.post(
    "/{execution_id}/reconcile",
    response_model=ExecutionOrchestrationResult,
    summary="Trigger Execution Reconciliation",
)
def reconcile_execution(execution_id: str) -> ExecutionOrchestrationResult:
    """Trigger broker reconciliation for an ambiguous execution record."""
    try:
        return global_execution_orchestrator.reconcile_execution(execution_id=execution_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@orchestration_router.post(
    "/control/pause",
    response_model=Dict[str, Any],
    summary="Pause Execution Orchestration",
)
def pause_orchestration(reason: str = "Operator requested pause") -> Dict[str, Any]:
    """Pause the execution orchestrator from accepting new executions."""
    state = global_execution_orchestrator.pause(reason)
    return {"status": "PAUSED", "control_state": state.value, "reason": reason}


@orchestration_router.post(
    "/control/resume",
    response_model=Dict[str, Any],
    summary="Resume Execution Orchestration",
)
def resume_orchestration() -> Dict[str, Any]:
    """Resume the execution orchestrator to RUNNING state."""
    try:
        state = global_execution_orchestrator.resume()
        return {"status": "RESUMED", "control_state": state.value}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@orchestration_router.post(
    "/control/halt",
    response_model=Dict[str, Any],
    summary="Emergency Halt Execution Orchestration",
)
def halt_orchestration(reason: str = "Operator emergency halt") -> Dict[str, Any]:
    """Halt the execution orchestrator immediately."""
    state = global_execution_orchestrator.halt(reason)
    return {"status": "HALTED", "control_state": state.value, "reason": reason}
