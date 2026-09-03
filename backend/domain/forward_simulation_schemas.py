"""
Phase 12 — Paper Trading & Live Forward Simulation Domain Schemas

Strongly typed domain models for forward market data normalization, market session
state classification, forward lifecycle auditing, simulation configuration, and
real-time session summaries.
"""

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field, model_validator


FORWARD_SIMULATION_VERSION = "12.0.0"


# ── Enums ───────────────────────────────────────────────────────────────────

class ForwardSimulationMode(str, Enum):
    """Execution and market data feed mode for Phase 12."""
    LIVE_STREAM = "LIVE_STREAM"
    PAPER_POLL = "PAPER_POLL"
    REPLAY_FEED = "REPLAY_FEED"
    MOCK_TICK = "MOCK_TICK"


class MarketSessionState(str, Enum):
    """Categorical market session and exchange calendar state."""
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PRE_OPEN = "PRE_OPEN"
    POST_CLOSE = "POST_CLOSE"
    WEEKEND = "WEEKEND"
    HOLIDAY = "HOLIDAY"
    DATA_STALE = "DATA_STALE"
    UNKNOWN = "UNKNOWN"


class ForwardEngineState(str, Enum):
    """Lifecycle state of the continuous forward simulation worker."""
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"
    ERROR = "ERROR"


class ForwardLifecycleStage(str, Enum):
    """Granular event stages of the forward decision & paper execution chain."""
    TICK_RECEIVED = "TICK_RECEIVED"
    SESSION_VALIDATED = "SESSION_VALIDATED"
    CANDIDATE_DISCOVERED = "CANDIDATE_DISCOVERED"
    ANALYSIS_STARTED = "ANALYSIS_STARTED"
    ANALYSIS_COMPLETED = "ANALYSIS_COMPLETED"
    DECISION_GENERATED = "DECISION_GENERATED"
    RISK_EVALUATED = "RISK_EVALUATED"
    SIZING_COMPLETED = "SIZING_COMPLETED"
    PREFLIGHT_VERIFIED = "PREFLIGHT_VERIFIED"
    PAPER_ORDER_SUBMITTED = "PAPER_ORDER_SUBMITTED"
    PAPER_FILL_EXECUTED = "PAPER_FILL_EXECUTED"
    PORTFOLIO_UPDATED = "PORTFOLIO_UPDATED"
    CYCLE_COMPLETED = "CYCLE_COMPLETED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


# ── Market Data Tick & Normalization Models ─────────────────────────────────

class MarketDataTick(BaseModel):
    """
    Normalized forward market update representing a single equity bar or tick.
    Guarantees finite positive numbers and strict timestamp validation.
    """
    tick_id: str = Field(default_factory=lambda: f"tick-{uuid.uuid4().hex[:8]}")
    symbol: str = Field(min_length=1, description="Ticker symbol (e.g. RELIANCE.NS)")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    price: float = Field(gt=0.0, description="Latest traded market price")
    open: Optional[float] = Field(default=None, gt=0.0)
    high: Optional[float] = Field(default=None, gt=0.0)
    low: Optional[float] = Field(default=None, gt=0.0)
    close: Optional[float] = Field(default=None, gt=0.0)
    volume: Optional[float] = Field(default=None, ge=0.0)
    bid: Optional[float] = Field(default=None, gt=0.0)
    ask: Optional[float] = Field(default=None, gt=0.0)
    source: str = Field(default="FORWARD_FEED", description="Data provider or generator source")
    session_state: MarketSessionState = Field(default=MarketSessionState.OPEN)
    is_stale: bool = Field(default=False)
    staleness_seconds: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def validate_numerical_integrity(self) -> "MarketDataTick":
        for field_name in ["price", "open", "high", "low", "close", "volume", "bid", "ask"]:
            val = getattr(self, field_name)
            if val is not None and (math.isnan(val) or math.isinf(val)):
                raise ValueError(f"Field '{field_name}' must be a finite numerical value, got {val}")
        
        # High-Low bound validation if both present
        if self.high is not None and self.low is not None and self.high < self.low:
            raise ValueError(f"High price ({self.high}) cannot be lower than Low price ({self.low})")
        
        return self


# ── Forward Simulation Configuration ─────────────────────────────────────────

class ForwardSimulationConfig(BaseModel):
    """
    Configuration parameters for live forward paper trading simulation.
    Safe default is PAPER mode with strict risk and preflight enforcement.
    """
    mode: ForwardSimulationMode = Field(default=ForwardSimulationMode.PAPER_POLL)
    universe_id: str = Field(default="NIFTY_50")
    poll_interval_seconds: float = Field(default=5.0, gt=0.0, le=3600.0)
    max_candidates_per_cycle: int = Field(default=5, ge=1, le=50)
    allow_execution: bool = Field(default=True, description="When true, approved orders submit to PaperBroker")
    market_hours_enforced: bool = Field(default=True, description="When true, trades are blocked outside market hours")
    max_data_age_seconds: float = Field(default=300.0, gt=0.0, description="Max permissible age before data is rejected as STALE")
    dedup_window_seconds: float = Field(default=60.0, ge=0.0, description="Window to prevent duplicate orders for the same signal")
    fill_ratio: float = Field(default=1.0, gt=0.0, le=1.0, description="Simulated execution fill percentage (1.0 = full fill)")
    slippage_pct: float = Field(default=0.0005, ge=0.0, le=0.05, description="Simulated slippage fraction (0.05%)")
    commission_rate: float = Field(default=0.0003, ge=0.0, le=0.02, description="Brokerage commission fraction (0.03%)")

    @model_validator(mode="after")
    def validate_config(self) -> "ForwardSimulationConfig":
        if math.isnan(self.poll_interval_seconds) or self.poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be a positive finite number.")
        return self


# ── Forward Lifecycle Audit & Events ─────────────────────────────────────────

class ForwardLifecycleEvent(BaseModel):
    """
    Audit event record tracking an individual step in the forward paper trading chain.
    """
    event_id: str = Field(default_factory=lambda: f"fevt-{uuid.uuid4().hex[:8]}")
    session_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    symbol: str
    stage: ForwardLifecycleStage
    details: str = ""
    data: Dict[str, Any] = Field(default_factory=dict)
    latency_ms: float = Field(default=0.0, ge=0.0)
    is_error: bool = False


# ── Forward Session Audit Summary ───────────────────────────────────────────

class ForwardSessionSummary(BaseModel):
    """
    Comprehensive operational summary of an active or completed forward simulation run.
    """
    session_id: str = Field(default_factory=lambda: f"fwd-ses-{uuid.uuid4().hex[:8]}")
    mode: ForwardSimulationMode = ForwardSimulationMode.PAPER_POLL
    state: ForwardEngineState = ForwardEngineState.STOPPED
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    stopped_at: Optional[datetime] = None
    ticks_processed: int = 0
    cycles_completed: int = 0
    candidates_discovered: int = 0
    pipeline_runs: int = 0
    approved_orders: int = 0
    rejected_orders: int = 0
    simulated_fills: int = 0
    total_volume_traded: float = 0.0
    total_commissions_paid: float = 0.0
    cash_balance: float = 100000.0
    total_equity: float = 100000.0
    open_positions_count: int = 0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    errors_count: int = 0
    recent_events: List[ForwardLifecycleEvent] = Field(default_factory=list)
