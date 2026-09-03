"""
Phase 13 — Real-Time Monitoring & System Health Engine

Deterministic, read-only observer for the entire Trading OS architecture.
Tracks health across all 16 subsystems, records 14-stage pipeline execution
metrics, monitors deterministic latency and data freshness, and mirrors paper
trading execution telemetry. Strictly downstream: never alters trading signals,
risk limits, position sizing, pre-flight gates, or broker execution.
"""

from collections import deque
from datetime import datetime, timezone
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.domain.monitoring_schemas import (
    MONITORING_VERSION,
    ComponentHealthRecord,
    ComponentHealthStatus,
    ComponentID,
    DataFreshnessStatus,
    ExecutionHealthMetrics,
    MonitoringConfig,
    PipelineRunMonitorReport,
    PipelineStageStatus,
    StageHealthRecord,
    SystemHealthLevel,
    SystemHealthSummary,
)
from backend.domain.schemas import MarketContext
from backend.domain.telemetry_schemas import ExecutionEventType, KillSwitchState
from backend.domain.trading_os_schemas import StageStatus, TradingOSRun

logger = logging.getLogger(__name__)


# ── Canonical Component Metadata ─────────────────────────────────────────────

_INITIAL_COMPONENTS = [
    {"id": ComponentID.MARKET_CONTEXT.value, "name": "Market Context Engine", "safety_critical": False},
    {"id": ComponentID.SPECIALISTS.value, "name": "Multi-Specialist Agents", "safety_critical": False},
    {"id": ComponentID.EVIDENCE_AGGREGATOR.value, "name": "Evidence Aggregator", "safety_critical": False},
    {"id": ComponentID.DEBATE_ENGINE.value, "name": "Adversarial Debate Engine", "safety_critical": False},
    {"id": ComponentID.INVESTMENT_COMMITTEE.value, "name": "Investment Committee", "safety_critical": False},
    {"id": ComponentID.CONVICTION_CALIBRATOR.value, "name": "Conviction & Calibration", "safety_critical": False},
    {"id": ComponentID.MARKET_REGIME_ENGINE.value, "name": "Market Regime Intelligence", "safety_critical": False},
    {"id": ComponentID.PORTFOLIO_INTELLIGENCE_ENGINE.value, "name": "Portfolio Intelligence", "safety_critical": False},
    {"id": ComponentID.SCENARIO_ENGINE.value, "name": "Scenario & Stress Engine", "safety_critical": False},
    {"id": ComponentID.RISK_ENGINE.value, "name": "Risk Management Engine", "safety_critical": True},
    {"id": ComponentID.POSITION_SIZING.value, "name": "Position Sizing Engine", "safety_critical": True},
    {"id": ComponentID.EXECUTION_PREFLIGHT_ENGINE.value, "name": "Pre-Flight Gatekeeper", "safety_critical": True},
    {"id": ComponentID.PAPER_BROKER_ADAPTER.value, "name": "Paper Broker Adapter", "safety_critical": True},
    {"id": ComponentID.FORWARD_SIMULATION_ENGINE.value, "name": "Forward Paper Trading Engine", "safety_critical": False},
    {"id": ComponentID.OPPORTUNITY_SCANNER.value, "name": "Opportunity Scanner", "safety_critical": False},
    {"id": ComponentID.EXECUTION_TELEMETRY_ENGINE.value, "name": "Execution Telemetry Engine", "safety_critical": False},
]

# Mapping of pipeline stage names to component IDs
_STAGE_TO_COMPONENT_MAP = {
    "MARKET_CONTEXT": ComponentID.MARKET_CONTEXT.value,
    "SPECIALISTS": ComponentID.SPECIALISTS.value,
    "EVIDENCE": ComponentID.EVIDENCE_AGGREGATOR.value,
    "DEBATE": ComponentID.DEBATE_ENGINE.value,
    "COMMITTEE": ComponentID.INVESTMENT_COMMITTEE.value,
    "CONVICTION": ComponentID.CONVICTION_CALIBRATOR.value,
    "REGIME": ComponentID.MARKET_REGIME_ENGINE.value,
    "PORTFOLIO": ComponentID.PORTFOLIO_INTELLIGENCE_ENGINE.value,
    "SCENARIO": ComponentID.SCENARIO_ENGINE.value,
    "RISK": ComponentID.RISK_ENGINE.value,
    "SIZING": ComponentID.POSITION_SIZING.value,
    "PREFLIGHT": ComponentID.EXECUTION_PREFLIGHT_ENGINE.value,
    "PAPER_BROKER": ComponentID.PAPER_BROKER_ADAPTER.value,
    "TELEMETRY": ComponentID.EXECUTION_TELEMETRY_ENGINE.value,
}


