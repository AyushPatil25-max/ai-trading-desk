"""
Phase 11 — High-Fidelity Historical Backtesting & Evaluation Harness Domain Schemas

Strongly typed domain models for multi-period point-in-time historical simulation,
portfolio accounting, performance attribution, risk metrics, walk-forward analysis,
Monte Carlo resampling, bias warnings, and master evaluation reporting.
"""

from datetime import datetime
from enum import Enum
import math
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field, model_validator


EVALUATION_HARNESS_VERSION = "11.0.0"


# ── Enums ───────────────────────────────────────────────────────────────────

class UniverseMode(str, Enum):
    """Historical universe reconstruction mode."""
    POINT_IN_TIME = "POINT_IN_TIME"
    CURRENT_CONSTITUENTS = "CURRENT_CONSTITUENTS"


class BiasType(str, Enum):
    """Types of biases audited during historical simulation."""
    LOOK_AHEAD_BIAS = "LOOK_AHEAD_BIAS"
    SURVIVORSHIP_BIAS = "SURVIVORSHIP_BIAS"
    STALE_DATA_BIAS = "STALE_DATA_BIAS"
    UNREALISTIC_EXECUTION_BIAS = "UNREALISTIC_EXECUTION_BIAS"
    COST_OMISSION_BIAS = "COST_OMISSION_BIAS"


class BiasSeverity(str, Enum):
    """Severity classification of detected bias."""
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


class RebalanceFrequency(str, Enum):
    """Frequency of candidate discovery and rebalancing."""
    BAR = "BAR"
    DAILY = "DAILY"


class ExitReason(str, Enum):
    """Reason for position closing."""
    STOP_LOSS = "STOP_LOSS"
    TARGET_HIT = "TARGET_HIT"
    HOLDING_PERIOD_EXPIRED = "HOLDING_PERIOD_EXPIRED"
    SIGNAL_EXIT = "SIGNAL_EXIT"
    RISK_VETO = "RISK_VETO"
    PREFLIGHT_REJECTION = "PREFLIGHT_REJECTION"
    MANUAL = "MANUAL"


# ── Cost & Configuration Models ─────────────────────────────────────────────

class TransactionCostConfig(BaseModel):
    """
    Explicit, documented transaction cost parameters for Indian market equities.
    No hidden assumptions or undisclosed cost omissions.
    """
    brokerage_pct: float = Field(default=0.0003, ge=0.0, description="0.03% institutional brokerage")
    slippage_pct: float = Field(default=0.0005, ge=0.0, description="0.05% baseline execution slippage")
    stt_tax_pct: float = Field(default=0.0010, ge=0.0, description="0.10% Securities Transaction Tax (STT)")
    exchange_charges_pct: float = Field(default=0.00003, ge=0.0, description="0.003% exchange & clearing turnover charges")
    enable_costs: bool = True

    @property
    def total_roundtrip_cost_pct(self) -> float:
        """Total roundtrip cost percentage assumption."""
        if not self.enable_costs:
            return 0.0
        return round(2.0 * (self.brokerage_pct + self.slippage_pct + self.exchange_charges_pct) + self.stt_tax_pct, 6)


