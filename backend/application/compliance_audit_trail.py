"""
Phase 22 — Compliance Audit Trail

Persistent, bounded, append-only compliance audit log recording all alerting
lifecycle events, safety verifications, and compliance snapshots.

Safety Invariant:
- Audit entries are IMMUTABLE after creation — no modification or deletion.
- The audit trail is STRICTLY OBSERVATIONAL with ZERO execution authority.
- TIER_4_LIVE_REAL_MONEY remains permanently locked and fail-closed.
"""

from collections import deque
from datetime import datetime, timezone
import logging
import threading
from typing import Any, Dict, List, Optional
import uuid

from backend.domain.alert_audit_schemas import (
    AlertCategory,
    AlertSeverity,
    AuditAction,
    AuditEntry,
    ComplianceReport,
)

logger = logging.getLogger(__name__)

# Sensitive keys that must never appear in audit entries
SENSITIVE_KEYS = frozenset({
    "api_key", "secret", "password", "token", "credential", "auth",
    "GROQ_API_KEY", "ALPACA_SECRET", "broker_secret", "private_key",
})


def _sanitize_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Strip sensitive keys from metadata before recording."""
    sanitized = {}
    for k, v in metadata.items():
        key_lower = k.lower()
        if any(s in key_lower for s in SENSITIVE_KEYS):
            sanitized[k] = "***REDACTED***"
        elif isinstance(v, dict):
            sanitized[k] = _sanitize_metadata(v)
        else:
            sanitized[k] = v
    return sanitized


class ComplianceAuditTrail:
    """
    Bounded, chronologically ordered, append-only compliance audit trail.

    Records all alert lifecycle events, rule evaluation events, safety
    verifications, and compliance snapshots. Entries are immutable after
    creation and cannot be modified or deleted.

    SAFETY: This audit trail is STRICTLY OBSERVATIONAL with ZERO execution
    authority. It cannot place orders, modify risk parameters, or bypass
    any safety gate.
    """

    def __init__(self, max_entries: int = 10_000) -> None:
        self._lock = threading.RLock()
        self._entries: deque = deque(maxlen=max_entries)
        self._max_entries = max_entries

    def record(self, entry: AuditEntry) -> None:
        """
        Append an immutable audit entry to the trail.

        Sanitizes metadata to prevent credential leakage.
        Entries are never modified after recording.
        """
        if not isinstance(entry, AuditEntry):
            logger.error(
                f"[ComplianceAuditTrail] Rejected invalid entry type: {type(entry).__name__}"
            )
            return

        with self._lock:
            # Sanitize metadata
            if entry.metadata:
                sanitized = _sanitize_metadata(entry.metadata)
                entry = entry.model_copy(update={"metadata": sanitized})
            self._entries.append(entry)
            logger.debug(
                f"[ComplianceAuditTrail] Recorded: [{entry.action.value}] {entry.description}"
            )

    def entry_count(self) -> int:
        """Return the total number of entries in the trail."""
        with self._lock:
            return len(self._entries)

    def get_entries(
        self,
        category: Optional[AlertCategory] = None,
        severity: Optional[AlertSeverity] = None,
        action: Optional[AuditAction] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[AuditEntry]:
        """
        Query audit entries with optional filtering.

        Filters are applied conjunctively (AND logic).
        Results are returned in chronological order, limited to the
        most recent entries matching the criteria.
        """
        with self._lock:
            entries = list(self._entries)

        # Apply filters
        if category is not None:
            entries = [e for e in entries if e.category == category]
        if severity is not None:
            entries = [e for e in entries if e.severity == severity]
        if action is not None:
            entries = [e for e in entries if e.action == action]
        if since is not None:
            entries = [e for e in entries if e.timestamp >= since]
        if until is not None:
            entries = [e for e in entries if e.timestamp <= until]

        return entries[-limit:]

    def get_compliance_snapshots(self, limit: int = 50) -> List[AuditEntry]:
        """Return all compliance snapshot entries."""
        return self.get_entries(action=AuditAction.COMPLIANCE_SNAPSHOT, limit=limit)

    def get_safety_entries(self, limit: int = 100) -> List[AuditEntry]:
        """Return entries where safety_verified is True."""
        with self._lock:
            entries = [e for e in self._entries if e.safety_verified]
        return entries[-limit:]

    def generate_compliance_report(self) -> ComplianceReport:
        """
        Generate an aggregated compliance report from the audit trail.
        """
        with self._lock:
            entries = list(self._entries)

        # Count by action
        by_action: Dict[str, int] = {}
        for e in entries:
            by_action[e.action.value] = by_action.get(e.action.value, 0) + 1

        # Count by category
        by_category: Dict[str, int] = {}
        for e in entries:
            by_category[e.category.value] = by_category.get(e.category.value, 0) + 1

        # Safety metrics
        safety_passed = sum(
            1 for e in entries
            if e.action == AuditAction.SAFETY_CHECK_PASSED
        )
        safety_failed = sum(
            1 for e in entries
            if e.action == AuditAction.SAFETY_CHECK_FAILED
        )

        # Compliance snapshots
        snapshot_count = by_action.get(AuditAction.COMPLIANCE_SNAPSHOT.value, 0)

        # Alert lifecycle
        alerts_raised = by_action.get(AuditAction.ALERT_RAISED.value, 0)
        alerts_resolved = by_action.get(AuditAction.ALERT_RESOLVED.value, 0)
        alerts_escalated = by_action.get(AuditAction.ALERT_ESCALATED.value, 0)

        # Compliance rate
        total_safety = safety_passed + safety_failed
        compliance_rate = (safety_passed / total_safety) if total_safety > 0 else 1.0

        summary = (
            f"Compliance audit trail contains {len(entries)} entries. "
            f"Safety checks: {safety_passed} passed, {safety_failed} failed "
            f"({compliance_rate:.1%} compliance rate). "
            f"Alerts: {alerts_raised} raised, {alerts_resolved} resolved, "
            f"{alerts_escalated} escalated. "
            f"Compliance snapshots: {snapshot_count}."
        )

        return ComplianceReport(
            report_id=f"report-{uuid.uuid4().hex[:12]}",
            total_entries=len(entries),
            entries_by_action=by_action,
            entries_by_category=by_category,
            safety_checks_passed=safety_passed,
            safety_checks_failed=safety_failed,
            compliance_snapshots_count=snapshot_count,
            alerts_raised=alerts_raised,
            alerts_resolved=alerts_resolved,
            alerts_escalated=alerts_escalated,
            overall_compliance_rate=compliance_rate,
            summary_message=summary,
        )

    def reset(self) -> None:
        """Reset the audit trail for testing purposes."""
        with self._lock:
            self._entries.clear()


# Global singleton instance
global_audit_trail = ComplianceAuditTrail()
