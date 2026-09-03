"""
Phase 26 — Forward Paper Trading, Shadow Validation & Drift Monitoring Domain Schemas

Strongly typed domain models for forward validation sessions, shadow decision tracking,
paper order execution auditing, realized outcome tracking (MFE / MAE), signal and strategy
drift monitoring, market regime transition logging, execution and data quality telemetry,
forward-vs-backtest comparison, and the 12-Category Forward Validation Scorecard.

Safety Invariant:
- STRICTLY VALIDATION, RESEARCH, SHADOW & PAPER EXECUTION ONLY.
- Zero live-money order submission authority.
- TIER_4_LIVE_REAL_MONEY remains permanently locked, unroutable, and fail-closed.
"""

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field, model_validator

from backend.domain.robustness_schemas import MarketRegimeType


FORWARD_VALIDATION_VERSION = "26.0.0"


# ── Enums ───────────────────────────────────────────────────────────────────

class ForwardSessionState(str, Enum):
    """Explicit lifecycle states for a forward validation session."""
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    DEGRADED = "DEGRADED"
    STOPPED = "STOPPED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ValidationMode(str, Enum):
    """Execution modality of the forward session."""
    SHADOW = "SHADOW"    # Zero order placement; hypothetical decisions and outcome tracking only
    PAPER = "PAPER"      # Passes through authoritative ExecutionGuard, RiskEngine, PreFlight, PaperBroker
    HYBRID = "HYBRID"    # Generates both shadow decisions and paper orders simultaneously


class DecisionOutcomeStatus(str, Enum):
    """Realized trade or shadow decision outcome classification."""
    PENDING = "PENDING"
    WIN = "WIN"
    LOSS = "LOSS"
    BREAKEVEN = "BREAKEVEN"
    STOPPED = "STOPPED"
    TARGET_REACHED = "TARGET_REACHED"
    TIME_EXIT = "TIME_EXIT"
    INVALIDATED = "INVALIDATED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class DriftState(str, Enum):
    """Statistical drift classification against historical reference baseline."""
    NORMAL = "NORMAL"
    WATCH = "WATCH"
    DRIFT = "DRIFT"
    SEVERE_DRIFT = "SEVERE_DRIFT"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ScorecardValidationStatus(str, Enum):
    """Overall validation health status from the 12-Category Scorecard."""
    VALIDATING = "VALIDATING"
    HEALTHY = "HEALTHY"
    WATCH = "WATCH"
    DEGRADED = "DEGRADED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


# ── Market & Decision Models (Step 4 & 5) ───────────────────────────────────

class MarketObservation(BaseModel):
    """
    Standardized market tick/bar observation ingested during forward validation.
    Strictly separates event time from processing time.
    """
    symbol: str
    price: float
    volume: float = 0.0
    high: Optional[float] = None
    low: Optional[float] = None
    event_timestamp: datetime
    processing_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tick_quality_ok: bool = True
    anomalies: List[str] = Field(default_factory=list)


class ShadowDecision(BaseModel):
    """
    Immutable hypothetical decision generated in SHADOW mode.
    Carries zero order-submission authority.
    """
    decision_id: str = Field(default_factory=lambda: f"shd-{uuid.uuid4().hex[:8]}")
    session_id: str
    correlation_id: str
    symbol: str
    direction: str = "BUY"
    signal_score: float = 0.0
    conviction_score: float = 0.0
    risk_state: str = "APPROVED"
    theoretical_entry: float
    theoretical_stop: float
    theoretical_target: float
    theoretical_size: int = 10
    vetoes: List[str] = Field(default_factory=list)
    rejection_reasons: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_immutable: bool = True


class PaperOrderObservation(BaseModel):
    """
    Authoritative simulated order executed via PaperBrokerAdapter.
    """
    order_id: str = Field(default_factory=lambda: f"pord-{uuid.uuid4().hex[:8]}")
    session_id: str
    decision_id: str
    correlation_id: str
    symbol: str
    side: str = "BUY"
    requested_price: float
    simulated_fill_price: float
    slippage: float = 0.0
    fees: float = 0.0
    execution_latency_ms: float = 0.0
    status: str = "FILLED"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Realized Outcome & Excursion Tracking (Step 6) ──────────────────────────

class RealizedOutcome(BaseModel):
    """
    Realized outcome tracking decision performance against subsequent price evolution.
    Measures Maximum Favorable Excursion (MFE) and Maximum Adverse Excursion (MAE).
    """
    outcome_id: str = Field(default_factory=lambda: f"out-{uuid.uuid4().hex[:8]}")
    decision_id: str
    session_id: str
    symbol: str
    entry_time: datetime
    exit_time: Optional[datetime] = None
    entry_price: float
    exit_price: Optional[float] = None
    maximum_favorable_excursion_pct: float = Field(
        default=0.0,
        description="Peak gain percentage during trade lifetime (MFE %)",
    )
    maximum_adverse_excursion_pct: float = Field(
        default=0.0,
        description="Worst draw percentage during trade lifetime (MAE %)",
    )
    realized_pnl: float = 0.0
    return_pct: float = 0.0
    holding_duration_seconds: float = 0.0
    status: DecisionOutcomeStatus = DecisionOutcomeStatus.PENDING
    exit_reason: str = "OPEN"


class DecisionOutcomeComparison(BaseModel):
    """Comparison between theoretical shadow decision and realized paper outcome."""
    decision_id: str
    symbol: str
    theoretical_pnl: float = 0.0
    realized_pnl: float = 0.0
    slippage_drag_pct: float = 0.0
    excursion_efficiency_pct: float = Field(
        default=0.0,
        description="Ratio of realized gain to MFE",
    )


