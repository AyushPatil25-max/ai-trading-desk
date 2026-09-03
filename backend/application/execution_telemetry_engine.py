"""
Phase 8 — Execution Monitoring & Live Telemetry Engine

Pure Python deterministic observability engine that collects append-only execution events,
aggregates latency and slippage telemetry, tracks simulated paper positions, monitors system health,
and provides a fail-safe operator kill switch.
Zero LLM dependencies.
"""

from datetime import datetime, timezone
import math
import threading
from typing import Any, Dict, List, Optional
import uuid

from backend.domain.paper_broker_schemas import (
    PaperOrderStatus,
    PaperOrder,
    PaperFill,
    PaperAccount,
)
from backend.domain.telemetry_schemas import (
    TELEMETRY_ENGINE_VERSION,
    ExecutionEventType,
    EventSeverity,
    KillSwitchState,
    ExecutionEvent,
    OrderTimelineStep,
    OrderTimeline,
    ExecutionMetrics,
    SystemHealthStatus,
    TelemetryDashboardSnapshot,
)


class ExecutionTelemetryEngine:
    """
    Central operational telemetry and event store for the Trading OS.
    Maintains an immutable append-only event log and aggregated telemetry metrics.
    """

    SENSITIVE_KEYS = {"api_key", "secret", "password", "token", "auth_token", "access_token"}

    def __init__(self):
        self._lock = threading.Lock()
        self._events: List[ExecutionEvent] = []
        self._kill_switch_state: KillSwitchState = KillSwitchState.ARMED
        self._kill_switch_reason: Optional[str] = None
        self._error_count: int = 0

    # ── Operator Kill Switch ──────────────────────────────────────────────────

    def trigger_kill_switch(self, reason: str = "Operator manual emergency stop") -> KillSwitchState:
        """
        Engage the paper trading emergency kill switch.
        Immediately halts intake of new orders. Existing history is preserved.
        """
        with self._lock:
            self._kill_switch_state = KillSwitchState.TRIGGERED
            self._kill_switch_reason = reason
            self._error_count += 1

            # Emit audit event
            event = ExecutionEvent(
                event_type=ExecutionEventType.EXECUTION_ERROR,
                execution_id="SYSTEM-KILL-SWITCH",
                reason=f"KILL SWITCH TRIGGERED: {reason}",
                severity=EventSeverity.CRITICAL,
                metadata={"action": "TRIGGER_KILL_SWITCH", "reason": reason},
            )
            self._events.append(event)

            try:
                from backend.application.system_health_monitor import global_health_monitor
                global_health_monitor.set_kill_switch_state(KillSwitchState.TRIGGERED)
            except Exception:
                pass

            return self._kill_switch_state

    def disarm_kill_switch(self) -> KillSwitchState:
        """Disarm the operator kill switch to permit order submission."""
        with self._lock:
            self._kill_switch_state = KillSwitchState.ARMED
            self._kill_switch_reason = None

            event = ExecutionEvent(
                event_type=ExecutionEventType.ORDER_ACKNOWLEDGED,
                execution_id="SYSTEM-KILL-SWITCH",
                reason="Kill switch disarmed by operator.",
                severity=EventSeverity.INFO,
                metadata={"action": "DISARM_KILL_SWITCH"},
            )
            self._events.append(event)

            try:
                from backend.application.system_health_monitor import global_health_monitor
                global_health_monitor.set_kill_switch_state(KillSwitchState.ARMED)
            except Exception:
                pass

            return self._kill_switch_state

    def is_kill_switch_triggered(self) -> bool:
        """Check whether the emergency kill switch is currently active."""
        with self._lock:
            return self._kill_switch_state == KillSwitchState.TRIGGERED

    # ── Event Recording & Ingestion ───────────────────────────────────────────

    def record_event(
        self,
        event_type: ExecutionEventType,
        execution_id: str,
        order_id: Optional[str] = None,
        decision_id: Optional[str] = None,
        symbol: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        status: Optional[str] = None,
        quantity: Optional[int] = None,
        price: Optional[float] = None,
        latency_ms: Optional[float] = None,
        reason: Optional[str] = None,
        severity: EventSeverity = EventSeverity.INFO,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExecutionEvent:
        """
        Record an immutable execution event into the append-only telemetry stream.
        Sanitizes metadata to redact any sensitive keys.
        """
        now = timestamp or datetime.now(timezone.utc)
        sanitized_meta = self._sanitize_metadata(metadata or {})

        event = ExecutionEvent(
            event_type=event_type,
            execution_id=execution_id,
            order_id=order_id,
            decision_id=decision_id,
            symbol=symbol,
            timestamp=now,
            status=status,
            quantity=quantity,
            price=price,
            latency_ms=latency_ms,
            reason=reason,
            severity=severity,
            metadata=sanitized_meta,
        )

        with self._lock:
            self._events.append(event)
            if severity in (EventSeverity.ERROR, EventSeverity.CRITICAL):
                self._error_count += 1

        try:
            from backend.application.system_health_monitor import global_health_monitor
            global_health_monitor.record_execution_event(
                event_type=event_type,
                order_id=order_id,
                symbol=symbol,
                quantity=quantity,
                price=price,
                details=sanitized_meta,
            )
        except Exception:
            pass

        try:
            from backend.application.stream_manager import global_stream_manager
            global_stream_manager.ingest_telemetry_event(event)
        except Exception:
            pass

        return event

    def record_raw_event(self, event: ExecutionEvent) -> ExecutionEvent:
        """Append an already constructed ExecutionEvent."""
        with self._lock:
            self._events.append(event)
            if event.severity in (EventSeverity.ERROR, EventSeverity.CRITICAL):
                self._error_count += 1

        try:
            from backend.application.stream_manager import global_stream_manager
            global_stream_manager.ingest_telemetry_event(event)
        except Exception:
            pass

        return event

    # ── Timeline & Latency Telemetry ──────────────────────────────────────────

    def get_order_timeline(self, order_id: str) -> OrderTimeline:
        """
        Reconstruct the chronological lifecycle timeline for a specific order.
        Calculates internal simulated transition latencies between steps.
        """
        with self._lock:
            order_events = [e for e in self._events if e.order_id == order_id]

        order_events.sort(key=lambda e: e.timestamp)
        symbol = order_events[0].symbol if order_events and order_events[0].symbol else "UNKNOWN"

        steps: List[OrderTimelineStep] = []
        prev_ts: Optional[datetime] = None
        total_latency_ms = 0.0

        for evt in order_events:
            latency_step_ms = 0.0
            if prev_ts is not None:
                latency_step_ms = max(0.0, (evt.timestamp - prev_ts).total_seconds() * 1000.0)
                total_latency_ms += latency_step_ms

            steps.append(OrderTimelineStep(
                status=evt.status or evt.event_type.value,
                timestamp=evt.timestamp,
                latency_from_prev_ms=round(latency_step_ms, 2),
                details=evt.reason or f"Event {evt.event_type.value}",
            ))
            prev_ts = evt.timestamp

        return OrderTimeline(
            order_id=order_id,
            symbol=symbol,
            steps=steps,
            total_lifecycle_ms=round(total_latency_ms, 2),
        )

    # ── Metrics Aggregation ───────────────────────────────────────────────────

    def compute_metrics(self, broker_orders: Optional[List[PaperOrder]] = None) -> ExecutionMetrics:
        """
        Calculate deterministic execution performance metrics across all recorded paper orders.
        Safe against zero-sample division by zero.
        """
        orders = broker_orders or []
        total = len(orders)
        if total == 0:
            return ExecutionMetrics()

        filled = sum(1 for o in orders if o.status == PaperOrderStatus.FILLED)
        partially_filled = sum(1 for o in orders if o.status == PaperOrderStatus.PARTIALLY_FILLED)
        cancelled = sum(1 for o in orders if o.status == PaperOrderStatus.CANCELLED)
        rejected = sum(1 for o in orders if o.status == PaperOrderStatus.REJECTED)
        active = sum(1 for o in orders if o.status in (PaperOrderStatus.SUBMITTED, PaperOrderStatus.ACKNOWLEDGED, PaperOrderStatus.PARTIALLY_FILLED))

        fill_rate = round((filled / total) * 100.0, 2)
        rejection_rate = round((rejected / total) * 100.0, 2)
        cancellation_rate = round((cancelled / total) * 100.0, 2)
        partial_rate = round((partially_filled / total) * 100.0, 2)

        # Collect fills from orders
        all_fills: List[PaperFill] = []
        for o in orders:
            all_fills.extend(o.fills)

        total_slippage_cost = round(sum(f.slippage_amount for f in all_fills), 4)
        total_commissions = round(sum(f.commission for f in all_fills), 4)

        # Average slippage pct
        if all_fills:
            slip_pcts = [
                abs(f.slippage_amount / (f.price * f.quantity)) * 100.0
                for f in all_fills
                if f.price > 0 and f.quantity > 0
            ]
            avg_slip = round(sum(slip_pcts) / len(slip_pcts), 4) if slip_pcts else 0.0
        else:
            avg_slip = 0.0

        # Average lifecycle latency
        latencies = []
        for o in orders:
            if o.updated_at and o.created_at:
                dur_ms = max(0.0, (o.updated_at - o.created_at).total_seconds() * 1000.0)
                latencies.append(dur_ms)
        avg_lat = round(sum(latencies) / len(latencies), 2) if latencies else 0.0

        return ExecutionMetrics(
            total_orders=total,
            active_orders=active,
            filled_orders=filled,
            partially_filled_orders=partially_filled,
            cancelled_orders=cancelled,
            rejected_orders=rejected,
            fill_rate_pct=fill_rate,
            rejection_rate_pct=rejection_rate,
            cancellation_rate_pct=cancellation_rate,
            partial_fill_rate_pct=partial_rate,
            avg_execution_latency_ms=avg_lat,
            avg_slippage_pct=avg_slip,
            total_slippage_cost=total_slippage_cost,
            total_simulated_commissions=total_commissions,
        )

    # ── Health & Dashboard Snapshots ──────────────────────────────────────────

    def get_health_status(self) -> SystemHealthStatus:
        """
        Evaluate operational system health status and kill switch state.
        """
        with self._lock:
            last_ts = self._events[-1].timestamp if self._events else None
            is_triggered = self._kill_switch_state == KillSwitchState.TRIGGERED
            err_cnt = self._error_count

        is_healthy = (not is_triggered) and (err_cnt < 10)

        return SystemHealthStatus(
            api_status="HEALTHY",
            paper_broker_status="HEALTHY" if not is_triggered else "HALTED_BY_KILL_SWITCH",
            preflight_status="HEALTHY",
            portfolio_ledger_status="HEALTHY",
            telemetry_status="HEALTHY",
            kill_switch_state=self._kill_switch_state,
            data_freshness="FRESH",
            last_event_timestamp=last_ts,
            error_count=err_cnt,
            healthy=is_healthy,
        )

    def get_dashboard_snapshot(
        self,
        account: Optional[PaperAccount] = None,
        orders: Optional[List[PaperOrder]] = None,
    ) -> TelemetryDashboardSnapshot:
        """
        Assemble the unified operational dashboard snapshot combining telemetry, account, and health.
        """
        health = self.get_health_status()
        metrics = self.compute_metrics(orders or [])

        # Account summary
        acct_summary = {
            "cash": account.cash if account else 100000.0,
            "total_equity": account.total_equity if account else 100000.0,
            "buying_power": account.buying_power if account else 100000.0,
            "realized_pnl": account.realized_pnl if account else 0.0,
            "unrealized_pnl": account.unrealized_pnl if account else 0.0,
            "open_positions_count": len([p for p in (account.positions.values() if account else []) if p.quantity > 0]),
        }

        # Active orders list
        order_list = []
        for o in (orders or []):
            order_list.append({
                "order_id": o.order_id,
                "symbol": o.symbol,
                "side": o.side.value,
                "order_type": o.order_type.value,
                "requested_quantity": o.requested_quantity,
                "filled_quantity": o.filled_quantity,
                "remaining_quantity": o.remaining_quantity,
                "status": o.status.value,
                "average_fill_price": o.average_fill_price,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "updated_at": o.updated_at.isoformat() if o.updated_at else None,
            })

        # Fills list
        fills_list = []
        if account:
            for f in account.fills[-20:]:  # Last 20 fills
                fills_list.append({
                    "fill_id": f.fill_id,
                    "order_id": f.order_id,
                    "symbol": f.symbol,
                    "side": f.side.value,
                    "quantity": f.quantity,
                    "price": f.price,
                    "slippage_amount": f.slippage_amount,
                    "timestamp": f.timestamp.isoformat() if f.timestamp else None,
                })

        # Positions list
        positions_list = []
        if account:
            for p in account.positions.values():
                if p.quantity > 0:
                    positions_list.append({
                        "symbol": p.symbol,
                        "quantity": p.quantity,
                        "average_entry_price": p.average_entry_price,
                        "current_price": p.current_price,
                        "market_value": p.market_value,
                        "realized_pnl": p.realized_pnl,
                        "unrealized_pnl": p.unrealized_pnl,
                    })

        # Recent events
        with self._lock:
            recent_events = [
                {
                    "event_id": e.event_id,
                    "event_type": e.event_type.value,
                    "execution_id": e.execution_id,
                    "order_id": e.order_id,
                    "symbol": e.symbol,
                    "severity": e.severity.value,
                    "reason": e.reason,
                    "timestamp": e.timestamp.isoformat(),
                }
                for e in self._events[-30:]
            ]

            # Risk alerts
            risk_alerts = [
                {
                    "event_id": e.event_id,
                    "event_type": e.event_type.value,
                    "severity": e.severity.value,
                    "reason": e.reason,
                    "timestamp": e.timestamp.isoformat(),
                }
                for e in self._events
                if e.event_type in (ExecutionEventType.RISK_VETO, ExecutionEventType.PREFLIGHT_REJECTED, ExecutionEventType.EXECUTION_ERROR)
            ]

        return TelemetryDashboardSnapshot(
            system_health=health,
            account_summary=acct_summary,
            metrics=metrics,
            active_orders=order_list,
            recent_fills=fills_list,
            positions=positions_list,
            recent_events=recent_events,
            risk_alerts=risk_alerts[-10:],
        )

    # ── Event Querying & Reset ────────────────────────────────────────────────

    def list_events(
        self,
        limit: int = 100,
        event_type: Optional[ExecutionEventType] = None,
        order_id: Optional[str] = None,
    ) -> List[ExecutionEvent]:
        """Query recorded events with optional filtering."""
        with self._lock:
            res = list(self._events)
            if event_type:
                res = [e for e in res if e.event_type == event_type]
            if order_id:
                res = [e for e in res if e.order_id == order_id]
            return res[-limit:]

    def clear(self) -> None:
        """Reset the in-memory telemetry store for testing."""
        with self._lock:
            self._events.clear()
            self._kill_switch_state = KillSwitchState.ARMED
            self._kill_switch_reason = None
            self._error_count = 0

    # ── Private Helpers ───────────────────────────────────────────────────────

    def _sanitize_metadata(self, meta: Dict[str, Any]) -> Dict[str, Any]:
        """Redact sensitive keys from event metadata."""
        cleaned = {}
        for k, v in meta.items():
            if any(s in k.lower() for s in self.SENSITIVE_KEYS):
                cleaned[k] = "[REDACTED]"
            elif isinstance(v, dict):
                cleaned[k] = self._sanitize_metadata(v)
            else:
                cleaned[k] = v
        return cleaned


# Global shared singleton for the application
global_telemetry_engine = ExecutionTelemetryEngine()
