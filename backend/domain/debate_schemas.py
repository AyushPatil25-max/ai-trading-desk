import uuid
from pydantic import BaseModel, Field, model_validator
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone
from enum import Enum
from backend.domain.schemas import (
    UnifiedEvidencePackage, MarketContext, AgentOutput, ContradictionRecord,
    EvidenceRecord, EvidenceSummary,
)

# ── Enums ───────────────────────────────────────────────────────────────────

class DebateSide(str, Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    NEUTRAL = "NEUTRAL"
    RISK = "RISK"

class ChallengeSeverity(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

class ChallengeStatus(str, Enum):
    OPEN = "OPEN"
    DEFENDED = "DEFENDED"
    CONCEDED = "CONCEDED"
    PARTIALLY_DEFENDED = "PARTIALLY_DEFENDED"
    UNADDRESSED = "UNADDRESSED"

class ContradictionResolutionStatus(str, Enum):
    UNRESOLVED = "UNRESOLVED"
    PARTIALLY_RESOLVED = "PARTIALLY_RESOLVED"
    RESOLVED = "RESOLVED"

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

# Alias for DebateState
DebateState = DebateDecisionState

# ── Legacy Case Models (Preserved for Backward Compatibility) ───────────────

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

# ── Phase 6.2: Adversarial Debate Models ───────────────────────────────────

class DebateArgument(BaseModel):
    argument_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    side: DebateSide = DebateSide.BULL
    claim: str
    supporting_evidence_ids: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    risks: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)

    # Backward-compatibility / optional fields
    strength: Optional[ArgumentStrength] = ArgumentStrength.MODERATE
    evidence_references: List[EvidenceReference] = Field(default_factory=list)
    is_unsupported: bool = False

class DebateChallenge(BaseModel):
    challenge_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    target_argument_id: str
    challenge: str = ""
    evidence_ids: List[str] = Field(default_factory=list)
    severity: ChallengeSeverity = ChallengeSeverity.MODERATE
    response_status: ChallengeStatus = ChallengeStatus.OPEN

    # Backward-compatibility / optional fields
    challenge_type: Optional[ChallengeType] = ChallengeType.DIRECT_CONFLICT
    explanation: Optional[str] = None
    evidence_references: List[EvidenceReference] = Field(default_factory=list)

    @model_validator(mode="after")
    def populate_fallback_fields(self):
        if not self.challenge and self.explanation:
            self.challenge = self.explanation
        elif not self.explanation and self.challenge:
            self.explanation = self.challenge
        return self

class DebateRebuttal(BaseModel):
    rebuttal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    challenge_id: str
    response: str
    supporting_evidence_ids: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    counter_evidence_ids: List[str] = Field(default_factory=list)

class ContradictionAnalysis(BaseModel):
    contradiction_id: str
    subject: str
    status: ContradictionResolutionStatus = ContradictionResolutionStatus.UNRESOLVED
    competing_claims: List[str] = Field(default_factory=list)
    resolution_rationale: str = ""

class DebateRound(BaseModel):
    round_number: int = 1
    bull_arguments: List[DebateArgument] = Field(default_factory=list)
    bear_arguments: List[DebateArgument] = Field(default_factory=list)
    challenges: List[DebateChallenge] = Field(default_factory=list)
    rebuttals: List[DebateRebuttal] = Field(default_factory=list)

    # Backward-compatibility / optional fields
    round_id: Optional[str] = None
    bear_challenges: List[DebateChallenge] = Field(default_factory=list)

class DebateResult(BaseModel):
    debate_id: str
    run_id: str = ""
    context_id: str
    symbol: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    duration_seconds: float = 0.0
    rounds: List[DebateRound] = Field(default_factory=list)
    unresolved_contradictions: List[ContradictionRecord] = Field(default_factory=list)
    contradiction_analyses: List[ContradictionAnalysis] = Field(default_factory=list)
    strongest_bull_arguments: List[DebateArgument] = Field(default_factory=list)
    strongest_bear_arguments: List[DebateArgument] = Field(default_factory=list)
    key_risks: List[str] = Field(default_factory=list)
    key_assumptions: List[str] = Field(default_factory=list)
    evidence_coverage: float = 0.0
    final_debate_state: DebateDecisionState = DebateDecisionState.PENDING
    confidence: float = 0.0

    # Backward-compatibility fields (used by committee_agent & legacy tests)
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
    evidence_references: List[EvidenceReference] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    thesis_status: DebateDecisionState = DebateDecisionState.PENDING
    recommended_action: str = ""

