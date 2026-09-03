"""
Phase 26 — Forward Paper Trading & Shadow Validation REST API Routes

Endpoints for session lifecycle control (start, pause, resume, stop),
market tick ingestion, shadow decision queries, realized outcome tracking (MFE/MAE),
signal and strategy drift snapshots, execution quality telemetry, and the 12-category scorecard.

Safety Invariant:
- Real-money live trading remains permanently locked and fail-closed.
- Zero live order execution authority.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.domain.forward_validation_schemas import (
    DataQualitySnapshot,
    ExecutionQualitySnapshot,
    ForwardPerformanceSnapshot,
    ForwardSessionState,
    ForwardValidationReport,
    ForwardValidationScorecard,
    ForwardValidationSession,
    MarketObservation,
    RealizedOutcome,
    ShadowDecision,
    SignalDriftSnapshot,
    StrategyDriftSnapshot,
    ValidationMode,
)
from backend.application.forward_validation_engine import (
    ForwardValidationEngine,
    global_forward_validation_engine,
)

forward_validation_router = APIRouter(prefix="/api/forward-validation", tags=["Forward Paper Trading & Shadow Validation"])


class CreateSessionRequest(BaseModel):
    symbols: List[str] = Field(default_factory=lambda: ["TCS.NS", "RELIANCE.NS", "INFY.NS"])
    mode: ValidationMode = ValidationMode.HYBRID
    initial_capital: float = 100000.0


class IngestTickRequest(BaseModel):
    symbol: str
    price: float
    volume: float = 1000.0
    event_timestamp: Optional[datetime] = None


@forward_validation_router.get("/status")
def get_forward_validation_status() -> Dict[str, Any]:
    """Get system readiness and safety configuration for Forward Paper Trading."""
    return {
        "status": "OPERATIONAL",
        "mode": "FORWARD_PAPER_AND_SHADOW_VALIDATION_ONLY",
        "live_money_execution": "LOCKED",
        "tier_4_live_real_money": "FAIL_CLOSED",
        "active_sessions_count": len(global_forward_validation_engine.list_sessions()),
        "schema_version": "26.0.0",
    }


@forward_validation_router.post("/sessions", response_model=ForwardValidationSession)
def create_forward_session(request: Optional[CreateSessionRequest] = None) -> ForwardValidationSession:
    """Create a new forward validation session."""
    req = request or CreateSessionRequest()
    return global_forward_validation_engine.create_session(
        symbols=req.symbols,
        mode=req.mode,
        initial_capital=req.initial_capital,
    )


@forward_validation_router.get("/sessions", response_model=List[ForwardValidationSession])
def list_forward_sessions() -> List[ForwardValidationSession]:
    """List all registered forward validation sessions."""
    return global_forward_validation_engine.list_sessions()


@forward_validation_router.get("/sessions/{session_id}", response_model=ForwardValidationSession)
def get_forward_session(session_id: str) -> ForwardValidationSession:
    """Retrieve details of a forward validation session."""
    try:
        return global_forward_validation_engine._get_session_or_raise(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")


@forward_validation_router.post("/sessions/{session_id}/start", response_model=ForwardValidationSession)
def start_forward_session(session_id: str) -> ForwardValidationSession:
    """Start a forward validation session."""
    try:
        return global_forward_validation_engine.start_session(session_id)
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@forward_validation_router.post("/sessions/{session_id}/pause", response_model=ForwardValidationSession)
def pause_forward_session(session_id: str) -> ForwardValidationSession:
    """Pause an active forward validation session."""
    try:
        return global_forward_validation_engine.pause_session(session_id)
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@forward_validation_router.post("/sessions/{session_id}/resume", response_model=ForwardValidationSession)
def resume_forward_session(session_id: str) -> ForwardValidationSession:
    """Resume a paused forward validation session."""
    try:
        return global_forward_validation_engine.resume_session(session_id)
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@forward_validation_router.post("/sessions/{session_id}/stop", response_model=ForwardValidationSession)
def stop_forward_session(session_id: str) -> ForwardValidationSession:
    """Stop a forward validation session."""
    try:
        return global_forward_validation_engine.stop_session(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@forward_validation_router.post("/sessions/{session_id}/tick")
def ingest_tick(session_id: str, request: IngestTickRequest) -> Dict[str, Any]:
    """Ingest a market tick into the forward validation session."""
    ts = request.event_timestamp or datetime.now(timezone.utc)
    obs = MarketObservation(
        symbol=request.symbol,
        price=request.price,
        volume=request.volume,
        event_timestamp=ts,
    )
    try:
        ok, anomalies = global_forward_validation_engine.ingest_market_observation(session_id, obs)
        return {"success": ok, "anomalies": anomalies, "symbol": request.symbol, "price": request.price}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@forward_validation_router.get("/sessions/{session_id}/decisions", response_model=List[ShadowDecision])
def get_shadow_decisions(session_id: str) -> List[ShadowDecision]:
    """Retrieve immutable shadow decisions generated for this session."""
    try:
        global_forward_validation_engine._get_session_or_raise(session_id)
        return global_forward_validation_engine._decisions.get(session_id, [])
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")


@forward_validation_router.get("/sessions/{session_id}/outcomes", response_model=List[RealizedOutcome])
def get_realized_outcomes(session_id: str) -> List[RealizedOutcome]:
    """Retrieve realized outcomes with MFE and MAE metrics."""
    try:
        global_forward_validation_engine._get_session_or_raise(session_id)
        return global_forward_validation_engine._outcomes.get(session_id, [])
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")


@forward_validation_router.get("/sessions/{session_id}/drift")
def get_drift_metrics(session_id: str) -> Dict[str, Any]:
    """Retrieve signal and strategy drift snapshots."""
    try:
        global_forward_validation_engine._get_session_or_raise(session_id)
        return {
            "signal_drift": global_forward_validation_engine.get_signal_drift(session_id),
            "strategy_drift": global_forward_validation_engine.get_strategy_drift(session_id),
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")


@forward_validation_router.get("/sessions/{session_id}/execution", response_model=ExecutionQualitySnapshot)
def get_execution_quality(session_id: str) -> ExecutionQualitySnapshot:
    """Retrieve execution latency and fill telemetry."""
    try:
        global_forward_validation_engine._get_session_or_raise(session_id)
        return global_forward_validation_engine.get_execution_quality(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")


@forward_validation_router.get("/sessions/{session_id}/risk", response_model=ForwardPerformanceSnapshot)
def get_risk_snapshot(session_id: str) -> ForwardPerformanceSnapshot:
    """Retrieve paper portfolio risk and performance state."""
    try:
        global_forward_validation_engine._get_session_or_raise(session_id)
        return global_forward_validation_engine.get_performance_snapshot(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")


@forward_validation_router.get("/sessions/{session_id}/scorecard", response_model=ForwardValidationScorecard)
def get_forward_scorecard(session_id: str) -> ForwardValidationScorecard:
    """Retrieve 12-category Unified Forward Validation Scorecard."""
    try:
        global_forward_validation_engine._get_session_or_raise(session_id)
        return global_forward_validation_engine.build_scorecard(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")


@forward_validation_router.get("/sessions/{session_id}/report", response_model=ForwardValidationReport)
def get_forward_report(session_id: str) -> ForwardValidationReport:
    """Retrieve complete forward validation report."""
    try:
        return global_forward_validation_engine.generate_report(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