class HistoricalEvaluationConfig(BaseModel):
    """
    Deterministic configuration parameters for historical replay harness.
    """
    run_id: str = Field(default_factory=lambda: f"eval-{uuid.uuid4().hex[:8]}")
    universe_id: str = "NIFTY_50"
    universe_mode: UniverseMode = UniverseMode.POINT_IN_TIME
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    initial_capital: float = Field(default=100000.0, ge=1000.0)
    rebalance_frequency: RebalanceFrequency = RebalanceFrequency.DAILY
    holding_period_bars: int = Field(default=5, ge=1, le=100)
    max_candidates_per_bar: int = Field(default=3, ge=1, le=20)
    cost_config: TransactionCostConfig = Field(default_factory=TransactionCostConfig)
    benchmark_symbol: str = "^NSEI"

    # Walk-forward settings
    walk_forward_enabled: bool = False
    train_window_bars: int = Field(default=20, ge=5)
    test_window_bars: int = Field(default=10, ge=2)
    step_bars: int = Field(default=5, ge=1)

    # Monte Carlo / Resampling settings
    monte_carlo_runs: int = Field(default=100, ge=10, le=1000)
    random_seed: int = 42
    fill_ratio: float = 1.0

    @model_validator(mode="after")
    def validate_eval_config(self) -> "HistoricalEvaluationConfig":
        if self.initial_capital <= 0 or math.isnan(self.initial_capital) or math.isinf(self.initial_capital):
            raise ValueError("initial_capital must be positive and finite.")
        if self.walk_forward_enabled and self.train_window_bars <= self.test_window_bars:
            raise ValueError("train_window_bars must be strictly greater than test_window_bars.")
        return self


# ── Context and Ledger Models ───────────────────────────────────────────────

class PointInTimeHistoricalContext(BaseModel):
    """
    Guaranteed point-in-time market context strictly verified <= evaluation timestamp T.
    Zero future information contamination.
    """
    evaluation_timestamp: datetime
    symbol: str
    historical_price: float
    historical_bars: List[Dict[str, Any]] = Field(default_factory=list)
    historical_volume: float = 0.0
    available_fundamentals: Dict[str, Any] = Field(default_factory=dict)
    available_news: List[Dict[str, Any]] = Field(default_factory=list)
    corporate_actions_known_at_time: List[Dict[str, Any]] = Field(default_factory=list)
    market_context_id: Optional[str] = None


class HistoricalTradeRecord(BaseModel):
    """
    Auditable historical trade execution and exit record.
    Tracks entry, exit, holding period, and transaction-cost-adjusted financial realization.
    """
    trade_id: str = Field(default_factory=lambda: f"htr-{uuid.uuid4().hex[:8]}")
    symbol: str
    side: str = "BUY"
    entry_timestamp: datetime
    entry_price: float
    exit_timestamp: Optional[datetime] = None
    exit_price: Optional[float] = None
    quantity: int = 0
    gross_pnl: float = 0.0
    transaction_costs: float = 0.0
    net_pnl: float = 0.0
    net_return_pct: float = 0.0
    holding_period_bars: int = 0
    entry_reason: str = ""
    exit_reason: ExitReason = ExitReason.HOLDING_PERIOD_EXPIRED
    conviction_score: float = 0.0
    risk_status: str = "SAFE"
    market_regime: str = "UNKNOWN"
    candidate_discovery_score: float = 0.0
    trading_os_run_id: Optional[str] = None
    is_open: bool = False


class EquityCurvePoint(BaseModel):
    """
    Point on the chronological portfolio equity curve at timestamp T.
    Tracks mark-to-market valuations without future price leaks.
    """
    timestamp: datetime
    cash: float
    invested_capital: float
    open_positions_market_value: float
    total_equity: float
    drawdown_pct: float = 0.0
    benchmark_equity: float = 100000.0
    open_positions_count: int = 0


# ── Analytics Models ────────────────────────────────────────────────────────

class PerformanceMetrics(BaseModel):
    """
    Pure Python deterministic performance metrics.
    Zero LLM numerical calculations.
    """
    total_return_pct: float = 0.0
    cagr_pct: float = 0.0
    annualized_volatility_pct: float = 0.0
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    max_drawdown_pct: float = 0.0
    max_drawdown_duration_bars: int = 0
    win_rate_pct: float = 0.0
    loss_rate_pct: float = 0.0
    profit_factor: Optional[float] = None
    average_win_pct: float = 0.0
    average_loss_pct: float = 0.0
    expectancy_pct: float = 0.0
    total_trades: int = 0
    portfolio_turnover: float = 0.0
    average_holding_period_bars: float = 0.0
    insufficient_sample: bool = False


