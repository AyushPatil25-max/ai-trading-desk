"""
Phase 6.8 — Historical Backtesting & Decision Validation Domain Schemas

Strongly typed domain models for Point-In-Time (PIT) backtest configurations,
forward outcome measurements, historical decision snapshots, risk veto analyses,
and aggregate performance reports.
"""

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field, model_validator


BACKTEST_ENGINE_VERSION = "6.8.0"


# ── Enums ───────────────────────────────────────────────────────────────────

class BacktestMode(str, Enum):
    """Backtesting execution mode."""
    SINGLE_DECISION = "SINGLE_DECISION"
    BATCH = "BATCH"


class EntryExecutionRule(str, Enum):
    """Rule determining the hypothetical trade entry price."""
    CLOSE_AT_SIGNAL = "CLOSE_AT_SIGNAL"
    NEXT_OPEN = "NEXT_OPEN"


class OutcomeStatus(str, Enum):
    """Realized forward outcome status."""
    WIN = "WIN"
    LOSS = "LOSS"
    SCRATCH = "SCRATCH"
    STOPPED_OUT = "STOPPED_OUT"
    TARGET_HIT = "TARGET_HIT"
    ACTIVE = "ACTIVE"
    VETOED = "VETOED"


class BacktestDataQuality(str, Enum):
    """Quality and completeness of the point-in-time historical data."""
    FRESH = "FRESH"
    STALE = "STALE"
    PARTIAL = "PARTIAL"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


# ── Configuration Model ─────────────────────────────────────────────────────

class BacktestConfig(BaseModel):
    """
    Explicit configuration parameters for historical backtesting and validation.
    No hidden parameters or undisclosed execution assumptions.
    """
    mode: BacktestMode = BacktestMode.SINGLE_DECISION
    entry_rule: EntryExecutionRule = EntryExecutionRule.CLOSE_AT_SIGNAL
    holding_period_bars: int = Field(default=5, ge=1, le=100)
    forward_horizons: List[int] = Field(default_factory=lambda: [1, 3, 5, 10, 20])

    # Transaction Costs & Friction (Explicitly Documented)
    brokerage_pct: float = Field(default=0.0003, ge=0.0, description="0.03% brokerage assumption")
    slippage_pct: float = Field(default=0.0005, ge=0.0, description="0.05% baseline execution slippage")
    stt_tax_pct: float = Field(default=0.0010, ge=0.0, description="0.10% STT/turnover tax assumption")
    enable_costs: bool = True

    # Sample Size Thresholds
    min_sample_size: int = Field(default=3, ge=1)

    @model_validator(mode="after")
    def validate_config(self) -> "BacktestConfig":
        """Strict validation of backtest parameters."""
        for cost_attr in ("brokerage_pct", "slippage_pct", "stt_tax_pct"):
            val = getattr(self, cost_attr)
            if math.isnan(val) or math.isinf(val):
                raise ValueError(f"{cost_attr} must be a finite number.")
            if val < 0.0 or val > 0.10:
                raise ValueError(f"{cost_attr} must be between 0.0 and 0.10 (10%).")

        if not self.forward_horizons:
            raise ValueError("forward_horizons list cannot be empty.")
        if any(h <= 0 for h in self.forward_horizons):
            raise ValueError("All forward horizons must be positive integers.")
        return self


# ── Outcome Models ──────────────────────────────────────────────────────────

class ForwardOutcome(BaseModel):
    """
    Deterministic forward measurement of price progression and exit realization AFTER decision.
    Strictly isolated from decision-time information.
    """
    horizon_bars: int
    entry_timestamp: datetime
    exit_timestamp: datetime
    entry_price: float
    exit_price: float
    forward_return_pct: float
    mfe_pct: float = Field(default=0.0, description="Maximum Favorable Excursion percentage")
    mae_pct: float = Field(default=0.0, description="Maximum Adverse Excursion percentage")
    drawdown_pct: float = Field(default=0.0, description="Maximum holding period drawdown percentage")

    # Stop-Loss & Target Events
    stop_loss_hit: bool = False
    gap_through_stop: bool = False
    target_hit: bool = False

    # Financial Realizations
    gross_pnl: float = 0.0
    total_cost: float = 0.0
    net_pnl: float = 0.0
    net_return_pct: float = 0.0
    outcome_status: OutcomeStatus = OutcomeStatus.ACTIVE