class SystemHealthMonitor:
    """
    Authoritative, thread-safe operational monitor for the AI Trading Desk.
    """

    def __init__(self, config: Optional[MonitoringConfig] = None) -> None:
        self.config = config or MonitoringConfig()
        self._lock = threading.RLock()
        self._start_time = datetime.now(timezone.utc)
        self._components: Dict[str, ComponentHealthRecord] = {}
        self._pipeline_history: deque = deque(maxlen=100)
        self._execution_metrics = ExecutionHealthMetrics()
        self._kill_switch_state = KillSwitchState.ARMED
        self._latest_freshness = DataFreshnessStatus()
        self._recent_alerts: deque = deque(maxlen=30)
        self._initialized = False

        self._initialize_components()

    # ── Initialization & Reset ────────────────────────────────────────────────

    def _initialize_components(self) -> None:
        """Initialize all 16 monitored subsystems with baseline healthy states."""
        with self._lock:
            self._components.clear()
            for meta in _INITIAL_COMPONENTS:
                rec = ComponentHealthRecord(
                    component_id=meta["id"],
                    name=meta["name"],
                    status=ComponentHealthStatus.HEALTHY,
                    is_safety_critical=meta["safety_critical"],
                )
                self._components[meta["id"]] = rec
            self._initialized = True

    def reset(self) -> None:
        """Reset monitoring counters, history, and metrics for clean test isolation."""
        with self._lock:
            self._start_time = datetime.now(timezone.utc)
            self._initialize_components()
            self._pipeline_history.clear()
            self._execution_metrics = ExecutionHealthMetrics()
            self._kill_switch_state = KillSwitchState.ARMED
            self._latest_freshness = DataFreshnessStatus()
            self._recent_alerts.clear()

    # ── Component Observation API ─────────────────────────────────────────────

    def record_component_execution(
        self,
        component_id: str,
        latency_ms: float = 0.0,
        details: Optional[Dict[str, Any]] = None,
    ) -> ComponentHealthRecord:
        """
        Record a successful component execution and update moving latency metrics.
        """
        with self._lock:
            rec = self._components.get(component_id)
            if not rec:
                rec = ComponentHealthRecord(
                    component_id=component_id,
                    name=component_id,
                    status=ComponentHealthStatus.HEALTHY,
                )
                self._components[component_id] = rec

            now = datetime.now(timezone.utc)
            rec.last_successful_at = now
            rec.execution_count += 1
            rec.consecutive_failures = 0
            rec.last_latency_ms = latency_ms
            rec.error_message = None

            # Moving average latency calculation
            if rec.execution_count == 1:
                rec.avg_latency_ms = latency_ms
            else:
                rec.avg_latency_ms = round(
                    ((rec.avg_latency_ms * (rec.execution_count - 1)) + latency_ms) / rec.execution_count,
                    2,
                )
            rec.max_latency_ms = max(rec.max_latency_ms, latency_ms)

            # Clear failure state if previously failed
            if rec.status == ComponentHealthStatus.FAILED:
                rec.status = ComponentHealthStatus.HEALTHY

            if details:
                rec.details.update(details)

            return rec

    def record_component_failure(
        self,
        component_id: str,
        error_message: str,
        latency_ms: float = 0.0,
        details: Optional[Dict[str, Any]] = None,
    ) -> ComponentHealthRecord:
        """
        Record a component failure, increment failure counters, and set FAILED status.
        """
        with self._lock:
            rec = self._components.get(component_id)
            if not rec:
                rec = ComponentHealthRecord(
                    component_id=component_id,
                    name=component_id,
                    status=ComponentHealthStatus.FAILED,
                )
                self._components[component_id] = rec

            now = datetime.now(timezone.utc)
            rec.last_failure_at = now
            rec.failure_count += 1
            rec.consecutive_failures += 1
            rec.last_latency_ms = latency_ms
            rec.status = ComponentHealthStatus.FAILED
            rec.error_message = error_message

            alert_msg = f"[{component_id}] FAILURE: {error_message}"
            self._recent_alerts.append(alert_msg)
            logger.warning(alert_msg)

            if details:
                rec.details.update(details)

            return rec

    def record_component_degraded(
        self,
        component_id: str,
        reason: str,
        latency_ms: float = 0.0,
        details: Optional[Dict[str, Any]] = None,
    ) -> ComponentHealthRecord:
        """
        Record a component running in degraded mode (e.g. fallback heuristic, missing metrics).
        """
        with self._lock:
            rec = self._components.get(component_id)
            if not rec:
                rec = ComponentHealthRecord(
                    component_id=component_id,
                    name=component_id,
                    status=ComponentHealthStatus.DEGRADED,
                )
                self._components[component_id] = rec

            now = datetime.now(timezone.utc)
            rec.last_successful_at = now
            rec.execution_count += 1
            rec.last_latency_ms = latency_ms
            rec.status = ComponentHealthStatus.DEGRADED
            rec.error_message = reason

            alert_msg = f"[{component_id}] DEGRADED: {reason}"
            self._recent_alerts.append(alert_msg)

            if details:
                rec.details.update(details)

            return rec

    def record_component_unavailable(
        self,
        component_id: str,
        reason: str = "Component offline or not configured",
    ) -> ComponentHealthRecord:
        """Mark a component as UNAVAILABLE."""
        with self._lock:
            rec = self._components.get(component_id)
            if not rec:
                rec = ComponentHealthRecord(
                    component_id=component_id,
                    name=component_id,
                    status=ComponentHealthStatus.UNAVAILABLE,
                )
                self._components[component_id] = rec

            rec.status = ComponentHealthStatus.UNAVAILABLE
            rec.error_message = reason
            return rec

    # ── Pipeline Observation API ──────────────────────────────────────────────

    def record_pipeline_run(
        self,
        run: TradingOSRun,
        market_context: Optional[MarketContext] = None,
    ) -> PipelineRunMonitorReport:
        """
        Observe and audit a completed or halted 14-stage Trading OS pipeline run.
        Classifies each stage, detects abnormal latency and early terminations.
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            run_id = getattr(run, "run_id", "unknown-run")
            symbol = getattr(run, "symbol", "UNKNOWN")
            total_duration = getattr(run, "total_duration_ms", 0.0)

            stages_dict: Dict[str, StageHealthRecord] = {}
            successful_stages: List[str] = []
            failed_stages: List[str] = []
            skipped_stages: List[str] = []
            degraded_stages: List[str] = []

            abnormal_latency = total_duration > self.config.abnormal_pipeline_latency_threshold_ms
            stale_data_flag = False

            # Inspect Data Freshness if context is provided
            if market_context:
                freshness = self.check_data_freshness(market_context_ts=getattr(market_context, "data_timestamp", None))
                if not freshness.is_fresh:
                    stale_data_flag = True

            # Analyze individual stages
            raw_stages = getattr(run, "stages", {}) or {}
            for stage_name, stage_res in raw_stages.items():
                dur = getattr(stage_res, "duration_ms", 0.0)
                raw_status = getattr(stage_res, "status", StageStatus.COMPLETED)
                err = getattr(stage_res, "error_message", None)
                details = getattr(stage_res, "details", {}) or {}

                if dur > self.config.abnormal_stage_latency_threshold_ms:
                    abnormal_latency = True

                # Map stage status to monitoring enum
                if raw_status in (StageStatus.COMPLETED,):
                    stage_stat = PipelineStageStatus.SUCCESS
                    successful_stages.append(stage_name)
                    # Update component record
                    comp_id = _STAGE_TO_COMPONENT_MAP.get(stage_name)
                    if comp_id:
                        self.record_component_execution(comp_id, latency_ms=dur)

                elif raw_status in (StageStatus.SKIPPED,):
                    stage_stat = PipelineStageStatus.SKIPPED
                    skipped_stages.append(stage_name)

                elif raw_status in (StageStatus.DEGRADED,):
                    stage_stat = PipelineStageStatus.DEGRADED
                    degraded_stages.append(stage_name)
                    comp_id = _STAGE_TO_COMPONENT_MAP.get(stage_name)
                    if comp_id:
                        self.record_component_degraded(comp_id, reason=err or "Degraded execution", latency_ms=dur)

                else:  # FAILED or REJECTED
                    stage_stat = PipelineStageStatus.FAILED
                    failed_stages.append(stage_name)
                    comp_id = _STAGE_TO_COMPONENT_MAP.get(stage_name)
                    if comp_id:
                        self.record_component_failure(comp_id, error_message=err or f"Stage {stage_name} failed", latency_ms=dur)

                stages_dict[stage_name] = StageHealthRecord(
                    stage_name=stage_name,
                    status=stage_stat,
                    duration_ms=dur,
                    started_at=getattr(stage_res, "started_at", now),
                    completed_at=getattr(stage_res, "completed_at", now),
                    error_message=err,
                    details=details,
                )

            # Determine Early Termination
            safety_halts = getattr(run, "safety_halts", []) or []
            risk_meta = getattr(run, "risk", {}) or {}
            risk_veto = risk_meta.get("veto_applied", False) if isinstance(risk_meta, dict) else False
            risk_reason = risk_meta.get("reason", "Risk veto applied") if isinstance(risk_meta, dict) else ""
            fail_reason = getattr(run, "failure_reason", None)

            terminated_early = len(skipped_stages) > 0 or len(failed_stages) > 0 or len(safety_halts) > 0 or risk_veto or bool(fail_reason)
            termination_reason = None
            if safety_halts:
                termination_reason = f"Safety Halt: {'; '.join(safety_halts)}"
            elif risk_veto:
                termination_reason = f"RISK_VETO: {risk_reason}"
            elif fail_reason:
                termination_reason = f"Pipeline Failure: {fail_reason}"
            elif skipped_stages:
                termination_reason = f"Pipeline terminated early at stage '{skipped_stages[0]}'"
            elif failed_stages:
                termination_reason = f"Stage failure in '{failed_stages[0]}'"

            report = PipelineRunMonitorReport(
                run_id=run_id,
                symbol=symbol,
                timestamp=now,
                total_latency_ms=total_duration,
                abnormal_latency_detected=abnormal_latency,
                stale_data_detected=stale_data_flag,
                pipeline_terminated_early=terminated_early,
                termination_reason=termination_reason,
                successful_stages=successful_stages,
                failed_stages=failed_stages,
                skipped_stages=skipped_stages,
                degraded_stages=degraded_stages,
                stages=stages_dict,
            )

            self._pipeline_history.append(report)
            return report

    # ── Data Freshness Verification ───────────────────────────────────────────

    def check_data_freshness(
        self,
        market_context_ts: Optional[datetime] = None,
        evidence_ts: Optional[datetime] = None,
        specialist_ts: Optional[datetime] = None,
        portfolio_ts: Optional[datetime] = None,
        telemetry_ts: Optional[datetime] = None,
    ) -> DataFreshnessStatus:
        """
        Evaluate deterministic age of incoming market, evidence, portfolio, and telemetry data.
        Never silently treats stale data as fresh.
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            stale_components: List[str] = []
            warnings: List[str] = []

            def _age(dt: Optional[datetime]) -> float:
                if dt is None:
                    return 0.0
                ts = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
                return max(0.0, (now - ts).total_seconds())

            # 1. Market Data
            m_age = _age(market_context_ts)
            if market_context_ts and m_age > self.config.market_data_max_age_seconds:
                stale_components.append(ComponentID.MARKET_CONTEXT.value)
                warnings.append(f"Market data is stale ({m_age:.1f}s > {self.config.market_data_max_age_seconds:.1f}s threshold).")
                self.record_component_degraded(ComponentID.MARKET_CONTEXT.value, reason="STALE_MARKET_DATA")

            # 2. Evidence Data
            e_age = _age(evidence_ts)
            if evidence_ts and e_age > self.config.evidence_max_age_seconds:
                stale_components.append(ComponentID.EVIDENCE_AGGREGATOR.value)
                warnings.append(f"Evidence data is stale ({e_age:.1f}s > {self.config.evidence_max_age_seconds:.1f}s threshold).")
                self.record_component_degraded(ComponentID.EVIDENCE_AGGREGATOR.value, reason="STALE_EVIDENCE_DATA")

            # 3. Specialist Data
            s_age = _age(specialist_ts)
            if specialist_ts and s_age > self.config.specialist_max_age_seconds:
                stale_components.append(ComponentID.SPECIALISTS.value)
                warnings.append(f"Specialist data is stale ({s_age:.1f}s > {self.config.specialist_max_age_seconds:.1f}s threshold).")
                self.record_component_degraded(ComponentID.SPECIALISTS.value, reason="STALE_SPECIALIST_DATA")

            # 4. Portfolio Data
            p_age = _age(portfolio_ts)
            if portfolio_ts and p_age > self.config.portfolio_max_age_seconds:
                stale_components.append(ComponentID.PORTFOLIO_INTELLIGENCE_ENGINE.value)
                warnings.append(f"Portfolio ledger state is stale ({p_age:.1f}s > {self.config.portfolio_max_age_seconds:.1f}s threshold).")
                self.record_component_degraded(ComponentID.PORTFOLIO_INTELLIGENCE_ENGINE.value, reason="STALE_PORTFOLIO_STATE")

            # 5. Telemetry Data
            t_age = _age(telemetry_ts)
            if telemetry_ts and t_age > self.config.telemetry_max_age_seconds:
                stale_components.append(ComponentID.EXECUTION_TELEMETRY_ENGINE.value)
                warnings.append(f"Telemetry events stream is stale ({t_age:.1f}s > {self.config.telemetry_max_age_seconds:.1f}s threshold).")
                self.record_component_degraded(ComponentID.EXECUTION_TELEMETRY_ENGINE.value, reason="STALE_TELEMETRY_EVENTS")

            status = DataFreshnessStatus(
                is_fresh=len(stale_components) == 0,
                market_data_age_seconds=m_age,
                evidence_age_seconds=e_age,
                specialist_age_seconds=s_age,
                portfolio_age_seconds=p_age,
                telemetry_age_seconds=t_age,
                stale_components=stale_components,
                warnings=warnings,
            )
            self._latest_freshness = status
            return status

    # ── Execution Telemetry Observation API ───────────────────────────────────

    def record_execution_event(
        self,
        event_type: ExecutionEventType,
        order_id: Optional[str] = None,
        symbol: Optional[str] = None,
        quantity: Optional[int] = None,
        price: Optional[float] = None,
        pnl: Optional[float] = None,
        cash_balance: Optional[float] = None,
        total_equity: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> ExecutionHealthMetrics:
        """
        Record paper execution lifecycle event and maintain aggregate paper statistics.
        Strictly paper-only.
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            metrics = self._execution_metrics
            metrics.last_execution_at = now

            if event_type == ExecutionEventType.ORDER_SUBMITTED:
                metrics.orders_submitted += 1

            elif event_type in (ExecutionEventType.ORDER_ACKNOWLEDGED, ExecutionEventType.ORDER_ACCEPTED):
                metrics.orders_accepted += 1

            elif event_type in (ExecutionEventType.ORDER_REJECTED, ExecutionEventType.PREFLIGHT_REJECTED, ExecutionEventType.RISK_VETO):
                metrics.orders_rejected += 1

            elif event_type in (ExecutionEventType.ORDER_FILLED, ExecutionEventType.FILL_CREATED):
                metrics.orders_filled += 1

            elif event_type in (ExecutionEventType.ORDER_CANCELLED, ExecutionEventType.ORDER_CANCEL_REQUESTED):
                metrics.orders_cancelled += 1

            elif event_type == ExecutionEventType.POSITION_OPENED:
                metrics.positions_opened += 1
                metrics.current_open_positions += 1

            elif event_type == ExecutionEventType.POSITION_CLOSED:
                metrics.positions_closed += 1
                metrics.current_open_positions = max(0, metrics.current_open_positions - 1)

            if pnl is not None:
                metrics.realized_pnl = round(metrics.realized_pnl + pnl, 2)

            if cash_balance is not None:
                metrics.cash_balance = round(cash_balance, 2)

            if total_equity is not None:
                metrics.total_equity = round(total_equity, 2)

            return metrics

    def set_kill_switch_state(self, state: KillSwitchState) -> None:
        """Update operator kill switch state."""
        with self._lock:
            self._kill_switch_state = state
            if state == KillSwitchState.TRIGGERED:
                self._recent_alerts.append("OPERATOR_KILL_SWITCH_TRIGGERED: All paper trading orders blocked.")

    # ── Master Health Aggregation API ─────────────────────────────────────────

    def get_system_health(self) -> SystemHealthSummary:
        """
        Compute deterministic overall system health based on explicit rules:
        1. OFFLINE: If monitoring uninitialized.
        2. CRITICAL: If operator kill switch is TRIGGERED.
        3. CRITICAL: If any SAFETY-CRITICAL component (Risk, Sizing, PreFlight, PaperBroker)
           is FAILED or DEGRADED or exceeds max consecutive failures.
        4. DEGRADED: If any non-critical component is FAILED/DEGRADED or data is stale.
        5. HEALTHY: All components healthy, all data fresh, kill switch armed.
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            uptime = (now - self._start_time).total_seconds()

            if not self._initialized:
                return SystemHealthSummary(
                    overall_health=SystemHealthLevel.OFFLINE,
                    status_badge="SYSTEM_OFFLINE",
                    uptime_seconds=0.0,
                )

            # Count statuses
            healthy_cnt = 0
            degraded_cnt = 0
            failed_cnt = 0
            unavail_cnt = 0
            safety_critical_healthy = True
            critical_failures: List[str] = []

            for comp in self._components.values():
                if comp.status == ComponentHealthStatus.HEALTHY:
                    healthy_cnt += 1
                elif comp.status == ComponentHealthStatus.DEGRADED:
                    degraded_cnt += 1
                    if comp.is_safety_critical:
                        safety_critical_healthy = False
                        critical_failures.append(f"Safety-critical component '{comp.name}' is DEGRADED: {comp.error_message}")
                elif comp.status == ComponentHealthStatus.FAILED:
                    failed_cnt += 1
                    if comp.is_safety_critical:
                        safety_critical_healthy = False
                        critical_failures.append(f"Safety-critical component '{comp.name}' has FAILED: {comp.error_message}")
                elif comp.status == ComponentHealthStatus.UNAVAILABLE:
                    unavail_cnt += 1
                    if comp.is_safety_critical:
                        safety_critical_healthy = False
                        critical_failures.append(f"Safety-critical component '{comp.name}' is UNAVAILABLE.")

                # Check consecutive failure threshold
                if comp.consecutive_failures >= self.config.max_consecutive_failures_allowed:
                    if comp.is_safety_critical:
                        safety_critical_healthy = False
                        critical_failures.append(
                            f"Safety-critical component '{comp.name}' exceeded failure threshold ({comp.consecutive_failures} failures)."
                        )

            # Evaluate Overall Health
            kill_switch_active = self._kill_switch_state == KillSwitchState.TRIGGERED

            if kill_switch_active or not safety_critical_healthy:
                overall = SystemHealthLevel.CRITICAL
                status_badge = "CRITICAL_SAFETY_ALERT"
            elif failed_cnt > 0 or degraded_cnt > 0 or not self._latest_freshness.is_fresh:
                overall = SystemHealthLevel.DEGRADED
                status_badge = "SYSTEM_DEGRADED_NON_CRITICAL"
            else:
                overall = SystemHealthLevel.HEALTHY
                status_badge = "ALL_SYSTEMS_OPERATIONAL"

            alerts = list(self._recent_alerts)
            if critical_failures:
                alerts.extend(critical_failures)

            return SystemHealthSummary(
                engine_version=MONITORING_VERSION,
                overall_health=overall,
                status_badge=status_badge,
                timestamp=now,
                uptime_seconds=round(uptime, 1),
                components_count=len(self._components),
                healthy_components_count=healthy_cnt,
                degraded_components_count=degraded_cnt,
                failed_components_count=failed_cnt,
                unavailable_components_count=unavail_cnt,
                safety_critical_healthy=safety_critical_healthy,
                data_freshness=self._latest_freshness,
                execution_metrics=self._execution_metrics,
                recent_alerts=alerts[-10:],
                active_kill_switch=kill_switch_active,
            )

    # ── Read-Only Query API ───────────────────────────────────────────────────

    def get_components_health(self) -> Dict[str, ComponentHealthRecord]:
        """Return operational health records for all 16 components."""
        with self._lock:
            return dict(self._components)

    def get_component_health(self, component_id: str) -> Optional[ComponentHealthRecord]:
        """Return operational health record for a specific component."""
        with self._lock:
            return self._components.get(component_id)

    def get_pipeline_history(self, limit: int = 50) -> List[PipelineRunMonitorReport]:
        """Return recent pipeline execution monitor reports."""
        with self._lock:
            history = list(self._pipeline_history)
            return history[-limit:]

    def get_latest_pipeline_report(self) -> Optional[PipelineRunMonitorReport]:
        """Return the most recent pipeline execution report."""
        with self._lock:
            return self._pipeline_history[-1] if self._pipeline_history else None

    def get_execution_metrics(self) -> ExecutionHealthMetrics:
        """Return simulated paper execution metrics."""
        with self._lock:
            return self._execution_metrics.model_copy()


# Global singleton instance for system-wide read-only monitoring
global_health_monitor = SystemHealthMonitor()
