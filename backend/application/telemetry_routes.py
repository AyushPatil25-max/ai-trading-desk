"""
Phase 8 — Telemetry & Execution Monitoring API Routes

FastAPI router exposing read-only execution observability endpoints and operator kill switch controls.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.domain.telemetry_schemas import (
    ExecutionEventType,
    KillSwitchState,
    ExecutionEvent,
    OrderTimeline,
    ExecutionMetrics,
    SystemHealthStatus,
    TelemetryDashboardSnapshot,
)
from backend.application.execution_telemetry_engine import global_telemetry_engine
from backend.application.paper_broker_adapter import PaperBrokerAdapter, global_paper_broker


router = APIRouter(prefix="/api/telemetry", tags=["Execution Telemetry"])


class KillSwitchRequest(BaseModel):
    action: str = "trigger"  # "trigger" or "disarm"
    reason: Optional[str] = "Operator API request"


@router.get("/dashboard", response_model=TelemetryDashboardSnapshot)
def get_dashboard():
    """Get the full operational dashboard snapshot."""
    orders = global_paper_broker.list_orders()
    acct = global_paper_broker.get_account()
    return global_telemetry_engine.get_dashboard_snapshot(account=acct, orders=orders)


@router.get("/events", response_model=List[ExecutionEvent])
def get_events(
    limit: int = Query(default=100, ge=1, le=1000),
    event_type: Optional[ExecutionEventType] = None,
    order_id: Optional[str] = None,
):
    """List execution audit events."""
    return global_telemetry_engine.list_events(limit=limit, event_type=event_type, order_id=order_id)


@router.get("/orders")
def get_orders(symbol: Optional[str] = None, status: Optional[str] = None):
    """List paper orders."""
    orders = global_paper_broker.list_orders(symbol=symbol)
    if status:
        orders = [o for o in orders if o.status.value == status]
    return [o.model_dump() for o in orders]


@router.get("/orders/{order_id}/timeline", response_model=OrderTimeline)
def get_order_timeline(order_id: str):
    """Get chronological lifecycle timeline and latencies for an order."""
    return global_telemetry_engine.get_order_timeline(order_id)


@router.get("/fills")
def get_fills():
    """List recent paper fills."""
    return [f.model_dump() for f in global_paper_broker.account.fills]


@router.get("/positions")
def get_positions():
    """List current open paper positions."""
    return [p.model_dump() for p in global_paper_broker.account.positions.values() if p.quantity > 0]


@router.get("/account")
def get_account():
    """Get current paper broker account state."""
    return global_paper_broker.account.model_dump()


@router.get("/metrics", response_model=ExecutionMetrics)
def get_metrics():
    """Get aggregated execution performance metrics."""
    orders = global_paper_broker.list_orders()
    return global_telemetry_engine.compute_metrics(orders)


@router.get("/health", response_model=SystemHealthStatus)
def get_health():
    """Get operational system health status."""
    return global_telemetry_engine.get_health_status()


@router.get("/kill-switch")
def get_kill_switch():
    """Get operator kill switch status."""
    return {
        "state": global_telemetry_engine._kill_switch_state.value,
        "is_triggered": global_telemetry_engine.is_kill_switch_triggered(),
        "reason": global_telemetry_engine._kill_switch_reason,
    }


@router.post("/kill-switch")
def set_kill_switch(req: KillSwitchRequest):
    """Trigger or disarm the operator emergency kill switch."""
    if req.action.lower() == "trigger":
        state = global_telemetry_engine.trigger_kill_switch(reason=req.reason or "Operator manual emergency stop")
        return {"status": "SUCCESS", "kill_switch_state": state.value, "message": "Kill switch engaged."}
    elif req.action.lower() == "disarm":
        state = global_telemetry_engine.disarm_kill_switch()
        return {"status": "SUCCESS", "kill_switch_state": state.value, "message": "Kill switch disarmed."}
    else:
        raise HTTPException(status_code=400, detail=f"Invalid action '{req.action}'. Use 'trigger' or 'disarm'.")
