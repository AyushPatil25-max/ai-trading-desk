"""
Phase 32 — Real-Time Execution Telemetry & Drift Observability REST API Routes

Endpoints:
- GET /api/execution/telemetry/status
- GET /api/execution/telemetry/metrics
- GET /api/execution/telemetry/latency
- GET /api/execution/telemetry/drift
- GET /api/execution/telemetry/history
- GET /api/execution/telemetry/history/{execution_id}

Safety Invariants:
- OBSERVABILITY ONLY: No endpoint mutates execution state, risk limits, or arms live trading.
- Responses are sanitized: Zero plaintext credentials or confirmation tokens returned.
- Bounded queries: Query limits strictly enforced against unbounded requests.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query

from backend.domain.execution_decision_schemas import ExecutionMode
from backend.domain.execution_telemetry_schemas import (
    DriftDetectionReport,
    ExecutionHealthMetrics,
    ExecutionLatencyProfile,
    ExecutionTelemetrySample,
)
from backend.execution.execution_telemetry import global_execution_telemetry_collector
from backend.config.execution_telemetry_config import get_all_telemetry_config


execution_telemetry_router = APIRouter(
    prefix="/api/execution/telemetry",
    tags=["Execution Telemetry & Observability"],
)


@execution_telemetry_router.get("/status")
def get_telemetry_status() -> Dict[str, Any]:
    """
    Get operational telemetry status, system health summary, and active threshold configurations.
    """
    metrics = global_execution_telemetry_collector.get_health_metrics()
    config = get_all_telemetry_config()
    return {
        "health_state": metrics.health_state.value,
        "total_executions": metrics.total_executions,
        "success_rate": metrics.success_rate,
        "failure_rate": metrics.failure_rate,
        "rejection_rate": metrics.rejection_rate,
        "last_sample_timestamp": metrics.last_sample_timestamp.isoformat() if metrics.last_sample_timestamp else None,
        "active_configuration": config,
    }


@execution_telemetry_router.get("/metrics", response_model=ExecutionHealthMetrics)
def get_health_metrics() -> ExecutionHealthMetrics:
    """
    Get detailed execution health statistics, rates, and failure counts.
    """
    return global_execution_telemetry_collector.get_health_metrics()


@execution_telemetry_router.get("/latency", response_model=ExecutionLatencyProfile)
def get_latency_profile(
    mode: Optional[ExecutionMode] = Query(None, description="Filter by PAPER or LIVE execution mode"),
    limit: Optional[int] = Query(None, ge=1, le=1000, description="Limit to last N samples"),
) -> ExecutionLatencyProfile:
    """
    Get statistical latency percentiles (p50, p90, p95, p99, min, max, mean) for decision and orchestration.
    """
    return global_execution_telemetry_collector.get_latency_profile(mode=mode, limit=limit)


@execution_telemetry_router.get("/drift", response_model=DriftDetectionReport)
def get_drift_report(
    baseline_window: Optional[int] = Query(None, ge=10, le=500, description="Baseline sample window size"),
    recent_window: Optional[int] = Query(None, ge=5, le=100, description="Recent sample window size"),
) -> DriftDetectionReport:
    """
    Evaluate and retrieve operational drift report for latency, error rate, and rejection trends.
    """
    return global_execution_telemetry_collector.detect_drift(
        baseline_window=baseline_window,
        recent_window=recent_window,
    )


@execution_telemetry_router.get("/history", response_model=List[ExecutionTelemetrySample])
def get_recent_telemetry_history(
    limit: int = Query(50, ge=1, le=200, description="Number of recent samples to return"),
) -> List[ExecutionTelemetrySample]:
    """
    Retrieve list of recent execution telemetry samples.
    """
    return global_execution_telemetry_collector.get_recent_samples(limit=limit)


@execution_telemetry_router.get("/history/{execution_id}", response_model=List[ExecutionTelemetrySample])
def get_samples_by_execution_id(execution_id: str) -> List[ExecutionTelemetrySample]:
    """
    Retrieve telemetry samples associated with a specific execution ID.
    """
    samples = global_execution_telemetry_collector.get_samples_by_execution(execution_id)
    if not samples:
        raise HTTPException(
            status_code=404,
            detail=f"No telemetry samples found for execution_id: {execution_id}",
        )
    return samples
