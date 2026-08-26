from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any
from datetime import datetime
from enum import Enum
from backend.domain.schemas import UnifiedEvidencePackage, MarketContext, AgentOutput

class ArgumentStrength(str, Enum):
    WEAK = "WEAK"
    MODERATE = "MODERATE"
    STRONG = "STRONG"
    COMPELLING = "COMPELLING"

class ChallengeType(str, Enum):
    DIRECT_CONFLICT = "DIRECT_CONFLICT"
    DATA_CONFLICT = "DATA_CONFLICT"
    DOMAIN_TENSION = "DOMAIN_TENSION"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
    VALUATION_RISK = "VALUATION_RISK"
    FUNDAMENTAL_DETERIORATION = "FUNDAMENTAL_DETERIORATION"

class DebateDecisionState(str, Enum):
    PENDING = "PENDING"
    BULL_FAVORED = "BULL_FAVORED"
    BEAR_FAVORED = "BEAR_FAVORED"
    MIXED = "MIXED"
    RISK_VETO = "RISK_VETO"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

class EvidenceReference(BaseModel):
    evidence_id: str
    category: str
    claim: str
    supporting_value: Optional[float] = None
    source: str = "UNKNOWN"
    confidence: float = 0.0
    is_assumption: bool = False

class BullCase(BaseModel):
    thesis_id: str
    context_id: str
    symbol: str
    core_thesis: str
    supporting_evidence: List[str] = Field(default_factory=list)
    key_catalysts: List[str] = Field(default_factory=list)
    specialist_support: List[str] = Field(default_factory=list)
    counterarguments_acknowledged: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    invalidation_conditions: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    evidence_references: List[EvidenceReference] = Field(default_factory=list)

class BearCase(BaseModel):
    thesis_id: str
    context_id: str
    symbol: str
    attack_summary: str
    bull_claims_challenged: List[str] = Field(default_factory=list)
    contradictory_evidence: List[str] = Field(default_factory=list)
    weakest_bull_arguments: List[str] = Field(default_factory=list)
    key_downside_risks: List[str] = Field(default_factory=list)
    invalidation_conditions: List[str] = Field(default_factory=list)
    required_confirmation: List[str] = Field(default_factory=list)
    specialist_counter_evidence: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    evidence_references: List[EvidenceReference] = Field(default_factory=list)

class RiskAssessment(BaseModel):
    context_id: str
    symbol: str
    risk_level: str
    risk_score: float = 0.0
    primary_risks: List[str] = Field(default_factory=list)
    secondary_risks: List[str] = Field(default_factory=list)
    data_risks: List[str] = Field(default_factory=list)
    thesis_invalidation: List[str] = Field(default_factory=list)
    risk_reward_assessment: str = ""
    position_constraints: List[str] = Field(default_factory=list)
    required_conditions: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    evidence_references: List[EvidenceReference] = Field(default_factory=list)
    risk_veto: bool = False

class DebateArgument(BaseModel):
    argument_id: str
    claim: str
    strength: ArgumentStrength
    evidence_references: List[EvidenceReference] = Field(default_factory=list)

class DebateChallenge(BaseModel):
    challenge_id: str
    target_argument_id: str
    challenge_type: ChallengeType
    explanation: str
    evidence_references: List[EvidenceReference] = Field(default_factory=list)

class DebateRound(BaseModel):
    round_id: str
    bull_arguments: List[DebateArgument] = Field(default_factory=list)
    bear_challenges: List[DebateChallenge] = Field(default_factory=list)

class DebateResult(BaseModel):
    debate_id: str
    context_id: str
    symbol: str
    bull_case: Optional[BullCase] = None
    bear_case: Optional[BearCase] = None
    risk_assessment: Optional[RiskAssessment] = None
    bull_strength: float = 0.0
    bear_strength: float = 0.0
    risk_score: float = 0.0
    key_agreements: List[str] = Field(default_factory=list)
    key_disagreements: List[str] = Field(default_factory=list)
    critical_conflicts: List[str] = Field(default_factory=list)
    unresolved_questions: List[str] = Field(default_factory=list)
    overall_debate_quality: str = "UNKNOWN"
    confidence: float = 0.0
    evidence_references: List[EvidenceReference] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    thesis_status: DebateDecisionState = DebateDecisionState.PENDING
    recommended_action: str = ""
