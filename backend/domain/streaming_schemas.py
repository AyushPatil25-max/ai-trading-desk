"""
Phase 18 — Distributed Real-Time Streaming & High-Frequency Telemetry Ingestion Schemas

Strongly typed domain models for real-time market event streaming, subscription routing,
queue backpressure strategies, telemetry health metrics, and distributed paper worker states.
"""

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field, model_validator


STREAMING_ENGINE_VERSION = "18.0.0"


# ── Event Types & Routing Enums ──────────────────────────────────────────────

class StreamEventType(str, Enum):
    """Categorical stream event types."""
    MARKET_TICK = "MARKET_TICK"
    MARKET_QUOTE = "MARKET_QUOTE"
    MARKET_TRADE = "MARKET_TRADE"
    MARKET_BAR = "MARKET_BAR"
    TELEMETRY_EVENT = "TELEMETRY_EVENT"
    SYSTEM_EVENT = "SYSTEM_EVENT"
    EXECUTION_EVENT = "EXECUTION_EVENT"
    HEARTBEAT = "HEARTBEAT"


class BackpressureStrategy(str, Enum):
    """Queue backpressure handling policy when consumer queue reaches capacity."""
    DROP_OLDEST = "DROP_OLDEST"
    REJECT_NEWEST = "REJECT_NEWEST"
    BLOCK_WITH_TIMEOUT = "BLOCK_WITH_TIMEOUT"


# ── Core Event Container ──────────────────────────────────────────────────────

class StreamEvent(BaseModel):
    """
    Standardized normalized real-time event container.
    Guarantees consistent metadata across all ingested market ticks and telemetry events.
    """
    event_id: str = Field(default_factory=lambda: f"evt-{uuid.uuid4().hex[:10]}")
    event_type: StreamEventType
    symbol: str = Field(min_length=1, description="Ticker symbol or 'SYSTEM'")
    source: str = Field(default="STREAM_INGEST", description="Source provider or subsystem")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Occurrence timestamp")
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Ingestion timestamp")
    sequence_num: Optional[int] = Field(default=None, description="Monotonically increasing sequence number if available")
    data: Dict[str, Any] = Field(default_factory=dict, description="Event payload data")
    is_valid: bool = Field(default=True, description="Whether event passed numerical integrity checks")
    is_stale: bool = Field(default=False, description="Whether event timestamp exceeds maximum age threshold")
    is_duplicate: bool = Field(default=False, description="Whether event was identified as a duplicate")
    is_out_of_order: bool = Field(default=False, description="Whether event sequence arrived out of order")
    validation_error: Optional[str] = Field(default=None, description="Validation failure details if invalid")

    @model_validator(mode="after")
    def validate_payload_numbers(self) -> "StreamEvent":
        # Check numerical fields in payload for NaN or Inf
        for k, v in self.data.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                if self.is_valid and (math.isnan(v) or math.isinf(v)):
                    raise ValueError(f"Payload field '{k}' contains non-finite float: {v}")
                if self.is_valid and k in ("price", "bid", "ask", "high", "low", "open", "close") and v <= 0.0:
                    raise ValueError(f"Payload price field '{k}' must be strictly positive (> 0.0), got {v}")
        return self


# ── Subscription Configuration ────────────────────────────────────────────────

class StreamSubscription(BaseModel):
    """Configuration for a consumer registering with the StreamManager."""
    consumer_id: str = Field(default_factory=lambda: f"consumer-{uuid.uuid4().hex[:8]}")
    symbols: List[str] = Field(default_factory=lambda: ["*"], description="Target symbols or ['*'] for all")
    event_types: List[StreamEventType] = Field(
        default_factory=lambda: [
            StreamEventType.MARKET_TICK,
            StreamEventType.TELEMETRY_EVENT,
            StreamEventType.EXECUTION_EVENT,
            StreamEventType.SYSTEM_EVENT,
        ]
    )
    queue_capacity: int = Field(default=500, ge=1, le=10000)
    backpressure_strategy: BackpressureStrategy = Field(default=BackpressureStrategy.DROP_OLDEST)


# ── Stream Health & Telemetry Metrics ─────────────────────────────────────────

class StreamHealthMetrics(BaseModel):
    """Real-time calculated metrics tracking throughput, latency, quality, and queues."""
    events_received: int = 0
    events_accepted: int = 0
    events_rejected: int = 0
    events_duplicated: int = 0
    events_stale: int = 0
    events_out_of_order: int = 0
    events_dropped: int = 0
    processing_latency_avg_ms: float = 0.0
    processing_latency_p50_ms: float = 0.0
    processing_latency_p95_ms: float = 0.0
    processing_latency_p99_ms: float = 0.0
    queue_depth: int = 0
    queue_capacity: int = 1000
    queue_utilization_pct: float = 0.0
    events_per_second: float = 0.0
    active_consumers_count: int = 0
    reconnect_count: int = 0
    uptime_seconds: float = 0.0
    last_event_timestamp: Optional[datetime] = None
    per_symbol_event_rate: Dict[str, float] = Field(default_factory=dict)


# ── Distributed Worker Models ─────────────────────────────────────────────────

class WorkerHealthStatus(BaseModel):
    """Operational status of an individual distributed paper simulation worker."""
    worker_id: str
    symbol: str
    is_alive: bool = False
    state: str = Field(default="STOPPED", description="STOPPED, RUNNING, PAUSED, ERROR")
    ticks_processed: int = 0
    decisions_generated: int = 0
    paper_orders_submitted: int = 0
    last_processed_time: Optional[datetime] = None
    failure_count: int = 0
    error_message: Optional[str] = None


class DistributedWorkerPoolStatus(BaseModel):
    """Aggregate status snapshot of the multi-symbol paper simulation pool."""
    total_workers: int = 0
    healthy_workers: int = 0
    failed_workers: int = 0
    workers: Dict[str, WorkerHealthStatus] = Field(default_factory=dict)
    total_ticks_processed: int = 0
    total_paper_orders: int = 0
    fail_closed_guarantee: str = Field(
        default="Real-money broker execution is strictly disabled and rejected unconditionally."
    )
