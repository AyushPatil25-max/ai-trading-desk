"""
Phase 9 — End-to-End Trading OS Schemas

Strongly typed domain models representing pipeline stage execution, unified TradingOSRun states,
and machine-readable operational run summaries.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


TRADING_OS_VERSION = "9.0.0"


# ── Enums ───────────────────────────────────────────────────────────────────

class StageStatus(str, Enum):
    """Execution status for each stage within the unified Trading OS pipeline."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    DEGRADED = "DEGRADED"


# ── Stage Outcome ───────────────────────────────────────────────────────────

class PipelineStageResult(BaseModel):
    """
    Detailed audit result of a single stage execution in the pipeline.
    """
    stage_name: str
    status: StageStatus
    started_at: datetime
    completed_at: datetime
    duration_ms: float = 0.0
    details: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None


# ── Unified Pipeline Run ───────────────────────────────────────────────────

class TradingOSRun(BaseModel):
    """
    Complete state container capturing an entire analysis-to-execution cycle.
    Strictly operating in PAPER_ONLY mode.
    """
    run_id: str = Field(default_factory=lambda: f"run-{uuid.uuid4().hex[:8]}")
    symbol: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    total_duration_ms: float = 0.0
    mode: str = "PAPER_ONLY"

    # Stage results map
    stages: Dict[str, PipelineStageResult] = Field(default_factory=dict)

    # Stage artifacts
    market_context: Optional[Dict[str, Any]] = None
    specialist_outputs: Optional[Dict[str, Any]] = None
    evidence: Optional[Dict[str, Any]] = None
    debate: Optional[Dict[str, Any]] = None
    committee_decision: Optional[Dict[str, Any]] = None
    conviction: Optional[Dict[str, Any]] = None
    regime: Optional[Dict[str, Any]] = None
    portfolio: Optional[Dict[str, Any]] = None
    scenario: Optional[Dict[str, Any]] = None
    risk: Optional[Dict[str, Any]] = None
    sizing: Optional[Dict[str, Any]] = None
    historical_validation: Optional[Dict[str, Any]] = None
    preflight: Optional[Dict[str, Any]] = None
    paper_order: Optional[Dict[str, Any]] = None
    fills: List[Dict[str, Any]] = Field(default_factory=list)
    telemetry_summary: Optional[Dict[str, Any]] = None

    final_status: StageStatus = StageStatus.PENDING
    failed_stage: Optional[str] = None
    failure_reason: Optional[str] = None


# ── Run Summary ─────────────────────────────────────────────────────────────

class TradingOSRunSummary(BaseModel):
    """
    Concise machine-readable summary of a completed Trading OS execution run.
    """
    run_id: str
    symbol: str
    decision: str
    conviction: float
    regime: str
    risk_status: str
    approved_size: int
    preflight_status: str
    paper_order_status: str
    fill_status: str
    final_position: int
    pnl: float
    warnings: List[str] = Field(default_factory=list)
    failures: List[str] = Field(default_factory=list)
    duration_ms: float = 0.0
    mode: str = "PAPER_ONLY"
