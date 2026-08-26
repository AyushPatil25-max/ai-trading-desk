from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any
from datetime import datetime
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
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    state: InvestmentDecisionState
    thesis: InvestmentThesis
    execution_plan: ExecutionPlan
    audit_trail: DecisionAudit
    confidence: float
    evidence_references: List[EvidenceReference] = Field(default_factory=list)
