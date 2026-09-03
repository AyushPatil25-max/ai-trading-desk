"""
Phase 23 — Production Observability, Audit Integrity & Operational Control REST API Routes

Read-only investigation endpoints, tamper-evident audit verification, decision explainability,
and safe operational control for simulated paper workers.

Safety Invariant:
- STRICTLY OBSERVATIONAL: Zero order submission authority.
- Worker controls operate exclusively on internal simulated paper workers.
- TIER_4_LIVE_REAL_MONEY remains permanently locked, unroutable, and fail-closed.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.domain.observability_schemas import (
    AuditVerificationStatus,
    EventCategory,
    EventSeverity,
)
from backend.application.decision_explainability_engine import global_explainability_engine
from backend.application.operational_control_plane import global_control_plane
from backend.application.slo_telemetry_engine import global_slo_telemetry_engine
from backend.application.tamper_evident_audit_chain import global_audit_chain

logger = logging.getLogger(__name__)

observability_router = APIRouter(
    prefix="/api/observability",
    tags=["Production Observability & Audit Integrity"],
)


# ── Request Models ────────────────────────────────────────────────────────────

class WorkerControlRequest(BaseModel):
    operator_id: str = Field(default="dashboard-operator", description="Operator identity for audit trail")


# ── Query & Investigation Endpoints (Step 8) ──────────────────────────────────

@observability_router.get("/events")
def query_events(
    correlation_id: Optional[str] = Query(default=None, description="Filter by correlation ID"),
    run_id: Optional[str] = Query(default=None, description="Filter by run ID"),
    symbol: Optional[str] = Query(default=None, description="Filter by symbol"),
    component: Optional[str] = Query(default=None, description="Filter by subsystem component"),
    category: Optional[str] = Query(default=None, description="Filter by event category"),
    severity: Optional[str] = Query(default=None, description="Filter by event severity"),
    limit: int = Query(default=50, ge=1, le=500, description="Max events to return"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
) -> Dict[str, Any]:
    """Bounded, paginated search across operational audit events."""
    cat_enum = None
    if category:
        try:
            cat_enum = EventCategory(category)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid category: {category}")

    sev_enum = None
    if severity:
        try:
            sev_enum = EventSeverity(severity)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid severity: {severity}")

    events = global_audit_chain.query_events(
        correlation_id=correlation_id,
        run_id=run_id,
        symbol=symbol,
        component=component,
        category=cat_enum,
        severity=sev_enum,
        limit=limit,
        offset=offset,
    )
    return {
        "count": len(events),
        "total_in_store": global_audit_chain.total_events_count,
        "offset": offset,
        "limit": limit,
        "events": [e.model_dump(mode="json") for e in events],
    }


@observability_router.get("/events/{event_id}")
def get_event(event_id: str) -> Dict[str, Any]:
    """Retrieve a single operational event by its event ID."""
    event = global_audit_chain.get_event_by_id(event_id)
    if not event:
        raise HTTPException(status_code=404, detail=f"Event '{event_id}' not found")
    return event.model_dump(mode="json")


@observability_router.get("/trace/{correlation_id}")
def get_lifecycle_trace(correlation_id: str) -> Dict[str, Any]:
    """
    Reconstruct the complete end-to-end execution lifecycle trace for a correlation ID.
    Returns all stages traversed, decision explainability, and timing metrics.
    """
    trace = global_control_plane.reconstruct_lifecycle(correlation_id)
    return trace.model_dump(mode="json")


@observability_router.get("/explainability/{correlation_id}")
def get_decision_explainability(correlation_id: str) -> Dict[str, Any]:
    """Retrieve structured decision explainability record by correlation ID."""
    rec = global_explainability_engine.get_by_correlation_id(correlation_id)
    if not rec:
        raise HTTPException(
            status_code=404,
            detail=f"No explainability record found for correlation_id '{correlation_id}'",
        )
    return rec.model_dump(mode="json")


# ── Audit Chain Cryptographic Verification (Step 4) ───────────────────────────

@observability_router.get("/audit/verify")
def verify_audit_chain() -> Dict[str, Any]:
    """
    Execute pure-Python SHA-256 cryptographic audit chain verification.
    Reports tamper status: VALID, BROKEN_CHAIN, INVALID_HASH, INVALID_SEQUENCE.
    """
    report = global_audit_chain.verify_integrity()
    return report.model_dump(mode="json")


# ── System Health & SLO Telemetry (Step 6) ────────────────────────────────────

@observability_router.get("/health")
def get_slo_health() -> Dict[str, Any]:
    """
    Retrieve operational SLO telemetry metrics snapshot:
    throughput, latency percentiles (p50, p95, p99), queue utilization, and health classification.
    """
    snapshot = global_slo_telemetry_engine.get_metrics_snapshot()
    return snapshot.model_dump(mode="json")


# ── Operational Control Plane (Step 7) ────────────────────────────────────────

@observability_router.get("/control/workers")
def get_paper_workers_status() -> Dict[str, Any]:
    """List operational status across all simulated paper trading workers."""
    workers = global_control_plane.get_worker_status_list()
    return {
        "total_workers": len(workers),
        "workers": workers,
        "mode": "PAPER_SIMULATION",
        "live_trading_permanently_locked": True,
    }


@observability_router.post("/control/workers/{symbol}/pause")
def pause_worker(symbol: str, request: WorkerControlRequest = WorkerControlRequest()) -> Dict[str, Any]:
    """
    Pause an individual simulated paper trading worker.
    Operates strictly within paper simulation. Zero live broker impact.
    """
    res = global_control_plane.pause_paper_worker(symbol=symbol, operator_id=request.operator_id)
    return res


@observability_router.post("/control/workers/{symbol}/resume")
def resume_worker(symbol: str, request: WorkerControlRequest = WorkerControlRequest()) -> Dict[str, Any]:
    """
    Resume an individual simulated paper trading worker.
    Operates strictly within paper simulation. Zero live broker impact.
    """
    res = global_control_plane.resume_paper_worker(symbol=symbol, operator_id=request.operator_id)
    return res


@observability_router.get("/control/config")
def get_system_configuration() -> Dict[str, Any]:
    """
    Inspect runtime operational configuration.
    Guarantees zero credential leakage and confirms fail-closed boundaries.
    """
    return global_control_plane.get_safe_system_configuration()
