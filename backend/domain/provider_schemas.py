"""
Phase 21 — Market Data Provider Orchestration & Resiliency Domain Schemas

Deterministic schemas defining circuit breaker states, provider health tracking,
failure classifications, data-quality validation results, and orchestrator status.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class ProviderStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


class FailureType(str, Enum):
    TIMEOUT = "TIMEOUT"
    NETWORK_ERROR = "NETWORK_ERROR"
    API_ERROR = "API_ERROR"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    UNKNOWN = "UNKNOWN"


class DataQualityCheckType(str, Enum):
    PRICE_BOUNDS = "PRICE_BOUNDS"
    NUMERICAL_INTEGRITY = "NUMERICAL_INTEGRITY"
    TIMESTAMP_FRESHNESS = "TIMESTAMP_FRESHNESS"
    TIMESTAMP_FUTURE = "TIMESTAMP_FUTURE"
    OHLC_RELATIONSHIPS = "OHLC_RELATIONSHIPS"
    DUPLICATE_OBSERVATIONS = "DUPLICATE_OBSERVATIONS"
    SEQUENCE_ORDER = "SEQUENCE_ORDER"
    DISCONTINUITY = "DISCONTINUITY"
    CONTEXT_COMPLETENESS = "CONTEXT_COMPLETENESS"


class ValidationResult(BaseModel):
    model_config = {"frozen": True}

    is_valid: bool
    failure_reasons: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    checks_passed: List[DataQualityCheckType] = Field(default_factory=list)
    checks_failed: List[DataQualityCheckType] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProviderHealthMetrics(BaseModel):
    provider_name: str
    priority: int = 1
    is_primary: bool = False
    status: ProviderStatus = ProviderStatus.HEALTHY
    circuit_state: CircuitState = CircuitState.CLOSED
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    timeout_count: int = 0
    validation_rejection_count: int = 0
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    availability_rate: float = 1.0
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    last_success_timestamp: Optional[datetime] = None
    last_failure_timestamp: Optional[datetime] = None
    last_failure_type: Optional[FailureType] = None
    last_failure_reason: Optional[str] = None


class ProviderOrchestratorStatus(BaseModel):
    model_config = {"frozen": True}

    system_status: ProviderStatus = ProviderStatus.HEALTHY
    primary_provider: str
    active_provider: str
    fallback_level: int = 0
    is_fallback_active: bool = False
    degraded_warning: Optional[str] = None
    provider_metrics: Dict[str, ProviderHealthMetrics] = Field(default_factory=dict)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
