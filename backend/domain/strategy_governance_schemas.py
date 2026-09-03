"""
Phase 29 — Automated Strategy Governance, Model Lifecycle & Champion/Challenger Validation Domain Schemas

Strongly-typed Pydantic domain models and enums for strategy lifecycle tracking,
version registry with SHA-256 config fingerprints, 12-dimension champion/challenger comparison,
conservative statistical promotion gates, automated rollback triggers, and governance policies.

Safety Invariants:
- STRICTLY OBSERVATIONAL & GOVERNANCE ONLY: Zero authority to place orders or mutate risk limits.
- Pure Python deterministic calculations: Zero LLM numerical calculations.
- TIER_4_LIVE_REAL_MONEY remains permanently locked, unroutable, and fail-closed.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field, model_validator


GOVERNANCE_SCHEMA_VERSION = "29.0.0"


# ── Canonical Enums ───────────────────────────────────────────────────────────

class StrategyLifecycleState(str, Enum):
    """Formal strategy lifecycle states."""
    CANDIDATE = "CANDIDATE"
    BACKTESTING = "BACKTESTING"
    VALIDATED = "VALIDATED"
    CHALLENGER = "CHALLENGER"
    CHAMPION = "CHAMPION"
    DEPRECATED = "DEPRECATED"
    RETIRED = "RETIRED"
    ROLLED_BACK = "ROLLED_BACK"


class StrategyRole(str, Enum):
    """Role assigned to a strategy version in the governance system."""
    CHAMPION = "CHAMPION"
    CHALLENGER = "CHALLENGER"
    CANDIDATE = "CANDIDATE"
    RETIRED = "RETIRED"


class GovernanceDecision(str, Enum):
    """Formal governance decisions."""
    PROMOTE = "PROMOTE"
    DEMOTE = "DEMOTE"
    RETIRE = "RETIRE"
    ROLLBACK = "ROLLBACK"
    HOLD = "HOLD"
    REJECT = "REJECT"


class GateStatus(str, Enum):
    """Evaluation status for promotion and validation gates."""
    PASSED = "PASSED"
    FAILED = "FAILED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    BLOCKED = "BLOCKED"


class RollbackReason(str, Enum):
    """Categorized triggers for strategy rollback."""
    DRAWDOWN_BREACH = "DRAWDOWN_BREACH"
    DRIFT_DETECTED = "DRIFT_DETECTED"
    FORWARD_DIVERGENCE = "FORWARD_DIVERGENCE"
    MANUAL = "MANUAL"
    EMERGENCY = "EMERGENCY"


# ── Performance & Evidence Models ─────────────────────────────────────────────

class StrategyPerformanceSnapshot(BaseModel):
    """
    Standardized performance snapshot used for governance comparison and gate evaluation.
    Guarantees pure-Python numerical sanity (no NaN/Inf).
    """
    total_trades: int = Field(default=0, ge=0)
    winning_trades: int = Field(default=0, ge=0)
    losing_trades: int = Field(default=0, ge=0)
    win_rate_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    total_return_pct: float = 0.0
    cagr_pct: float = 0.0
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    max_drawdown_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    profit_factor: Optional[float] = None
    calmar_ratio: Optional[float] = None
    recovery_factor: Optional[float] = None
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    annualized_volatility_pct: float = 0.0
    out_of_sample_tested: bool = False
    forward_tested: bool = False
    insufficient_data: bool = False


class ValidationEvidence(BaseModel):
    """Evidence artifact supporting a strategy version's lifecycle progression."""
    evidence_id: str = Field(default_factory=lambda: f"ev-{uuid.uuid4().hex[:8]}")
    evidence_type: str  # e.g. "BACKTEST_REPORT", "ROBUSTNESS_SCORECARD", "FORWARD_VALIDATION"
    source_id: str      # run_id or session_id
    score: float = Field(default=0.0, ge=0.0, le=100.0)
    passed: bool = True
    summary: str = ""
    metrics: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Strategy Version Model ───────────────────────────────────────────────────

class StrategyVersion(BaseModel):
    """
    Immutable representation of a strategy version with SHA-256 configuration fingerprint.
    """
    strategy_id: str = Field(default_factory=lambda: f"strat-{uuid.uuid4().hex[:8]}")
    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = "SYSTEM"
    state: StrategyLifecycleState = StrategyLifecycleState.CANDIDATE
    role: StrategyRole = StrategyRole.CANDIDATE
    config_fingerprint: str = ""
    parameters: Dict[str, Any] = Field(default_factory=dict)
    performance: StrategyPerformanceSnapshot = Field(default_factory=StrategyPerformanceSnapshot)
    evidence: List[ValidationEvidence] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    promoted_at: Optional[datetime] = None
    retired_at: Optional[datetime] = None
    is_locked: bool = False

    @model_validator(mode="after")
    def compute_fingerprint_if_missing(self) -> "StrategyVersion":
        if not self.config_fingerprint:
            canonical_repr = json.dumps(
                {"name": self.name, "version": self.version, "parameters": self.parameters},
                sort_keys=True,
                default=str,
            )
            self.config_fingerprint = hashlib.sha256(canonical_repr.encode("utf-8")).hexdigest()
        return self


# ── Comparison & Gate Models ─────────────────────────────────────────────────

class DimensionScore(BaseModel):
    """Score for a single dimension in the 12-dimension comparison grid."""
    dimension_name: str
    champion_value: Optional[float] = None
    challenger_value: Optional[float] = None
    champion_score: float = Field(ge=0.0, le=100.0)
    challenger_score: float = Field(ge=0.0, le=100.0)
    weight: float = Field(default=1.0, ge=0.1)
    winner: str = "TIE"  # "CHAMPION", "CHALLENGER", "TIE"
    description: str = ""


