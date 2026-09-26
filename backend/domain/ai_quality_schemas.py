from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

class ClaimValidationStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNAVAILABLE = "UNAVAILABLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

class QualityClaim(BaseModel):
    claim_id: str
    claim_text: str
    claim_type: str = "FACTUAL"
    validation_status: ClaimValidationStatus = ClaimValidationStatus.UNSUPPORTED
    evidence_refs: List[str] = Field(default_factory=list)
    provenance_refs: List[str] = Field(default_factory=list)
    explanation: str = ""

class QualityResult(BaseModel):
    overall_status: str
    claims: List[QualityClaim] = Field(default_factory=list)
    uncertainty_warnings: List[str] = Field(default_factory=list)
    evidence_coverage_pct: float = 0.0
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class QualityValidatedResponse(BaseModel):
    original_text: str
    quality_result: QualityResult