class RiskMetrics(BaseModel):
    """
    Auditable portfolio risk constraints and veto metrics.
    """
    max_portfolio_exposure_pct: float = 0.0
    max_single_position_exposure_pct: float = 0.0
    largest_loss_pct: float = 0.0
    largest_daily_loss_pct: float = 0.0
    risk_veto_count: int = 0
    preflight_rejection_count: int = 0


class BenchmarkComparison(BaseModel):
    """
    Comparison of strategy performance against a passive market benchmark (e.g. NIFTY 50).
    """
    benchmark_symbol: str = "^NSEI"
    benchmark_total_return_pct: float = 0.0
    benchmark_cagr_pct: float = 0.0
    benchmark_volatility_pct: float = 0.0
    benchmark_max_drawdown_pct: float = 0.0
    benchmark_sharpe_ratio: Optional[float] = None
    alpha_pct: Optional[float] = None
    beta: Optional[float] = None
    outperformed_benchmark: bool = False


class PerformanceAttribution(BaseModel):
    """
    Multi-dimensional performance breakdown by regime, discovery score tier, and conviction.
    """
    by_regime: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    by_score_tier: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    by_conviction_tier: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class WalkForwardSplit(BaseModel):
    """
    Metrics for a single in-sample (train) vs out-of-sample (test) walk-forward partition.
    """
    split_index: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    in_sample_return_pct: float = 0.0
    out_of_sample_return_pct: float = 0.0
    out_of_sample_sharpe: Optional[float] = None


class MonteCarloResult(BaseModel):
    """
    Deterministic bootstrap resampling sensitivity analysis of trade returns.
    """
    resample_runs: int = 100
    random_seed: int = 42
    mean_return_pct: float = 0.0
    p05_return_pct: float = 0.0
    p50_return_pct: float = 0.0
    p95_return_pct: float = 0.0
    probability_of_loss_pct: float = 0.0
    probability_drawdown_exceeds_10pct: float = 0.0


class BiasWarning(BaseModel):
    """
    Audit alert identifying potential bias or data distortion in historical evaluation.
    """
    bias_type: BiasType
    severity: BiasSeverity
    message: str
    affected_period: Optional[str] = None


class DataQualityAudit(BaseModel):
    """
    Audit of data cleanliness, missing observations, and temporal anomalies.
    """
    missing_bars_count: int = 0
    stale_bars_count: int = 0
    future_bars_detected_count: int = 0
    rejected_timestamps_count: int = 0
    quality_score: float = 1.0
    audit_notes: List[str] = Field(default_factory=list)


# ── Master Evaluation Report Model ──────────────────────────────────────────

class HistoricalEvaluationReport(BaseModel):
    """
    Master auditable historical evaluation report returned by HistoricalEvaluationHarness.
    Supports dual synchronous and awaitable invocation.
    """
    run_id: str
    config: HistoricalEvaluationConfig
    started_at: datetime
    completed_at: datetime
    duration_ms: float
    total_bars_evaluated: int
    performance_metrics: PerformanceMetrics
    risk_metrics: RiskMetrics
    benchmark_comparison: BenchmarkComparison
    attribution: PerformanceAttribution
    equity_curve: List[EquityCurvePoint] = Field(default_factory=list)
    trade_ledger: List[HistoricalTradeRecord] = Field(default_factory=list)
    walk_forward_splits: List[WalkForwardSplit] = Field(default_factory=list)
    monte_carlo: Optional[MonteCarloResult] = None
    bias_warnings: List[BiasWarning] = Field(default_factory=list)
    data_quality: DataQualityAudit = Field(default_factory=DataQualityAudit)
    execution_mode: str = "PAPER_ONLY"
    system_version: str = EVALUATION_HARNESS_VERSION

    def __await__(self):
        """Allows dual synchronous or awaitable invocation."""
        async def _passthrough():
            return self
        return _passthrough().__await__()
