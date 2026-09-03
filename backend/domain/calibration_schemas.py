"""
Phase 6.5 — Conviction & Decision Calibration Domain Schemas

Strongly typed domain models, enums, and results for deterministic
conviction scoring, de-correlated specialist agreement, data quality
penalties, and recommendation consistency auditing.
"""

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator

from backend.domain.investment_committee_schemas import (
    CommitteeRecommendation,
    DataQualityStatus,
)

# ── Centralized Calibration Version ───────────────────────────────────────────
CALIBRATION_VERSION: str = "6.5.0"


# ── Enums ───────────────────────────────────────────────────────────────────

class ConvictionBand(str, Enum):
    """Calibrated conviction ranges with explicit semantics."""
    VERY_LOW = "VERY_LOW"      # 0.00 – 0.19
    LOW = "LOW"                # 0.20 – 0.39
    MODERATE = "MODERATE"      # 0.40 – 0.59
    HIGH = "HIGH"              # 0.60 – 0.79
    VERY_HIGH = "VERY_HIGH"    # 0.80 – 1.00

    @classmethod
    def from_score(cls, score: float) -> "ConvictionBand":
        """Map a numeric score in [0.0, 1.0] to its corresponding band."""
        if math.isnan(score) or math.isinf(score) or score <= 0.1999:
            return cls.VERY_LOW
        elif score <= 0.3999:
            return cls.LOW
        elif score <= 0.5999:
            return cls.MODERATE
        elif score <= 0.7999:
            return cls.HIGH
        else:
            return cls.VERY_HIGH


class SpecialistAgreementLevel(str, Enum):
    """Assessment of multi-pillar alignment across independent domains."""
    STRONG_CONSENSUS = "STRONG_CONSENSUS"      # >= 3 pillars point same direction, 0 oppose
    MODERATE_CONSENSUS = "MODERATE_CONSENSUS"  # 2 pillars point same direction, 0 oppose
    MIXED = "MIXED"                            # Neutral or balanced signals
    CONFLICTING = "CONFLICTING"                # Direct opposition between major pillars
    INSUFFICIENT = "INSUFFICIENT"              # < 2 active pillars


class RecommendationConsistency(str, Enum):
    """Audit of alignment between committee recommendation and calibrated conviction."""
    CONSISTENT = "CONSISTENT"
    INCONSISTENT = "INCONSISTENT"
    CAUTIONARY = "CAUTIONARY"
    NOT_APPLICABLE = "NOT_APPLICABLE"


# ── Pillar Breakdown Model ───────────────────────────────────────────────────

class PillarBreakdown(BaseModel):
    """Breakdown of an independent evidence pillar."""
    pillar_name: str
    weight: float = Field(ge=0.0, le=1.0)
    raw_score: float = Field(ge=0.0, le=1.0)
    direction: str = Field(default="UNKNOWN", description="e.g. 'BULLISH', 'BEARISH', 'NEUTRAL', 'UNKNOWN'")
    specialists_included: List[str] = Field(default_factory=list)
    correlation_discount_applied: float = Field(default=1.0, ge=0.0, le=1.0)


# ── Calibration Result Model ─────────────────────────────────────────────────

class ConvictionCalibrationResult(BaseModel):
    """
    Strongly typed, auditable result of deterministic conviction calibration.
    Advisory and planning-only — pure Python calculations, zero LLM arithmetic.
    """
    calibration_id: str = Field(description="Unique calibration identifier")
    context_id: str = Field(description="Market context ID")
    decision_id: str = Field(description="Upstream CommitteeDecision ID")
    symbol: str = Field(description="Ticker symbol")

    # Scores
    raw_conviction: float = Field(ge=0.0, le=1.0, description="Raw upstream conviction score")
    calibrated_conviction: float = Field(ge=0.0, le=1.0, description="Calibrated deterministic score strictly in [0.0, 1.0]")
    conviction_band: ConvictionBand = Field(description="Qualitative classification band")

    # Factor Analysis
    evidence_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    specialist_agreement: SpecialistAgreementLevel = Field(default=SpecialistAgreementLevel.MIXED)
    debate_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    pillar_scores: Dict[str, float] = Field(default_factory=dict)
    pillar_details: List[PillarBreakdown] = Field(default_factory=list)

    # Adjustments & Penalties
    correlation_discount: float = Field(default=0.0, ge=0.0, le=1.0, description="Discount for collinear specialists (e.g. Tech+Mom)")
    contradiction_penalty: float = Field(default=0.0, ge=0.0, description="Penalty for unresolved contradictions")
    data_quality_adjustment: float = Field(default=0.0, description="Haircut or scale applied due to data quality")
    missing_data_penalty: float = Field(default=0.0, ge=0.0, description="Penalty for missing critical pillars")

    # Metadata & Versioning
    calibration_method: str = Field(default="MULTI_PILLAR_UNCORRELATED_COMPOSITE")
    calibration_version: str = Field(default=CALIBRATION_VERSION)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    # Recommendation Audit
    recommendation: CommitteeRecommendation = Field(default=CommitteeRecommendation.INDETERMINATE)
    recommendation_consistency: RecommendationConsistency = Field(default=RecommendationConsistency.CONSISTENT)
    consistency_notes: str = Field(default="")

    # Risk Decoupling (Strict Separation)
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Downside risk score (strictly separate from conviction)")
    risk_veto_applied: bool = Field(default=False, description="Whether risk veto was applied upstream")
    risk_veto_reason: Optional[str] = Field(default=None)

    # Audit & Traceability
    warnings: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    provenance: List[Dict[str, Any]] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_calibration(self) -> "ConvictionCalibrationResult":
        if math.isnan(self.calibrated_conviction) or math.isinf(self.calibrated_conviction):
            raise ValueError("calibrated_conviction must be a finite number.")
        if self.calibrated_conviction < 0.0 or self.calibrated_conviction > 1.0:
            raise ValueError(f"calibrated_conviction {self.calibrated_conviction} out of [0.0, 1.0] bounds.")
        return self

    def __await__(self):
        """Allows this result to be awaited directly for seamless async/sync dual usage."""
        async def _identity():
            return self
        return _identity().__await__()
