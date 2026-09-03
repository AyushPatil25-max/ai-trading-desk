"""
Phase 16 — Live Evaluation & Staged Execution REST API Routes

FastAPI router exposing endpoints for automated agent prediction evaluation,
Bull vs. Bear grading matrix, specialist attribution, calibration Brier scores,
staged execution readiness auditing, and dynamic conviction weight feedback.
"""

from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.domain.live_evaluation_schemas import (
    AgentPerformanceMatrix,
    StagedReadinessReport,
)
from backend.application.live_evaluation_engine import global_evaluation_engine
from backend.application.staged_execution_auditor import global_readiness_auditor

router = APIRouter(prefix="/api/evaluation/live", tags=["Live Evaluation & Staged Readiness"])


class RecordOutcomeRequest(BaseModel):
    """Payload for recording a realized trade or forward tick outcome."""
    symbol: str
    realized_return_pct: float
    run_id: Optional[str] = None
    order_id: Optional[str] = None


@router.post(
    "/evaluate",
    response_model=AgentPerformanceMatrix,
    summary="Trigger Automated Multi-Agent Evaluation Loop",
)
def trigger_evaluation() -> AgentPerformanceMatrix:
    """
    Execute the automated evaluation loop across all recorded Trading OS predictions
    and paired realized returns. Computes Bull vs. Bear grades, specialist scorecards,
    and Brier calibration scores.
    """
    return global_evaluation_engine.evaluate()


@router.get(
    "/agent-matrix",
    response_model=AgentPerformanceMatrix,
    summary="Get Latest Multi-Agent Performance Matrix",
)
def get_agent_performance_matrix() -> AgentPerformanceMatrix:
    """
    Retrieve the most recent multi-agent performance evaluation matrix.
    """
    return global_evaluation_engine.get_latest_matrix()


@router.get(
    "/readiness",
    response_model=StagedReadinessReport,
    summary="Get Staged Broker Execution Readiness Report",
)
def get_staged_readiness_report() -> StagedReadinessReport:
    """
    Execute and return the staged broker execution readiness audit.
    Affirms operational stability and enforces that TIER_4_LIVE_REAL_MONEY is fail-closed.
    """
    return global_readiness_auditor.audit_readiness()


@router.get(
    "/feedback",
    response_model=Dict[str, float],
    summary="Get Dynamic Conviction Weight Adjustments",
)
def get_conviction_feedback() -> Dict[str, float]:
    """
    Retrieve empirical weight multipliers for specialist research agents
    derived from recent prediction accuracy.
    """
    return global_evaluation_engine.get_dynamic_weights()


@router.post(
    "/record-outcome",
    summary="Record Realized Trade Return Outcome",
)
def record_outcome(req: RecordOutcomeRequest) -> Dict[str, Any]:
    """
    Record an actual market return for a symbol or run ID to evaluate prediction accuracy.
    """
    record = global_evaluation_engine.record_trade_outcome(
        symbol=req.symbol,
        realized_return_pct=req.realized_return_pct,
        run_id=req.run_id,
        order_id=req.order_id,
    )
    if not record:
        return {
            "status": "RECORDED_PENDING_MATCH",
            "symbol": req.symbol,
            "realized_return_pct": req.realized_return_pct,
            "message": "Outcome recorded; will match future run records.",
        }
    return {
        "status": "MATCHED",
        "symbol": req.symbol,
        "run_id": record.run_id,
        "predicted_action": record.decision_action,
        "actual_direction": record.actual_direction,
        "is_win": record.is_win,
    }
