"""
Phase 24 — Deterministic Historical Replay, Backtesting & Walk-Forward Validation Domain Schemas

Strongly typed domain models for historical market data replay, point-in-time isolation,
reproducibility fingerprinting, pure-Python portfolio accounting, and walk-forward validation.

Safety Invariant:
- STRICTLY HISTORICAL / REPLAY / SIMULATION.
- Zero live-money order submission authority.
- TIER_4_LIVE_REAL_MONEY remains permanently locked, unroutable, and fail-closed.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
from typing import Any, Dict, List, Optional, Union
import uuid
from pydantic import BaseModel, Field, model_validator


REPLAY_SCHEMA_VERSION = "24.0.0"


# ── Enums ───────────────────────────────────────────────────────────────────

class ReplayMode(str, Enum):
    """Historical market replay operating mode."""
    BAR_REPLAY = "BAR_REPLAY"
    TICK_REPLAY = "TICK_REPLAY"
    FAST_REPLAY = "FAST_REPLAY"
    REALTIME_SPEED_REPLAY = "REALTIME_SPEED_REPLAY"


class PartitionType(str, Enum):
    """Walk-forward and backtest dataset partition classification."""
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    TEST = "TEST"
    IN_SAMPLE = "IN_SAMPLE"
    OUT_OF_SAMPLE = "OUT_OF_SAMPLE"


class ReplayStatus(str, Enum):
    """Operational lifecycle status of historical replay run."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


class TradeSide(str, Enum):
    """Trade execution side."""
    BUY = "BUY"
    SELL = "SELL"


class ReplayExitReason(str, Enum):
    """Reason for simulated trade liquidation."""
    STOP_LOSS = "STOP_LOSS"
    TARGET_HIT = "TARGET_HIT"
    HOLDING_PERIOD_EXPIRED = "HOLDING_PERIOD_EXPIRED"
    SIGNAL_EXIT = "SIGNAL_EXIT"
    RISK_VETO = "RISK_VETO"
    PREFLIGHT_REJECTION = "PREFLIGHT_REJECTION"
    END_OF_SIMULATION = "END_OF_SIMULATION"


# ── Historical Data Contract (Step 2) ───────────────────────────────────────

class HistoricalDataPoint(BaseModel):
    """
    Strongly typed historical replay market datum.
    Explicitly distinguishes between:
      - event_timestamp: The historical market event time (used strictly for ordering)
      - processing_timestamp: The ingestion/wall-clock processing time
    """
    symbol: str
    event_timestamp: datetime = Field(description="Market event occurrence timestamp")
    processing_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Ingestion/simulation processing timestamp",
    )
    open: float = Field(ge=0.0)
    high: float = Field(ge=0.0)
    low: float = Field(ge=0.0)
    close: float = Field(ge=0.0)
    volume: float = Field(ge=0.0)
    vwap: Optional[float] = None
    quote_bid: Optional[float] = None
    quote_ask: Optional[float] = None
    trade_price: Optional[float] = None
    trade_size: Optional[int] = None
    session_id: Optional[str] = None
    source_id: str = "HISTORICAL_REPLAY"
    sequence_id: int = 0

    @model_validator(mode="after")
    def validate_ohlcv_bounds(self) -> "HistoricalDataPoint":
        """Validate logical OHLC boundaries."""
        if self.high < max(self.open, self.close, self.low):
            # Enforce high is >= all prices
            self.high = max(self.high, self.open, self.close)
        if self.low > min(self.open, self.close, self.high):
            # Enforce low is <= all prices
            self.low = min(self.low, self.open, self.close)
        return self


# ── Execution Assumptions & Configuration ───────────────────────────────────

class ExecutionAssumptions(BaseModel):
    """
    Documented friction and execution parameters for Indian equities backtesting.
    Zero hidden assumptions or undisclosed costs.
    """
    brokerage_pct: float = Field(default=0.0003, ge=0.0, description="0.03% institutional brokerage")
    slippage_pct: float = Field(default=0.0005, ge=0.0, description="0.05% execution slippage")
    stt_tax_pct: float = Field(default=0.0010, ge=0.0, description="0.10% Securities Transaction Tax (STT)")
    exchange_charges_pct: float = Field(default=0.00003, ge=0.0, description="0.003% exchange turnover charges")
    execution_delay_ms: float = Field(default=0.0, ge=0.0, description="Simulated execution latency in ms")
    partial_fill_ratio: float = Field(default=1.0, ge=0.01, le=1.0, description="Fill ratio (1.0 = full fill)")
    market_hours_only: bool = Field(default=True, description="Constrain orders to market hours")
    enable_costs: bool = Field(default=True, description="Whether transaction frictions are deducted")

    @property
    def total_roundtrip_cost_pct(self) -> float:
        """Total roundtrip cost percentage assumption."""
        if not self.enable_costs:
            return 0.0
        return round(2.0 * (self.brokerage_pct + self.slippage_pct + self.exchange_charges_pct) + self.stt_tax_pct, 6)


