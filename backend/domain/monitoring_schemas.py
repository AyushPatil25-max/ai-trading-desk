"""
Phase 13 — Real-Time Monitoring & System Health Engine Domain Schemas

Strongly typed domain models for system-wide component health, pipeline stage
monitoring, latency measurement, data freshness evaluation, execution telemetry
metrics, and dashboard contracts. Strictly read-only and downstream.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


MONITORING_VERSION = "13.0.0"


# ── Enums ───────────────────────────────────────────────────────────────────

class ComponentHealthStatus(str, Enum):
    """Operational health status of a single Trading OS subsystem."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    UNAVAILABLE = "UNAVAILABLE"


class SystemHealthLevel(str, Enum):
    """Consolidated system-level health status."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"
    OFFLINE = "OFFLINE"


class PipelineStageStatus(str, Enum):
    """Auditable state of an individual pipeline stage."""
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    DEGRADED = "DEGRADED"
    STALE_DATA = "STALE_DATA"
    NOT_RUN = "NOT_RUN"


class ComponentID(str, Enum):
    """Canonical component identifiers for all 16 monitored subsystems."""
    MARKET_CONTEXT = "MARKET_CONTEXT"
    SPECIALISTS = "SPECIALISTS"
    EVIDENCE_AGGREGATOR = "EVIDENCE_AGGREGATOR"
    DEBATE_ENGINE = "DEBATE_ENGINE"
    INVESTMENT_COMMITTEE = "INVESTMENT_COMMITTEE"
    CONVICTION_CALIBRATOR = "CONVICTION_CALIBRATOR"
    MARKET_REGIME_ENGINE = "MARKET_REGIME_ENGINE"
    PORTFOLIO_INTELLIGENCE_ENGINE = "PORTFOLIO_INTELLIGENCE_ENGINE"
    SCENARIO_ENGINE = "SCENARIO_ENGINE"
    RISK_ENGINE = "RISK_ENGINE"
    POSITION_SIZING = "POSITION_SIZING"
    EXECUTION_PREFLIGHT_ENGINE = "EXECUTION_PREFLIGHT_ENGINE"
    PAPER_BROKER_ADAPTER = "PAPER_BROKER_ADAPTER"
    FORWARD_SIMULATION_ENGINE = "FORWARD_SIMULATION_ENGINE"
    OPPORTUNITY_SCANNER = "OPPORTUNITY_SCANNER"
    EXECUTION_TELEMETRY_ENGINE = "EXECUTION_TELEMETRY_ENGINE"


# ── Core Component Health Models ────────────────────────────────────────────

class ComponentHealthRecord(BaseModel):
    """
    Detailed operational record for an individual Trading OS component.
    """
    component_id: str
    name: str
    status: ComponentHealthStatus = ComponentHealthStatus.HEALTHY
    is_safety_critical: bool = False
    last_successful_at: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    last_latency_ms: float = 0.0
    avg_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    execution_count: int = 0
    failure_count: int = 0
    consecutive_failures: int = 0
    error_message: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class StageHealthRecord(BaseModel):
    """
    Observational record for a single pipeline stage execution.
    """
    stage_name: str
    status: PipelineStageStatus = PipelineStageStatus.NOT_RUN
    duration_ms: float = 0.0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


# ── Data Freshness Models ───────────────────────────────────────────────────

class DataFreshnessStatus(BaseModel):
    """
    Deterministic freshness check results for market, evidence, portfolio, and telemetry data.
    """
    is_fresh: bool = True
    market_data_age_seconds: float = 0.0
    evidence_age_seconds: float = 0.0
    specialist_age_seconds: float = 0.0
    portfolio_age_seconds: float = 0.0
    telemetry_age_seconds: float = 0.0
    stale_components: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


# ── Pipeline Monitoring Models ──────────────────────────────────────────────

class PipelineRunMonitorReport(BaseModel):
    """
    Master audit summary of a single 14-stage Trading OS pipeline run.
    """
    report_id: str = Field(default_factory=lambda: f"mon-{uuid.uuid4().hex[:8]}")
    run_id: str
    symbol: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_latency_ms: float = 0.0
    abnormal_latency_detected: bool = False
    stale_data_detected: bool = False
    pipeline_terminated_early: bool = False
    termination_reason: Optional[str] = None
    successful_stages: List[str] = Field(default_factory=list)
    failed_stages: List[str] = Field(default_factory=list)
    skipped_stages: List[str] = Field(default_factory=list)
    degraded_stages: List[str] = Field(default_factory=list)
    stages: Dict[str, StageHealthRecord] = Field(default_factory=dict)


# ── Execution Telemetry Monitoring Models ───────────────────────────────────

class ExecutionHealthMetrics(BaseModel):
    """
    Simulated paper execution metrics tracked by the monitoring layer.
    Strictly paper-only.
    """
    orders_submitted: int = 0
    orders_accepted: int = 0
    orders_rejected: int = 0
    orders_filled: int = 0
    orders_cancelled: int = 0
    positions_opened: int = 0
    positions_closed: int = 0
    current_open_positions: int = 0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_equity: float = 100000.0
    cash_balance: float = 100000.0
    last_execution_at: Optional[datetime] = None
    mode: str = "PAPER_ONLY"


# ── Master Configuration & System Health Summary ────────────────────────────

class MonitoringConfig(BaseModel):
    """
    Deterministic configuration parameters for the system health monitor.
    """
    market_data_max_age_seconds: float = 60.0
    evidence_max_age_seconds: float = 300.0
    specialist_max_age_seconds: float = 300.0
    portfolio_max_age_seconds: float = 300.0
    telemetry_max_age_seconds: float = 60.0
    abnormal_pipeline_latency_threshold_ms: float = 10000.0
    abnormal_stage_latency_threshold_ms: float = 3000.0
    max_consecutive_failures_allowed: int = 3


class SystemHealthSummary(BaseModel):
    """
    Unified, dashboard-ready snapshot of complete Trading OS health.
    """
    engine_version: str = MONITORING_VERSION
    overall_health: SystemHealthLevel = SystemHealthLevel.HEALTHY
    status_badge: str = "ALL_SYSTEMS_OPERATIONAL"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    uptime_seconds: float = 0.0
    components_count: int = 16
    healthy_components_count: int = 16
    degraded_components_count: int = 0
    failed_components_count: int = 0
    unavailable_components_count: int = 0
    safety_critical_healthy: bool = True
    data_freshness: DataFreshnessStatus = Field(default_factory=DataFreshnessStatus)
    execution_metrics: ExecutionHealthMetrics = Field(default_factory=ExecutionHealthMetrics)
    recent_alerts: List[str] = Field(default_factory=list)
    active_kill_switch: bool = False
