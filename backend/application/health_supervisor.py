"""
Phase 22 — Component Health Supervisor & Safe Degradation Policies

Supervises operational health across the 10 core subsystems of the Trading OS,
maintains heartbeat telemetry, tracks failure states, and strictly enforces
deterministic fail-closed safe-degradation policies.

Safety Invariant:
- STRICTLY OBSERVATIONAL: Zero authority to place real-money orders.
- Safe degradation NEVER fabricates market prices, model predictions, or broker fills.
- TIER_4_LIVE_REAL_MONEY remains permanently locked and fail-closed.
"""

from datetime import datetime, timezone
import logging
import threading
from typing import Any, Dict, List, Optional

from backend.domain.resilience_schemas import (
    CircuitState,
    ComponentHealthRecord,
    ComponentSupervisorState,
    FailureDomainType,
    FailureSeverity,
    ResilienceComponent,
)
from backend.application.resilience_engine import global_resilience_engine

logger = logging.getLogger(__name__)


# ── Canonical Supervised Subsystems ───────────────────────────────────────────

DEFAULT_SUPERVISED_COMPONENTS = [
    (ResilienceComponent.MARKET_DATA, "Market Data Ingestion", True),
    (ResilienceComponent.STREAMING_LAYER, "Real-Time Streaming Engine", False),
    (ResilienceComponent.PAPER_WORKERS, "Distributed Paper Simulation Workers", False),
    (ResilienceComponent.MODEL_SERVICES, "Multi-Specialist Model / Inference Services", False),
    (ResilienceComponent.CONTEXT_CACHE, "Market Context & In-Memory Cache", False),
    (ResilienceComponent.SNAPSHOT_SUBSYSTEM, "Market Context Snapshot Engine", True),
    (ResilienceComponent.TELEMETRY_PIPELINE, "Execution Telemetry & Event Ingestion", False),
    (ResilienceComponent.BROKER_SANDBOX, "External Broker Sandbox Adapter", True),
    (ResilienceComponent.API_SUBSYSTEM, "FastAPI Application & REST Routing", False),
    (ResilienceComponent.ALERTING_ENGINE, "Centralized Alerting Engine & Audit Trail", False),
]


