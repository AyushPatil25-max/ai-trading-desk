from enum import Enum
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field
from backend.domain.schemas import DataQualityStatus, EvidenceRecord

class DirectionalState(str, Enum):
    BULLISH = 'BULLISH'
    BEARISH = 'BEARISH'
    NEUTRAL = 'NEUTRAL'
    MIXED = 'MIXED'
    INSUFFICIENT_DATA = 'INSUFFICIENT_DATA'

class EngineRiskState(str, Enum):
    LOW = 'LOW'
    MODERATE = 'MODERATE'
    HIGH = 'HIGH'
    EXTREME = 'EXTREME'
    UNKNOWN = 'UNKNOWN'

class EngineConflictRecord(BaseModel):
    conflict_type: str
    bullish_evidence_ids: List[str]
    bearish_evidence_ids: List[str]
    resolution_note: str

class EngineRiskFactor(BaseModel):
    factor_type: str
    severity: EngineRiskState
    description: str

class BullBearRiskResult(BaseModel):
    directional_state: DirectionalState
    risk_state: EngineRiskState
    bullish_score: float = 0.0
    bearish_score: float = 0.0
    active_evidence: List[EvidenceRecord] = Field(default_factory=list)
    conflicts: List[EngineConflictRecord] = Field(default_factory=list)
    risk_factors: List[EngineRiskFactor] = Field(default_factory=list)
    invalidation_conditions: List[str] = Field(default_factory=list)