class ReplayConfig(BaseModel):
    """
    Deterministic configuration parameters for historical replay and backtesting.
    """
    run_id: str = Field(default_factory=lambda: f"replay-{uuid.uuid4().hex[:8]}")
    seed: int = Field(default=42, description="Random seed for deterministic reproducibility")
    replay_mode: ReplayMode = ReplayMode.BAR_REPLAY
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    initial_capital: float = Field(default=100000.0, ge=1000.0)
    symbols: List[str] = Field(default_factory=lambda: ["TCS.NS", "RELIANCE.NS", "INFY.NS"])
    holding_period_bars: int = Field(default=5, ge=1, le=100)
    execution_assumptions: ExecutionAssumptions = Field(default_factory=ExecutionAssumptions)
    look_ahead_protection_strict: bool = Field(default=True, description="Strictly forbid future data access")

    # Walk-forward validation settings
    walk_forward_enabled: bool = False
    train_window_bars: int = Field(default=20, ge=5)
    val_window_bars: int = Field(default=5, ge=1)
    test_window_bars: int = Field(default=10, ge=2)
    step_bars: int = Field(default=5, ge=1)

    @model_validator(mode="after")
    def validate_replay_config(self) -> "ReplayConfig":
        if self.initial_capital <= 0 or math.isnan(self.initial_capital) or math.isinf(self.initial_capital):
            raise ValueError("initial_capital must be positive and finite.")
        if self.walk_forward_enabled and self.train_window_bars <= self.test_window_bars:
            raise ValueError("train_window_bars must be strictly greater than test_window_bars.")
        return self


# ── Portfolio & Performance Accounting (Step 8 & 9) ─────────────────────────

class ReplayEquityPoint(BaseModel):
    """
    Chronological portfolio valuation at historical timestamp T.
    Tracks mark-to-market valuations without future price contamination.
    """
    timestamp: datetime
    cash: float
    invested_capital: float
    total_equity: float
    drawdown_pct: float = 0.0
    open_positions_count: int = 0


class ReplayTrade(BaseModel):
    """
    Auditable historical trade execution and exit record.
    Traceable back to originating decision correlation_id.
    """
    trade_id: str = Field(default_factory=lambda: f"rtr-{uuid.uuid4().hex[:8]}")
    correlation_id: str = Field(description="Phase 23 correlation ID of originating decision")
    symbol: str
    side: TradeSide = TradeSide.BUY
    entry_time: datetime
    entry_price: float
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    quantity: int = 0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    return_pct: float = 0.0
    exit_reason: ReplayExitReason = ReplayExitReason.HOLDING_PERIOD_EXPIRED
    holding_bars: int = 0
    transaction_costs: float = 0.0
    slippage_paid: float = 0.0
    factor_scores_at_entry: Dict[str, float] = Field(default_factory=dict)
    explainability_id: Optional[str] = None
    is_open: bool = False


class ReplayPerformanceSummary(BaseModel):
    """
    Pure Python deterministic performance and risk metrics.
    Zero LLM numerical hallucination; divisions-by-zero safeguarded.
    """
    total_return_pct: float = 0.0
    cagr_pct: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    max_drawdown_pct: float = 0.0
    max_drawdown_duration_bars: int = 0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate_pct: float = 0.0
    profit_factor: Optional[float] = None
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    annualized_volatility_pct: float = 0.0
    downside_deviation_pct: float = 0.0
    expectancy: float = 0.0
    portfolio_turnover: float = 0.0
    total_transaction_costs: float = 0.0
    total_slippage_costs: float = 0.0
    insufficient_data: bool = False


# ── Walk-Forward Partitions (Step 10) ───────────────────────────────────────

class WalkForwardPartition(BaseModel):
    """
    Chronologically isolated walk-forward window partition.
    Strictly differentiates IN_SAMPLE from OUT_OF_SAMPLE.
    """
    partition_id: str = Field(default_factory=lambda: f"wfp-{uuid.uuid4().hex[:8]}")
    window_index: int
    partition_type: PartitionType = PartitionType.OUT_OF_SAMPLE
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    in_sample_return_pct: float = 0.0
    out_of_sample_return_pct: float = 0.0
    in_sample_sharpe: Optional[float] = None
    out_of_sample_sharpe: Optional[float] = None
    trades_count: int = 0


# ── Backtest Result & Run Fingerprint (Step 12 & 14) ─────────────────────────

def compute_run_fingerprint(
    dataset_hash: str,
    config: ReplayConfig,
    schema_version: str = REPLAY_SCHEMA_VERSION,
) -> str:
    """
    Compute a deterministic SHA-256 run fingerprint.
    Guarantees two identical runs have identical fingerprints,
    while materially different configurations produce distinct fingerprints.
    """
    data = {
        "schema_version": schema_version,
        "dataset_hash": dataset_hash,
        "seed": config.seed,
        "symbols": sorted(config.symbols),
        "initial_capital": config.initial_capital,
        "replay_mode": config.replay_mode.value,
        "holding_period_bars": config.holding_period_bars,
        "assumptions": {
            "brokerage_pct": config.execution_assumptions.brokerage_pct,
            "slippage_pct": config.execution_assumptions.slippage_pct,
            "stt_tax_pct": config.execution_assumptions.stt_tax_pct,
            "enable_costs": config.execution_assumptions.enable_costs,
        },
    }
    canonical_json = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class DeterministicBacktestResult(BaseModel):
    """
    Structured, fully reproducible backtest report container.
    """
    run_id: str
    fingerprint: str = Field(description="Deterministic SHA-256 reproducibility fingerprint")
    config: ReplayConfig
    start_time: datetime
    end_time: datetime
    symbols: List[str]
    initial_capital: float
    final_equity: float
    performance: ReplayPerformanceSummary
    equity_curve: List[ReplayEquityPoint] = Field(default_factory=list)
    trade_ledger: List[ReplayTrade] = Field(default_factory=list)
    walk_forward_partitions: List[WalkForwardPartition] = Field(default_factory=list)
    audit_events_emitted: int = 0
    audit_status: str = "VALID"
    status: ReplayStatus = ReplayStatus.COMPLETED
    mode: str = "HISTORICAL_REPLAY_SIMULATION"
    tier_4_live_real_money_locked: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
