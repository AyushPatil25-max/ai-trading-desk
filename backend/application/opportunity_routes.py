"""
Phase 10 — Opportunity Scanner FastAPI Routes

REST API endpoints for triggering opportunity scans, querying discovered candidates,
inspecting candidate details with linked Trading OS runs, and controlling the background discovery worker.
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.domain.opportunity_schemas import (
    CandidatePriority,
    CandidateScreeningStatus,
    OpportunityCandidate,
    ScannerCycleSummary,
    ScannerHealthStatus,
)
from backend.application.opportunity_scanner import global_scanner, global_worker

router = APIRouter(prefix="/api/opportunities", tags=["Opportunities"])


class TriggerScanRequest(BaseModel):
    universe_id: str = "NIFTY_50"
    max_candidates: Optional[int] = None
    allow_execution: bool = True
    fill_ratio: float = 1.0


@router.post("/scan", response_model=ScannerCycleSummary)
def trigger_scan(request: Optional[TriggerScanRequest] = None) -> ScannerCycleSummary:
    """
    Trigger an immediate, on-demand opportunity scan cycle across the specified universe.
    """
    req = request or TriggerScanRequest()
    if req.max_candidates:
        global_scanner.config.max_candidates_per_cycle = req.max_candidates
    global_scanner.config.allow_execution = req.allow_execution
    global_scanner.config.fill_ratio = req.fill_ratio

    try:
        summary = global_scanner.execute_scan_cycle(universe_id=req.universe_id)
        return summary
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"Scan cycle execution failed: {str(ex)}")


@router.get("", response_model=List[OpportunityCandidate])
def list_candidates(
    universe: Optional[str] = Query(None, description="Filter by universe ID (e.g. NIFTY_50)"),
    priority: Optional[CandidatePriority] = Query(None, description="Filter by candidate priority"),
    status: Optional[CandidateScreeningStatus] = Query(None, description="Filter by screening status"),
    limit: int = Query(50, ge=1, le=200, description="Max candidates to return"),
) -> List[OpportunityCandidate]:
    """
    Query discovered candidates with optional filtering by universe, priority, and screening status.
    """
    return global_scanner.list_candidates(
        universe=universe,
        priority=priority,
        status=status,
        limit=limit,
    )


@router.get("/scanner/status", response_model=ScannerHealthStatus)
def get_scanner_status() -> ScannerHealthStatus:
    """
    Get live operational health, queue size, and background worker state.
    """
    return global_worker.get_status()


@router.post("/scanner/start")
def start_scanner() -> dict:
    """
    Start the continuous background discovery worker.
    """
    started = global_worker.start()
    return {"success": started, "state": global_worker.state.value}


@router.post("/scanner/stop")
def stop_scanner() -> dict:
    """
    Stop the continuous background discovery worker.
    """
    stopped = global_worker.stop()
    return {"success": stopped, "state": global_worker.state.value}


@router.post("/scanner/pause")
def pause_scanner() -> dict:
    """
    Pause continuous background discovery scans.
    """
    paused = global_worker.pause()
    return {"success": paused, "state": global_worker.state.value}


@router.post("/scanner/resume")
def resume_scanner() -> dict:
    """
    Resume paused background discovery scans.
    """
    resumed = global_worker.resume()
    return {"success": resumed, "state": global_worker.state.value}


@router.get("/{candidate_id}", response_model=OpportunityCandidate)
def get_candidate_details(candidate_id: str) -> OpportunityCandidate:
    """
    Retrieve single candidate details, including discovery score, Stage A metrics, and linked Trading OS run.
    """
    cand = global_scanner.get_candidate(candidate_id)
    if not cand:
        raise HTTPException(status_code=404, detail=f"Candidate '{candidate_id}' not found.")
    return cand