class HistoricalDecisionSnapshot(BaseModel):
    """
    Immutable frozen snapshot of system state at timestamp T.
    Zero future leakage; records what the system decided using only information available at T.
    """
    decision_id: str
    evaluation_timestamp: datetime
    symbol: str

    # Snapshot Sub-components
    market_context_summary: Dict[str, Any] = Field(default_factory=dict)
    evidence_snapshot: Dict[str, Any] = Field(default_factory=dict)
    debate_snapshot: Dict[str, Any] = Field(default_factory=dict)
    committee_snapshot: Dict[str, Any] = Field(default_factory=dict)
    conviction_snapshot: Dict[str, Any] = Field(default_factory=dict)
    regime_snapshot: Dict[str, Any] = Field(default_factory=dict)
    portfolio_snapshot: Dict[str, Any] = Field(default_factory=dict)
    risk_snapshot: Dict[str, Any] = Field(default_factory=dict)
    sizing_snapshot: Dict[str, Any] = Field(default_factory=dict)
    scenario_snapshot: Dict[str, Any] = Field(default_factory=dict)

    data_quality: BacktestDataQuality = BacktestDataQuality.FRESH
    provenance: List[Dict[str, Any]] = Field(default_factory=list)


# ── Backtest Results Models ─────────────────────────────────────────────────

class SingleDecisionBacktestResult(BaseModel):
    """
    Complete evaluation of a single historical decision and its post-decision forward realization.
    Supports dual synchronous and awaitable invocation.
    """
    backtest_id: str = Field(default_factory=lambda: f"bt-{uuid.uuid4().hex[:8]}")
    decision_snapshot: HistoricalDecisionSnapshot
    forward_outcomes: Dict[int, ForwardOutcome] = Field(default_factory=dict)
    primary_outcome: ForwardOutcome
    decision_quality_score: float = Field(default=0.5, ge=0.0, le=1.0)
    scenario_vs_actual: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    data_quality: BacktestDataQuality = BacktestDataQuality.FRESH

    def __await__(self):
        """Allows dual synchronous or awaitable invocation."""
        async def _passthrough():
            return self
        return _passthrough().__await__()


class AggregatePerformanceReport(BaseModel):
    """
    Deterministic summary statistics across a set of historical backtested decisions.
    Reports INSUFFICIENT_SAMPLE if sample size is too small for statistical validity.
    """
    total_decisions: int = 0
    accepted_decisions: int = 0
    vetoed_decisions: int = 0
    wins: int = 0
    losses: int = 0
    scratches: int = 0

    win_rate_pct: Optional[float] = None
    avg_return_pct: Optional[float] = None
    median_return_pct: Optional[float] = None
    avg_win_pct: Optional[float] = None
    avg_loss_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    profit_factor: Optional[float] = None
    expectancy: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None

    insufficient_sample: bool = False
    sample_notes: str = ""


class RiskVetoAnalysis(BaseModel):
    """
    Audit of risk vetoes across historical evaluations.
    Evaluates decision quality rather than hindsight profitability.
    """
    total_vetoes: int = 0
    veto_reasons_distribution: Dict[str, int] = Field(default_factory=dict)
    vetoed_fwd_return_avg: Optional[float] = None
    prevented_loss_count: int = 0
    missed_gain_count: int = 0
    summary: str = ""


class BatchBacktestResult(BaseModel):
    """
    Structured multi-decision historical backtest evaluation result.
    Supports dual synchronous and awaitable invocation.
    """
    batch_id: str = Field(default_factory=lambda: f"batch-bt-{uuid.uuid4().hex[:8]}")
    config: BacktestConfig
    results: List[SingleDecisionBacktestResult] = Field(default_factory=list)
    performance_report: AggregatePerformanceReport
    risk_veto_analysis: RiskVetoAnalysis
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def __await__(self):
        """Allows dual synchronous or awaitable invocation."""
        async def _passthrough():
            return self
        return _passthrough().__await__()