class ComponentHealthSupervisor:
    """
    Supervises operational health across all 10 subsystems of the Trading OS.
    Enforces deterministic fail-closed safe degradation policies when faults are detected.
    """

    def __init__(self, resilience_engine: Optional[Any] = None):
        self._lock = threading.RLock()
        self.resilience_engine = resilience_engine or global_resilience_engine
        self._components: Dict[ResilienceComponent, ComponentHealthRecord] = {}

        # Initialize supervisor records
        for comp, name, is_critical in DEFAULT_SUPERVISED_COMPONENTS:
            self._components[comp] = ComponentHealthRecord(
                component=comp,
                name=name,
                state=ComponentSupervisorState.HEALTHY,
                is_safety_critical=is_critical,
                last_heartbeat=datetime.now(timezone.utc),
                last_success_at=datetime.now(timezone.utc),
            )

    # ── Heartbeat & Telemetry Tracking (Step 4) ───────────────────────────────

    def record_heartbeat(self, component: ResilienceComponent) -> None:
        """Record an operational heartbeat confirming subsystem liveliness."""
        with self._lock:
            rec = self._components.get(component)
            if rec:
                rec.last_heartbeat = datetime.now(timezone.utc)

    def record_operation_success(self, component: ResilienceComponent, latency_ms: float = 0.0) -> None:
        """Record successful operational cycle for a subsystem."""
        with self._lock:
            rec = self._components.get(component)
            if rec:
                rec.last_success_at = datetime.now(timezone.utc)
                rec.last_heartbeat = datetime.now(timezone.utc)
                rec.consecutive_failures = 0
                rec.latency_ms = (rec.latency_ms * 0.8) + (latency_ms * 0.2)  # Exponential moving average
                if rec.state != ComponentSupervisorState.HEALTHY:
                    rec.state = ComponentSupervisorState.HEALTHY
                    rec.active_fallback = None
                    logger.info(f"[ComponentHealthSupervisor] Subsystem {component.value} restored to HEALTHY.")

    def record_operation_failure(
        self,
        component: ResilienceComponent,
        failure_type: FailureDomainType,
        error_message: str,
        is_timeout: bool = False,
        audit_metadata: Optional[Dict[str, Any]] = None,
    ) -> ComponentSupervisorState:
        """
        Record subsystem failure, update tracking counters, and apply safe degradation.
        Returns the new operational state of the component.
        """
        with self._lock:
            rec = self._components.get(component)
            if not rec:
                return ComponentSupervisorState.FAILED_SAFE

            now = datetime.now(timezone.utc)
            rec.last_failure_at = now
            rec.last_heartbeat = now
            rec.consecutive_failures += 1
            if is_timeout:
                rec.timeout_count += 1

            # Determine failure severity
            sev = FailureSeverity.CRITICAL if rec.is_safety_critical else FailureSeverity.HIGH

            # Determine and apply safe degradation policy
            new_state, fallback_desc, halt_trading = self._evaluate_safe_degradation_policy(
                component=component,
                failure_type=failure_type,
                consecutive_failures=rec.consecutive_failures,
            )

            rec.state = new_state
            rec.active_fallback = fallback_desc

            # Register failure in resilience engine
            self.resilience_engine.record_failure_event(
                component=component,
                failure_type=failure_type,
                description=error_message,
                severity=sev,
                safe_fallback=fallback_desc,
                trading_halted=halt_trading,
                audit_metadata=audit_metadata or {},
            )

            logger.warning(
                f"[ComponentHealthSupervisor] {component.value} transitioned to {new_state.value}. "
                f"Active fallback: {fallback_desc}"
            )
            return new_state

    # ── Safe Degradation Policies (Step 5) ────────────────────────────────────

    def _evaluate_safe_degradation_policy(
        self,
        component: ResilienceComponent,
        failure_type: FailureDomainType,
        consecutive_failures: int,
    ) -> Tuple[ComponentSupervisorState, str, bool]:
        """
        Evaluates deterministic safe degradation policies.
        Returns: (NewState, SafeFallbackDescription, HaltTradingBoolean)
        """
        if component == ResilienceComponent.MARKET_DATA:
            # Policy 1: Market data failure / stale -> reject decisions, preserve state, zero price fabrication
            if failure_type == FailureDomainType.MARKET_DATA_STALE:
                return (
                    ComponentSupervisorState.DEGRADED,
                    "REJECT_DECISIONS_STALE_DATA: Market data stale (>300s). No new paper orders allowed. Zero price invention.",
                    True,
                )
            return (
                ComponentSupervisorState.UNAVAILABLE,
                "FAIL_CLOSED_NO_MARKET_DATA: Market data feed unavailable. New decisions rejected. Preserving paper positions.",
                True,
            )

        elif component == ResilienceComponent.MODEL_SERVICES:
            # Policy 2: Model failure -> trip circuit breaker, route to deterministic fallback, zero hallucinated predictions
            return (
                ComponentSupervisorState.DEGRADED,
                "DETERMINISTIC_MODEL_FALLBACK: ML models unavailable. Routed to deterministic heuristic rules. Zero hallucinated signals.",
                False,
            )

        elif component == ResilienceComponent.PAPER_WORKERS:
            # Policy 3: Worker failure -> isolate failed worker, prevent failure propagation to other symbols
            return (
                ComponentSupervisorState.DEGRADED,
                "ISOLATE_FAILED_SYMBOL_WORKER: Failed symbol worker isolated. Other symbols continue executing.",
                False,
            )

        elif component == ResilienceComponent.CONTEXT_CACHE:
            # Policy 4: Cache failure -> invalidate unsafe cache state, bypass cache and fetch authoritative context
            return (
                ComponentSupervisorState.DEGRADED,
                "BYPASS_CACHE_AUTHORITATIVE_FETCH: Cache state invalidated. Forcing fresh context fetch or failing closed.",
                False,
            )

        elif component == ResilienceComponent.BROKER_SANDBOX:
            # Policy 5: Broker sandbox failure -> halt affected simulated execution, require reconciliation, zero assumed fills
            return (
                ComponentSupervisorState.UNAVAILABLE,
                "HALT_SANDBOX_EXECUTION_REQUIRE_RECONCILIATION: Sandbox unreachable. Order submission halted. Reconciliation flag set.",
                True,
            )

        elif component == ResilienceComponent.TELEMETRY_PIPELINE:
            # Policy 6: Telemetry failure -> core trading safety must NOT depend on telemetry. Buffer/drop gracefully.
            return (
                ComponentSupervisorState.DEGRADED,
                "BUFFER_AND_DROP_TELEMETRY: Telemetry backpressured/dropping. Core execution safety rules unaffected.",
                False,
            )

        elif component == ResilienceComponent.STREAMING_LAYER:
            return (
                ComponentSupervisorState.DEGRADED,
                "STREAM_BACKPRESSURE_DROP_OLDEST: Streaming queue saturated. Backpressure dropping oldest unconsumed events.",
                False,
            )

        # Default generic safe degradation
        state = (
            ComponentSupervisorState.FAILED_SAFE
            if consecutive_failures >= 3
            else ComponentSupervisorState.DEGRADED
        )
        return (state, "FAIL_SAFE_DEFAULT_ISOLATION: Component isolated under safe fallback policy.", False)

    # ── State Queries ─────────────────────────────────────────────────────────

    def get_component_record(self, component: ResilienceComponent) -> Optional[ComponentHealthRecord]:
        with self._lock:
            rec = self._components.get(component)
            return rec.model_copy() if rec else None

    def get_all_component_records(self) -> Dict[str, ComponentHealthRecord]:
        with self._lock:
            return {comp.value: rec.model_copy() for comp, rec in self._components.items()}

    def get_overall_resilience_state(self) -> ComponentSupervisorState:
        """Derive highest-severity state across all monitored subsystems."""
        with self._lock:
            states = [rec.state for rec in self._components.values()]
            if ComponentSupervisorState.FAILED_SAFE in states:
                return ComponentSupervisorState.FAILED_SAFE
            if ComponentSupervisorState.UNAVAILABLE in states:
                return ComponentSupervisorState.UNAVAILABLE
            if ComponentSupervisorState.RECOVERING in states:
                return ComponentSupervisorState.RECOVERING
            if ComponentSupervisorState.DEGRADED in states:
                return ComponentSupervisorState.DEGRADED
            return ComponentSupervisorState.HEALTHY

    def reset(self) -> None:
        """Reset supervisor state for clean testing."""
        with self._lock:
            for comp, rec in self._components.items():
                rec.state = ComponentSupervisorState.HEALTHY
                rec.consecutive_failures = 0
                rec.timeout_count = 0
                rec.recovery_attempts = 0
                rec.circuit_state = CircuitState.CLOSED
                rec.active_fallback = None


# Global singleton instance
global_health_supervisor = ComponentHealthSupervisor()
