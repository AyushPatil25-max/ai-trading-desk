"""
Phase 13 — Real-Time Monitoring & System Health Engine REST Routes

Exposes read-only operational telemetry, component health records, pipeline
run audits, latency metrics, and paper execution metrics under `/api/monitor/*`.
Strictly read-only and downstream.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, status

from backend.domain.monitoring_schemas import (
    ComponentHealthRecord,
    ExecutionHealthMetrics,
    PipelineRunMonitorReport,
    SystemHealthSummary,
)
from backend.application.system_health_monitor import global_health_monitor

monitoring_router = APIRouter(prefix="/api/monitor", tags=["Monitoring & Health"])


@monitoring_router.get(
    "/health",
    response_model=SystemHealthSummary,
    summary="Master System Health Summary",
)
def get_system_health() -> SystemHealthSummary:
    """
    Retrieve deterministic overall Trading OS health, component status counts,
    data freshness indicators, and active kill switch status.
    """
    return global_health_monitor.get_system_health()


@monitoring_router.get(
    "/components",
    response_model=Dict[str, ComponentHealthRecord],
    summary="List All Monitored Subsystem Health Records",
)
def get_all_components_health() -> Dict[str, ComponentHealthRecord]:
    """
    Retrieve operational health records, latencies, and execution statistics
    for all 16 monitored Trading OS subsystems.
    """
    return global_health_monitor.get_components_health()


@monitoring_router.get(
    "/components/{component_id}",
    response_model=ComponentHealthRecord,
    summary="Get Single Component Health Record",
)
def get_component_health(component_id: str) -> ComponentHealthRecord:
    """
    Retrieve detailed operational health for a specific subsystem by ID.
    """
    rec = global_health_monitor.get_component_health(component_id.upper())
    if not rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitored component '{component_id}' not found.",
        )
    return rec


@monitoring_router.get(
    "/pipeline",
    response_model=List[PipelineRunMonitorReport],
    summary="Query Pipeline Execution Audit History",
)
def get_pipeline_history(
    limit: int = Query(default=20, ge=1, le=100, description="Max runs to return"),
) -> List[PipelineRunMonitorReport]:
    """
    Retrieve chronological audit reports for recent 14-stage pipeline runs,
    including stage latencies, skipped stages, and early terminations.
    """
    return global_health_monitor.get_pipeline_history(limit=limit)


@monitoring_router.get(
    "/pipeline/latest",
    response_model=Optional[PipelineRunMonitorReport],
    summary="Get Most Recent Pipeline Run Report",
)
def get_latest_pipeline_report() -> Optional[PipelineRunMonitorReport]:
    """
    Retrieve the most recent pipeline execution report.
    """
    report = global_health_monitor.get_latest_pipeline_report()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No pipeline runs recorded yet.",
        )
    return report


@monitoring_router.get(
    "/telemetry",
    response_model=Dict[str, Any],
    summary="Execution Telemetry & Paper Trading Health",
)
def get_telemetry_health() -> Dict[str, Any]:
    """
    Retrieve aggregate execution metrics and operational telemetry snapshot.
    """
    health = global_health_monitor.get_system_health()
    metrics = global_health_monitor.get_execution_metrics()
    return {
        "engine_version": health.engine_version,
        "overall_health": health.overall_health.value,
        "mode": metrics.mode,
        "execution_metrics": metrics.model_dump(),
        "data_freshness": health.data_freshness.model_dump(),
        "recent_alerts": health.recent_alerts,
    }


@monitoring_router.get(
    "/executions",
    response_model=ExecutionHealthMetrics,
    summary="Paper Execution Statistics",
)
def get_execution_metrics() -> ExecutionHealthMetrics:
    """
    Retrieve paper order counts (submitted, accepted, rejected, filled, cancelled),
    open positions, realized P&L, and paper equity balances.
    """
    return global_health_monitor.get_execution_metrics()


@monitoring_router.post(
    "/reset",
    status_code=status.HTTP_200_OK,
    summary="Reset Monitor Statistics (Test Isolation)",
)
def reset_monitoring() -> Dict[str, str]:
    """
    Reset all component counters, pipeline history, and execution metrics.
    Useful for clean test isolation.
    """
    global_health_monitor.reset()
    return {"status": "RESET_SUCCESS", "message": "System health monitor reset successfully."}
