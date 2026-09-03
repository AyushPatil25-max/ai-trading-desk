"""
Phase 16 — Live Evaluation & Staged Broker Execution Domain Schemas

Strongly typed domain models for automated agent evaluation loops, Bull vs. Bear
grading matrix, specialist attribution, Brier score calibration, execution tier stages,
and staged broker execution readiness audits.
"""

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


class AgentGrade(str, Enum):
    """Objective academic letter grades assigned based on empirical skill scores."""
    A_PLUS = "A+"
    A = "A"
    B_PLUS = "B+"
    B = "B"
    C = "C"
    D = "D"
    F = "F"


class ExecutionTier(str, Enum):
    """
    Formal staged execution tiers enforcing progressive readiness verification.
    TIER_4_LIVE_REAL_MONEY is strictly fail-closed and locked in this phase.
    """
    TIER_0_INTERNAL_PAPER = "TIER_0_INTERNAL_PAPER"
    TIER_1_FORWARD_PAPER = "TIER_1_FORWARD_PAPER"
    TIER_2_SANDBOX_STAGED = "TIER_2_SANDBOX_STAGED"
    TIER_3_READINESS_AUDITED = "TIER_3_READINESS_AUDITED"
    TIER_4_LIVE_REAL_MONEY = "TIER_4_LIVE_REAL_MONEY"


class PredictionOutcomeRecord(BaseModel):
    """
    Paired record binding agent forecasts from a Trading OS run with actual realized market returns.
    """
    prediction_id: str = Field(default_factory=lambda: f"pred-{uuid.uuid4().hex[:8]}")
    run_id: str
    symbol: str
    decision_action: str
    calibrated_conviction: float
    bull_confidence: float
    bear_confidence: float
    specialist_signals: Dict[str, str] = Field(default_factory=dict)
    actual_return_pct: Optional[float] = None
    actual_direction: Optional[str] = None
    is_win: Optional[bool] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SpecialistScorecard(BaseModel):
    """
    Empirical performance scorecard for an individual specialist research agent.
    """
    specialist_name: str
    skill_score: float = Field(ge=0.0, le=100.0, description="Composite score 0-100")
    letter_grade: AgentGrade
    directional_accuracy: float = Field(ge=0.0, le=1.0)
    win_rate: float = Field(ge=0.0, le=1.0)
    total_predictions: int = 0
    correct_predictions: int = 0
    avg_return_contribution: float = 0.0
    information_coefficient: float = Field(default=0.0, description="Correlation between forecast and return")


class DebateEvaluationSummary(BaseModel):
    """
    Evaluative summary comparing Bull Specialist vs. Bear Specialist adversarial skill.
    """
    bull_skill_score: float = Field(ge=0.0, le=100.0)
    bull_grade: AgentGrade
    bull_accuracy: float = Field(ge=0.0, le=1.0)
    bear_skill_score: float = Field(ge=0.0, le=100.0)
    bear_grade: AgentGrade
    bear_accuracy: float = Field(ge=0.0, le=1.0)
    winning_side_frequency: Dict[str, float] = Field(default_factory=dict)
    total_debates_evaluated: int = 0
    contradiction_resolution_rate: float = Field(default=1.0, ge=0.0, le=1.0)


class CalibrationMetrics(BaseModel):
    """
    Statistical calibration metrics evaluating probability realism (Brier score & ECE).
    """
    brier_score: float = Field(ge=0.0, le=1.0, description="Mean squared error of probabilistic conviction")
    expected_calibration_error: float = Field(ge=0.0, le=1.0)
    overconfidence_score: float = Field(default=0.0, description="Positive = overconfident, Negative = underconfident")
    total_samples: int = 0
    calibration_grade: str = "GOOD"


class AgentPerformanceMatrix(BaseModel):
    """
    Comprehensive multi-agent performance evaluation snapshot across all agents.
    """
    evaluation_id: str = Field(default_factory=lambda: f"eval-{uuid.uuid4().hex[:8]}")
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_runs_evaluated: int = 0
    total_completed_trades: int = 0
    overall_accuracy: float = Field(ge=0.0, le=1.0)
    debate_summary: DebateEvaluationSummary
    specialists: List[SpecialistScorecard] = Field(default_factory=list)
    calibration: CalibrationMetrics
    dynamic_weight_adjustments: Dict[str, float] = Field(
        default_factory=dict,
        description="Empirical weight multipliers (0.7 to 1.3) based on historical accuracy"
    )


class ReadinessAuditItem(BaseModel):
    """
    Individual operational requirement item evaluated for staged broker execution readiness.
    """
    check_name: str
    category: str
    passed: bool
    threshold_description: str
    actual_value: str
    severity: str
    message: str


class StagedReadinessReport(BaseModel):
    """
    Authoritative audit report establishing staged execution readiness.
    Explicitly affirms TIER_4_LIVE_REAL_MONEY is permanently fail-closed and locked.
    """
    audit_id: str = Field(default_factory=lambda: f"audit-{uuid.uuid4().hex[:8]}")
    audit_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    active_tier: ExecutionTier
    is_tier3_certified: bool
    tier4_live_blocked: bool = True
    checks: List[ReadinessAuditItem] = Field(default_factory=list)
    passed_checks_count: int = 0
    failed_checks_count: int = 0
    summary_message: str
