from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone
from enum import Enum
from backend.domain.debate_schemas import EvidenceReference

class InvestmentDecisionState(str, Enum):
    APPROVE = "APPROVE"
    HOLD = "HOLD"
    REJECT = "REJECT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    RISK_VETO = "RISK_VETO"
    DATA_QUALITY_VETO = "DATA_QUALITY_VETO"

class InvestmentAction(str, Enum):
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"
    AVOID = "AVOID"
    WATCH = "WATCH"

class InvestmentHorizon(str, Enum):
    INTRADAY = "INTRADAY"
    SHORT_TERM = "SHORT_TERM"
    SWING = "SWING"
    MEDIUM_TERM = "MEDIUM_TERM"
    LONG_TERM = "LONG_TERM"

class DecisionGate(BaseModel):
    gate_name: str
    passed: bool
    threshold_used: Optional[float] = None
    input_value: Optional[float] = None
    reason: str

class PositionSizing(BaseModel):
    is_available: bool = True
    recommended_size_pct: float = 0.0
    max_size_pct: float = 0.0
    volatility_adjusted: bool = False
    reason: str = ""

class ExecutionPlan(BaseModel):
    action: InvestmentAction
    horizon: InvestmentHorizon
    entry_conditions: List[str] = Field(default_factory=list)
    preferred_entry_zone: str = "UNKNOWN"
    stop_loss_condition: str = "UNKNOWN"
    target_logic: str = "UNKNOWN"
    cancellation_conditions: List[str] = Field(default_factory=list)
    reassessment_conditions: List[str] = Field(default_factory=list)
    position_sizing: PositionSizing

class DecisionAudit(BaseModel):
    gates_evaluated: List[DecisionGate] = Field(default_factory=list)
    critical_conflicts_found: int = 0
    risk_veto_triggered: bool = False
    missing_data_triggered: bool = False
    deterministic_state: InvestmentDecisionState

class InvestmentThesis(BaseModel):
    synthesis: str
    key_drivers: List[str] = Field(default_factory=list)
    primary_risks: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    invalidation_conditions: List[str] = Field(default_factory=list)

class InvestmentDecision(BaseModel):
    decision_id: str
    context_id: str
    symbol: str
    run_id: Optional[str] = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    state: InvestmentDecisionState
    thesis: InvestmentThesis
    execution_plan: ExecutionPlan
    audit_trail: DecisionAudit
    confidence: float
    evidence_references: List[EvidenceReference] = Field(default_factory=list)

# ── Phase 6.3: Investment Committee Decision Synthesis ──────────────────────

from backend.domain.schemas import ContradictionRecord
from backend.domain.debate_schemas import DebateArgument

class CommitteeRecommendation(str, Enum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    HOLD = "HOLD"
    WATCH = "WATCH"
    AVOID = "AVOID"
    SELL = "SELL"
    INDETERMINATE = "INDETERMINATE"

class DataQualityStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    DEGRADED = "DEGRADED"
    INSUFFICIENT = "INSUFFICIENT"
    STALE = "STALE"

class CommitteeDecision(BaseModel):
    decision_id: str
    run_id: str = ""
    context_id: str
    symbol: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    duration_seconds: float = 0.0
    decision_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    time_horizon: str = "MEDIUM_TERM"

    # Decision
    recommendation: CommitteeRecommendation = CommitteeRecommendation.INDETERMINATE
    conviction_score: float = Field(default=0.0, ge=0.0, le=1.0)
    calibrated_conviction: Optional[float] = None
    calibration_id: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    # Evidence
    supporting_evidence_ids: List[str] = Field(default_factory=list)
    opposing_evidence_ids: List[str] = Field(default_factory=list)
    strongest_bull_arguments: List[DebateArgument] = Field(default_factory=list)
    strongest_bear_arguments: List[DebateArgument] = Field(default_factory=list)
    unresolved_contradictions: List[ContradictionRecord] = Field(default_factory=list)

    # Risk
    risk_score: float = 0.0
    risk_level: str = "LOW"
    risk_veto_applied: bool = False
    risk_veto_reason: Optional[str] = None
    key_risks: List[str] = Field(default_factory=list)
    invalidation_conditions: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)

    # Data Quality
    evidence_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    data_quality: DataQualityStatus = DataQualityStatus.AVAILABLE
    degraded_specialists: List[str] = Field(default_factory=list)
    failed_specialists: List[str] = Field(default_factory=list)
    missing_critical_data: List[str] = Field(default_factory=list)

    # Reasoning Summary
    investment_thesis: str = ""
    decision_summary: str = ""
    why_bull_case_wins: str = ""
    why_bear_case_wins: str = ""
    what_would_change_the_decision: str = ""

    # Traceability & Provenance
    evidence_references: List[EvidenceReference] = Field(default_factory=list)
    provenance: List[Any] = Field(default_factory=list)

    # Backward compatibility / legacy fields
    state: Optional[InvestmentDecisionState] = None
    execution_plan: Optional[ExecutionPlan] = None
    audit_trail: Optional[DecisionAudit] = None

# Aliases
InvestmentCommitteeResult = CommitteeDecision