class ChampionChallengerComparison(BaseModel):
    """
    12-dimension deterministic comparison between Champion and Challenger strategies.
    """
    comparison_id: str = Field(default_factory=lambda: f"cmp-{uuid.uuid4().hex[:8]}")
    champion_id: str
    challenger_id: str
    champion_name: str
    challenger_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    dimensions: List[DimensionScore] = Field(default_factory=list)
    champion_composite_score: float = Field(default=0.0, ge=0.0, le=100.0)
    challenger_composite_score: float = Field(default=0.0, ge=0.0, le=100.0)
    score_delta: float = 0.0
    overall_winner: str = "TIE"
    recommendation: GovernanceDecision = GovernanceDecision.HOLD
    rationale: str = ""


class GateCheck(BaseModel):
    """Individual gate check result within a promotion evaluation."""
    gate_name: str
    status: GateStatus = GateStatus.PASSED
    required_value: Any
    actual_value: Any
    passed: bool = True
    evidence: str = ""


class PromotionGateResult(BaseModel):
    """
    Conservative statistical evaluation of whether a Challenger strategy can be promoted to Champion.
    """
    evaluation_id: str = Field(default_factory=lambda: f"pgr-{uuid.uuid4().hex[:8]}")
    challenger_id: str
    champion_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    all_gates_passed: bool = False
    gate_checks: List[GateCheck] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    confidence_level_pct: float = Field(default=95.0, ge=80.0, le=99.9)
    recommendation: GovernanceDecision = GovernanceDecision.REJECT


# ── Governance Policy & Audit Models ──────────────────────────────────────────

class GovernancePolicy(BaseModel):
    """
    Configurable, bounds-checked thresholds for strategy promotion and rollback.
    """
    min_trade_count: int = Field(default=30, ge=10, le=1000)
    min_sharpe_improvement_pct: float = Field(default=5.0, ge=0.0, le=100.0)
    max_drawdown_tolerance_pct: float = Field(default=20.0, ge=5.0, le=50.0)
    max_relative_drawdown_increase_pct: float = Field(default=10.0, ge=0.0, le=50.0)
    min_win_rate_pct: float = Field(default=40.0, ge=20.0, le=90.0)
    min_profit_factor: float = Field(default=1.1, ge=0.8, le=5.0)
    require_out_of_sample: bool = True
    require_forward_validation: bool = True
    confidence_level_pct: float = Field(default=95.0, ge=90.0, le=99.0)
    rollback_max_drawdown_pct: float = Field(default=25.0, ge=10.0, le=50.0)
    rollback_drift_threshold: float = Field(default=0.6, ge=0.2, le=1.0)
    champion_protection_lock: bool = True


class GovernanceDecisionRecord(BaseModel):
    """
    Immutable audit record for formal governance decisions.
    """
    decision_id: str = Field(default_factory=lambda: f"gdec-{uuid.uuid4().hex[:8]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    decision: GovernanceDecision
    strategy_id: str
    target_role: Optional[StrategyRole] = None
    previous_state: StrategyLifecycleState
    new_state: StrategyLifecycleState
    rationale: str
    operator: str = "SYSTEM_GOVERNANCE"
    gate_evaluation_id: Optional[str] = None
    config_fingerprint: str = ""
    decision_hash: str = ""

    @model_validator(mode="after")
    def compute_decision_hash(self) -> "GovernanceDecisionRecord":
        if not self.decision_hash:
            data = {
                "decision_id": self.decision_id,
                "timestamp": self.timestamp.isoformat(),
                "decision": self.decision.value,
                "strategy_id": self.strategy_id,
                "previous_state": self.previous_state.value,
                "new_state": self.new_state.value,
                "rationale": self.rationale,
            }
            self.decision_hash = hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()
        return self


class RollbackTrigger(BaseModel):
    """Event detailing an automated or manual rollback of a champion strategy."""
    trigger_id: str = Field(default_factory=lambda: f"rb-{uuid.uuid4().hex[:8]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    champion_id: str
    reason: RollbackReason
    trigger_metric: str
    trigger_value: float
    threshold_value: float
    fallback_strategy_id: Optional[str] = None
    details: str = ""


class ChampionRecord(BaseModel):
    """High-level summary of the currently active Champion strategy."""
    strategy_id: str
    name: str
    version: str
    promoted_at: datetime
    defenses_count: int = 0
    performance: StrategyPerformanceSnapshot
    config_fingerprint: str


class ChallengerRecord(BaseModel):
    """High-level summary of an active Challenger strategy."""
    strategy_id: str
    name: str
    version: str
    registered_at: datetime
    composite_score: float = 0.0
    performance: StrategyPerformanceSnapshot
    config_fingerprint: str


class GovernanceStatusSummary(BaseModel):
    """Operational summary of the strategy governance engine."""
    schema_version: str = GOVERNANCE_SCHEMA_VERSION
    total_strategies_count: int = 0
    active_champion: Optional[ChampionRecord] = None
    active_challengers: List[ChallengerRecord] = Field(default_factory=list)
    state_distribution: Dict[str, int] = Field(default_factory=dict)
    total_decisions_count: int = 0
    last_decision: Optional[GovernanceDecisionRecord] = None
    policy: GovernancePolicy = Field(default_factory=GovernancePolicy)
    system_health: str = "HEALTHY"
    tier_4_live_real_money_locked: bool = True