# ── Drift & Telemetry Models (Step 8, 9, 10, 11) ────────────────────────────

class SignalDriftSnapshot(BaseModel):
    """Rolling statistical distribution tracking for factor and signal drift."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    factor_means: Dict[str, float] = Field(default_factory=dict)
    signal_mean: float = 0.0
    conviction_mean: float = 0.0
    baseline_signal_mean: float = 0.0
    drift_delta: float = 0.0
    drift_state: DriftState = DriftState.NORMAL


class StrategyDriftSnapshot(BaseModel):
    """Rolling behavioral drift monitoring (risk veto rate, trade frequency)."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    decisions_per_hour: float = 0.0
    risk_veto_frequency_pct: float = 0.0
    average_position_size: float = 0.0
    win_rate_rolling_pct: float = 0.0
    drift_state: DriftState = DriftState.NORMAL
    anomaly_notes: List[str] = Field(default_factory=list)


class ExecutionQualitySnapshot(BaseModel):
    """Execution latency and fill quality telemetry."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    decision_to_order_latency_ms_p50: float = 0.0
    decision_to_order_latency_ms_p95: float = 0.0
    order_to_fill_latency_ms_p50: float = 0.0
    order_to_fill_latency_ms_p95: float = 0.0
    order_to_fill_latency_ms_p99: float = 0.0
    simulated_slippage_p50: float = 0.0
    simulated_slippage_p95: float = 0.0
    fill_rate_pct: float = 100.0
    stale_data_rejections: int = 0


class RegimeTransitionEvent(BaseModel):
    """Point-in-Time market regime transition event."""
    transition_id: str = Field(default_factory=lambda: f"trans-{uuid.uuid4().hex[:8]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    previous_regime: MarketRegimeType
    new_regime: MarketRegimeType
    strategy_exposure_pct: float = 0.0
    active_positions_count: int = 0
    risk_state: str = "NORMAL"


class DataQualitySnapshot(BaseModel):
    """Health telemetry for forward market data streaming."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tick_rate_per_sec: float = 0.0
    stale_ticks_count: int = 0
    duplicate_ticks_count: int = 0
    out_of_order_count: int = 0
    invalid_prices_count: int = 0
    quality_score: float = Field(default=100.0, ge=0.0, le=100.0)


class ForwardPerformanceSnapshot(BaseModel):
    """Realized mark-to-market performance of forward paper portfolio."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    equity: float = 100000.0
    cash: float = 100000.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate_pct: float = 0.0
    trade_count: int = 0
    profit_factor: Optional[float] = None


# ── Forward vs Backtest Comparison (Step 7) ─────────────────────────────────

class ForwardVsBacktestComparison(BaseModel):
    """Direct comparison between historical expectation and forward observed metrics."""
    metric_name: str
    expected_backtest_value: float
    observed_forward_value: float
    deviation_pct: float = 0.0
    is_degraded: bool = False
    sample_sufficient: bool = True
    notes: str = ""


# ── Scorecard & Master Containers (Step 13) ─────────────────────────────────

class ForwardScorecardCategory(BaseModel):
    """Evaluation score and findings for one of 12 forward validation dimensions."""
    category_name: str
    score: float = Field(ge=0.0, le=100.0)
    passed: bool = True
    status: ScorecardValidationStatus = ScorecardValidationStatus.HEALTHY
    evidence: str = ""
    key_metrics: Dict[str, Any] = Field(default_factory=dict)
    insufficient_data: bool = False


class ForwardValidationScorecard(BaseModel):
    """
    Unified 12-Category Forward Validation Scorecard.
    Synthesizes real-time empirical validation evidence into an overall status.
    """
    overall_score: float = Field(default=0.0, ge=0.0, le=100.0)
    status: ScorecardValidationStatus = ScorecardValidationStatus.VALIDATING
    categories: List[ForwardScorecardCategory] = Field(default_factory=list)
    primary_weaknesses: List[str] = Field(default_factory=list)
    strongest_evidence: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class ForwardValidationSession(BaseModel):
    """Master forward validation session entity."""
    session_id: str = Field(default_factory=lambda: f"fvs-{uuid.uuid4().hex[:8]}")
    mode: ValidationMode = ValidationMode.HYBRID
    state: ForwardSessionState = ForwardSessionState.CREATED
    symbols: List[str] = Field(default_factory=lambda: ["TCS.NS", "RELIANCE.NS", "INFY.NS"])
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    configuration_fingerprint: str = ""
    initial_capital: float = 100000.0
    decisions_count: int = 0
    orders_count: int = 0
    outcomes_count: int = 0


class ForwardValidationReport(BaseModel):
    """
    Comprehensive, auditable report for a forward validation session.
    """
    report_id: str = Field(default_factory=lambda: f"fvr-{uuid.uuid4().hex[:8]}")
    session_id: str
    session: ForwardValidationSession
    performance: ForwardPerformanceSnapshot
    execution_quality: ExecutionQualitySnapshot
    data_quality: DataQualitySnapshot
    signal_drift: SignalDriftSnapshot
    strategy_drift: StrategyDriftSnapshot
    regime_transitions: List[RegimeTransitionEvent] = Field(default_factory=list)
    decisions: List[ShadowDecision] = Field(default_factory=list)
    outcomes: List[RealizedOutcome] = Field(default_factory=list)
    comparisons: List[ForwardVsBacktestComparison] = Field(default_factory=list)
    scorecard: ForwardValidationScorecard
    audit_status: str = "VALID"
    tier_4_live_real_money_locked: bool = True
