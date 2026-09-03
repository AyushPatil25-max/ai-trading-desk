"""
Phase 22 — Alerting & Compliance REST API Routes

Provides operational API endpoints for the centralized alerting engine and
compliance audit trail. All endpoints are strictly observational and read-only
with the exception of alert lifecycle transitions (acknowledge/resolve) and
on-demand evaluation/snapshot triggers.

Safety Invariant:
- These routes have ZERO execution authority.
- No endpoint can place orders, modify risk parameters, or bypass safety gates.
- TIER_4_LIVE_REAL_MONEY remains permanently locked and fail-closed.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

from backend.domain.alert_audit_schemas import (
    AlertCategory,
    AlertSeverity,
)
from backend.application.alerting_engine import global_alerting_engine
from backend.application.compliance_audit_trail import global_audit_trail

logger = logging.getLogger(__name__)

alert_router = APIRouter(prefix="/api", tags=["Alerts & Compliance"])


# ── Active Alerts ─────────────────────────────────────────────────────────────

@alert_router.get("/alerts/active")
def get_active_alerts(
    severity: Optional[str] = Query(default=None, description="Filter by severity"),
    category: Optional[str] = Query(default=None, description="Filter by category"),
) -> Dict[str, Any]:
    """Return all currently active alerts with optional severity/category filters."""
    try:
        sev = AlertSeverity(severity) if severity else None
    except ValueError:
        sev = None
    try:
        cat = AlertCategory(category) if category else None
    except ValueError:
        cat = None

    alerts = global_alerting_engine.get_active_alerts(severity=sev, category=cat)
    return {
        "active_count": len(alerts),
        "alerts": [a.model_dump(mode="json") for a in alerts],
    }


# ── Alert History ─────────────────────────────────────────────────────────────

@alert_router.get("/alerts/history")
def get_alert_history(
    limit: int = Query(default=100, ge=1, le=1000, description="Max alerts to return"),
    severity: Optional[str] = Query(default=None, description="Filter by severity"),
    category: Optional[str] = Query(default=None, description="Filter by category"),
) -> Dict[str, Any]:
    """Return paginated alert history with optional filters."""
    try:
        sev = AlertSeverity(severity) if severity else None
    except ValueError:
        sev = None
    try:
        cat = AlertCategory(category) if category else None
    except ValueError:
        cat = None

    alerts = global_alerting_engine.get_alert_history(limit=limit, severity=sev, category=cat)
    return {
        "total_returned": len(alerts),
        "alerts": [a.model_dump(mode="json") for a in alerts],
    }


# ── Alert Status ──────────────────────────────────────────────────────────────

@alert_router.get("/alerts/status")
def get_alert_status() -> Dict[str, Any]:
    """Return alerting engine status summary."""
    status = global_alerting_engine.get_status()
    return status.model_dump(mode="json")


# ── Acknowledge Alert ─────────────────────────────────────────────────────────

@alert_router.post("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: str) -> Dict[str, Any]:
    """Acknowledge an active alert."""
    alert = global_alerting_engine.acknowledge_alert(alert_id)
    if alert is None:
        raise HTTPException(
            status_code=404,
            detail=f"Alert '{alert_id}' not found or not in ACTIVE state"
        )
    return {
        "status": "acknowledged",
        "alert": alert.model_dump(mode="json"),
    }


# ── Resolve Alert ─────────────────────────────────────────────────────────────

@alert_router.post("/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: str) -> Dict[str, Any]:
    """Resolve an active or acknowledged alert."""
    alert = global_alerting_engine.resolve_alert(alert_id)
    if alert is None:
        raise HTTPException(
            status_code=404,
            detail=f"Alert '{alert_id}' not found or not in ACTIVE/ACKNOWLEDGED state"
        )
    return {
        "status": "resolved",
        "alert": alert.model_dump(mode="json"),
    }


# ── Alert Rules ───────────────────────────────────────────────────────────────

@alert_router.get("/alerts/rules")
def get_alert_rules() -> Dict[str, Any]:
    """List all configured alert rules and their states."""
    rules = global_alerting_engine.get_rules()
    return {
        "total_rules": len(rules),
        "rules": [r.model_dump(mode="json") for r in rules],
    }


# ── Trigger Evaluation ───────────────────────────────────────────────────────

@alert_router.post("/alerts/evaluate")
def trigger_evaluation() -> Dict[str, Any]:
    """Trigger immediate rule evaluation cycle."""
    new_alerts = global_alerting_engine.evaluate_all_rules()
    return {
        "evaluated": True,
        "new_alerts_raised": len(new_alerts),
        "alerts": [a.model_dump(mode="json") for a in new_alerts],
    }


# ── Compliance Audit Trail ───────────────────────────────────────────────────

@alert_router.get("/compliance/audit")
def get_compliance_audit(
    category: Optional[str] = Query(default=None, description="Filter by category"),
    severity: Optional[str] = Query(default=None, description="Filter by severity"),
    action: Optional[str] = Query(default=None, description="Filter by action type"),
    limit: int = Query(default=100, ge=1, le=1000, description="Max entries to return"),
) -> Dict[str, Any]:
    """Query compliance audit trail with optional filters."""
    from backend.domain.alert_audit_schemas import AuditAction

    try:
        cat = AlertCategory(category) if category else None
    except ValueError:
        cat = None
    try:
        sev = AlertSeverity(severity) if severity else None
    except ValueError:
        sev = None
    try:
        act = AuditAction(action) if action else None
    except ValueError:
        act = None

    entries = global_audit_trail.get_entries(
        category=cat, severity=sev, action=act, limit=limit
    )
    return {
        "total_returned": len(entries),
        "entries": [e.model_dump(mode="json") for e in entries],
    }


# ── Compliance Snapshot ──────────────────────────────────────────────────────

@alert_router.get("/compliance/snapshot")
def get_compliance_snapshot() -> Dict[str, Any]:
    """Generate and return current compliance verification snapshot."""
    snapshot = global_alerting_engine.generate_compliance_snapshot()
    return snapshot.model_dump(mode="json")


# ── Compliance Report ────────────────────────────────────────────────────────

@alert_router.get("/compliance/report")
def get_compliance_report() -> Dict[str, Any]:
    """Generate compliance summary report from audit trail."""
    report = global_audit_trail.generate_compliance_report()
    return report.model_dump(mode="json")
