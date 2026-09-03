"""
Phase 10 — Opportunity Scanner & Continuous Background Discovery Domain Schemas

Strongly typed domain models for candidate discovery, universe management,
deterministic screening, priority queues, and scanner operational health.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


OPPORTUNITY_SCANNER_VERSION = "10.0.0"


# ── Enums ───────────────────────────────────────────────────────────────────

class CandidateScreeningStatus(str, Enum):
    """Categorical lifecycle status of an opportunity candidate."""
    SCREENED = "SCREENED"
    SHORTLISTED = "SHORTLISTED"
    ANALYZED = "ANALYZED"
    PASSED_TO_TRADING_OS = "PASSED_TO_TRADING_OS"
    REJECTED = "REJECTED"
    DEGRADED = "DEGRADED"


class CandidatePriority(str, Enum):
    """Deterministic priority levels for queued candidate evaluation."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ScannerState(str, Enum):
    """Operational lifecycle state of the background discovery worker."""
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"
    ERROR = "ERROR"


class UniverseID(str, Enum):
    """Supported market universes for candidate discovery."""
    NIFTY_50 = "NIFTY_50"
    NIFTY_500 = "NIFTY_500"
    CUSTOM = "CUSTOM"


# ── Models ──────────────────────────────────────────────────────────────────

class MarketUniverse(BaseModel):
    """
    Structured definition of an approved stock universe.
    Decouples symbol lists from code and allows new universes to be added cleanly.
    """
    universe_id: str
    name: str
    description: str = ""
    symbols: List[str] = Field(default_factory=list)
    active: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DeterministicScreenMetrics(BaseModel):
    """
    Inexpensive quantitative and technical metrics extracted during Stage A.
    Pure Python calculation — zero LLM math.
    """
    current_price: float = 0.0
    volume_20d_avg: float = 0.0
    turnover_cr: float = 0.0
    rsi_14: Optional[float] = None
    ema_20: Optional[float] = None
    ema_50: Optional[float] = None
    trend_alignment_score: float = 0.0
    momentum_score: float = 0.0
    volatility_annualized: float = 0.0
    liquidity_score: float = 0.0
    regime_alignment_score: float = 0.0
    data_age_seconds: float = 0.0
    bar_count: int = 0


class OpportunityCandidate(BaseModel):
    """
    Strongly typed candidate representation produced by Opportunity Scanner.
    Represents a discovered prospective setup awaiting or passing through the Trading OS.
    Never presents an unverified setup as a 'guaranteed' winner.
    """
    candidate_id: str = Field(default_factory=lambda: f"cand-{uuid.uuid4().hex[:10]}")
    symbol: str
    universe: str
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    discovery_score: float = Field(default=0.0, ge=0.0, le=100.0)
    priority: CandidatePriority = CandidatePriority.MEDIUM
    screening_status: CandidateScreeningStatus = CandidateScreeningStatus.SCREENED
    screening_reasons: List[str] = Field(default_factory=list)
    metrics: Optional[DeterministicScreenMetrics] = None
    data_quality: str = "HIGH"
    market_regime: Optional[str] = None

    # Downstream Trading OS integration fields (populated after Stage B)
    pipeline_status: Optional[str] = None
    final_decision: Optional[str] = None
    conviction: Optional[float] = None
    risk_status: Optional[str] = None
    approved_quantity: Optional[int] = None
    trading_os_run_id: Optional[str] = None
    execution_order_id: Optional[str] = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def generate_candidate_id(cls, symbol: str, universe: str, cycle_timestamp: datetime) -> str:
        """
        Generate a deterministic candidate ID based on symbol, universe, and hourly cycle window.
        Guarantees idempotency and prevents duplicate submissions in a short window.
        """
        window_str = cycle_timestamp.strftime("%Y%m%d%H")
        token_src = f"{symbol.upper()}:{universe.upper()}:{window_str}"
        digest = hashlib.sha256(token_src.encode("utf-8")).hexdigest()[:12]
        return f"cand-{digest}"


class OpportunityScannerConfig(BaseModel):
    """
    Configuration parameters for the Opportunity Scanner and background discovery worker.
    """
    universe_id: str = "NIFTY_50"
    scan_interval_seconds: float = 300.0
    batch_size: int = 25
    max_candidates_per_cycle: int = 5
    max_concurrent_analysis: int = 3
    max_queue_size: int = 100
    min_discovery_score: float = 40.0
    min_liquidity_cr: float = 1.0
    min_price: float = 10.0
    max_price: float = 100000.0
    min_historical_bars: int = 20
    max_market_data_age_seconds: float = 300.0
    timeout_seconds: float = 30.0
    retry_limit: int = 2
    allow_execution: bool = True
    fill_ratio: float = 1.0
    dedup_window_seconds: float = 3600.0


class ScannerCycleSummary(BaseModel):
    """
    Structured summary of a completed discovery cycle.
    """
    scan_id: str = Field(default_factory=lambda: f"scan-{uuid.uuid4().hex[:8]}")
    universe_id: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: float = 0.0
    universe_size: int = 0
    screened_count: int = 0
    shortlisted_count: int = 0
    analyzed_count: int = 0
    passed_count: int = 0
    risk_rejected_count: int = 0
    paper_execution_count: int = 0
    shortlisted_candidates: List[OpportunityCandidate] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class ScannerHealthStatus(BaseModel):
    """
    Operational health snapshot of the Opportunity Scanner background subsystem.
    """
    state: ScannerState = ScannerState.STOPPED
    is_healthy: bool = True
    queue_size: int = 0
    total_cycles_completed: int = 0
    last_scan_at: Optional[datetime] = None
    last_scan_duration_ms: float = 0.0
    active_workers: int = 0
    errors_count: int = 0
    current_universe: str = "NIFTY_50"
