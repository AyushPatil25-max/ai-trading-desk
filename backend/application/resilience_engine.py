"""
Phase 22 — Centralized Resilience & Recovery Engine

Provides unified fault handling, bounded retries with exponential backoff and jitter,
timeout enforcement, generalized service circuit breaking (CLOSED, OPEN, HALF_OPEN),
correlation ID propagation, and telemetry emission.

Safety Invariant:
- STRICTLY OBSERVATIONAL and defensive recovery only.
- ZERO authority to submit real-money orders.
- Recovery logic NEVER bypasses ExecutionGuard, RiskEngine, or PreFlight.
"""

import asyncio
from collections import deque
import concurrent.futures
from datetime import datetime, timezone
import logging
import math
import random
import threading
import time
from typing import Any, Callable, Coroutine, Deque, Dict, List, Optional, Tuple, Type, TypeVar, Union
import uuid

from backend.domain.resilience_schemas import (
    CircuitState,
    ComponentSupervisorState,
    FailureDomainType,
    FailureEvent,
    FailureSeverity,
    RecoveryAction,
    RecoveryState,
    ResilienceComponent,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

SENSITIVE_KEYS = frozenset({
    "api_key", "secret", "password", "token", "auth", "credential",
    "access_token", "auth_token", "private_key", "groq_api_key", "alpaca_secret",
})


def _sanitize_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively scrub any sensitive keys from error/failure metadata."""
    sanitized: Dict[str, Any] = {}
    for k, v in metadata.items():
        key_lower = str(k).lower()
        if any(s in key_lower for s in SENSITIVE_KEYS):
            sanitized[k] = "***REDACTED***"
        elif isinstance(v, dict):
            sanitized[k] = _sanitize_metadata(v)
        else:
            sanitized[k] = v
    return sanitized


# ── Generalized Service Circuit Breaker (Step 3) ──────────────────────────────

class ServiceCircuitBreaker:
    """
    Thread-safe operational circuit breaker for protecting internal subsystems,
    remote services, models, and broker sandbox APIs.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 5.0,
        half_open_success_threshold: int = 1,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.half_open_success_threshold = half_open_success_threshold

        self._lock = threading.RLock()
        self._state: CircuitState = CircuitState.CLOSED
        self._opened_at: Optional[float] = None
        self._consecutive_failures: int = 0
        self._consecutive_successes: int = 0
        self._half_open_successes: int = 0
        self._probe_in_flight: bool = False
        self._total_trips: int = 0

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN and self._opened_at:
                elapsed = time.monotonic() - self._opened_at
                if elapsed >= self.recovery_timeout_seconds:
                    self._state = CircuitState.HALF_OPEN
                    self._probe_in_flight = False
                    self._half_open_successes = 0
            return self._state

    def allow_request(self) -> bool:
        """Evaluate if an operation is permitted under current circuit state."""
        with self._lock:
            current_state = self.state
            if current_state == CircuitState.CLOSED:
                return True
            elif current_state == CircuitState.HALF_OPEN:
                if not self._probe_in_flight:
                    self._probe_in_flight = True
                    return True
                return False
            else:  # OPEN
                return False

    def record_success(self) -> None:
        """Record successful execution and handle re-closing transitions."""
        with self._lock:
            self._consecutive_failures = 0
            self._consecutive_successes += 1
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_successes += 1
                self._probe_in_flight = False
                if self._half_open_successes >= self.half_open_success_threshold:
                    self._state = CircuitState.CLOSED
                    self._opened_at = None
                    logger.info(f"[ServiceCircuitBreaker:{self.name}] RECLOSED to CLOSED state.")

    def record_failure(self) -> bool:
        """
        Record failure and trip circuit to OPEN if threshold reached.
        Returns True if circuit was newly tripped to OPEN.
        """
        with self._lock:
            self._consecutive_failures += 1
            self._consecutive_successes = 0
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
                self._probe_in_flight = False
                self._total_trips += 1
                logger.warning(f"[ServiceCircuitBreaker:{self.name}] Probe failed! Tripped back to OPEN.")
                return True
            elif self._state == CircuitState.CLOSED:
                if self._consecutive_failures >= self.failure_threshold:
                    self._state = CircuitState.OPEN
                    self._opened_at = time.monotonic()
                    self._total_trips += 1
                    logger.warning(
                        f"[ServiceCircuitBreaker:{self.name}] Failure threshold ({self.failure_threshold}) reached! "
                        f"Tripped to OPEN."
                    )
                    return True
            return False

    def reset(self) -> None:
        """Manually reset the circuit breaker to CLOSED."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._opened_at = None
            self._consecutive_failures = 0
            self._consecutive_successes = 0
            self._half_open_successes = 0
            self._probe_in_flight = False

    @property
    def total_trips(self) -> int:
        with self._lock:
            return self._total_trips


# ── Resilience Engine (Step 3) ────────────────────────────────────────────────

class ResilienceEngine:
    """
    Centralized fault management, bounded retry execution, and timeout supervisor.
    Observational only: zero order submission authority.
    """

    def __init__(
        self,
        max_events_history: int = 1000,
        sleep_fn: Optional[Callable[[float], None]] = None,
    ):
        self._lock = threading.RLock()
        self._sleep_fn = sleep_fn or time.sleep
        self._circuit_breakers: Dict[str, ServiceCircuitBreaker] = {}
        self._failure_events: Deque[FailureEvent] = deque(maxlen=max_events_history)
        self._active_failures: Dict[str, FailureEvent] = {}  # failure_id -> FailureEvent
        self._recovery_actions: Deque[RecoveryAction] = deque(maxlen=max_events_history)

        # Telemetry engine reference (lazy loaded)
        self._telemetry_engine: Optional[Any] = None

    @property
    def telemetry_engine(self) -> Any:
        if self._telemetry_engine is None:
            try:
                from backend.application.execution_telemetry_engine import global_telemetry_engine
                self._telemetry_engine = global_telemetry_engine
            except ImportError:
                pass
        return self._telemetry_engine

    # ── Circuit Breakers ──────────────────────────────────────────────────────

    def get_or_create_circuit_breaker(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 5.0,
    ) -> ServiceCircuitBreaker:
        with self._lock:
            if name not in self._circuit_breakers:
                self._circuit_breakers[name] = ServiceCircuitBreaker(
                    name=name,
                    failure_threshold=failure_threshold,
                    recovery_timeout_seconds=recovery_timeout_seconds,
                )
            return self._circuit_breakers[name]

    def get_circuit_state(self, name: str) -> CircuitState:
        with self._lock:
            cb = self._circuit_breakers.get(name)
            return cb.state if cb else CircuitState.CLOSED

    def reset_all_circuits(self) -> None:
        with self._lock:
            for cb in self._circuit_breakers.values():
                cb.reset()

    # ── Timeout Enforcement ───────────────────────────────────────────────────

    def execute_with_timeout_sync(
        self,
        func: Callable[..., T],
        timeout_seconds: float,
        fallback_value: Optional[T] = None,
        *args: Any,
        **kwargs: Any,
    ) -> Tuple[T, bool]:
        """
        Execute a synchronous callable with strict timeout enforcement using a thread pool.
        Returns: (result, timed_out_boolean)
        """
        if timeout_seconds <= 0:
            return func(*args, **kwargs), False

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func, *args, **kwargs)
            try:
                result = future.result(timeout=timeout_seconds)
                return result, False
            except concurrent.futures.TimeoutError:
                logger.warning(f"[ResilienceEngine] Execution timed out after {timeout_seconds}s")
                return fallback_value, True  # type: ignore[return-value]

    async def execute_with_timeout_async(
        self,
        coro_fn: Callable[..., Coroutine[Any, Any, T]],
        timeout_seconds: float,
        fallback_value: Optional[T] = None,
        *args: Any,
        **kwargs: Any,
    ) -> Tuple[T, bool]:
        """
        Execute an asynchronous coroutine with strict timeout enforcement.
        Returns: (result, timed_out_boolean)
        """
        if timeout_seconds <= 0:
            res = await coro_fn(*args, **kwargs)
            return res, False

        try:
            res = await asyncio.wait_for(coro_fn(*args, **kwargs), timeout=timeout_seconds)
            return res, False
        except asyncio.TimeoutError:
            logger.warning(f"[ResilienceEngine] Async execution timed out after {timeout_seconds}s")
            return fallback_value, True  # type: ignore[return-value]

    # ── Bounded Exponential Backoff with Jitter (Step 3) ───────────────────────

    def calculate_backoff(
        self,
        attempt: int,
        base_delay_seconds: float = 0.5,
        max_delay_seconds: float = 30.0,
        jitter_factor: float = 0.1,
    ) -> float:
        """
        Calculate bounded exponential backoff delay with controlled jitter:
        delay = min(max_delay, base_delay * (2 ^ (attempt - 1))) + jitter
        """
        if attempt <= 1:
            raw_delay = base_delay_seconds
        else:
            raw_delay = min(max_delay_seconds, base_delay_seconds * (2 ** (attempt - 1)))

        jitter = random.uniform(0, jitter_factor * raw_delay) if jitter_factor > 0 else 0.0
        return min(max_delay_seconds, raw_delay + jitter)

    def execute_with_retry_sync(
        self,
        func: Callable[..., T],
        max_attempts: int = 3,
        base_delay_seconds: float = 0.1,
        max_delay_seconds: float = 5.0,
        circuit_name: Optional[str] = None,
        component: ResilienceComponent = ResilienceComponent.API_SUBSYSTEM,
        failure_type: FailureDomainType = FailureDomainType.UNKNOWN_FAILURE,
        safe_fallback: Optional[T] = None,
        *args: Any,
        **kwargs: Any,
    ) -> Tuple[T, int, bool]:
        """
        Execute a function with bounded retries, exponential backoff, and circuit breaker.
        Returns: (result, attempts_used, succeeded)
        """
        if max_attempts < 1:
            max_attempts = 1

        cb = self.get_or_create_circuit_breaker(circuit_name) if circuit_name else None
        if cb and not cb.allow_request():
            logger.warning(f"[ResilienceEngine] Request blocked by circuit breaker '{circuit_name}'")
            return safe_fallback, 0, False  # type: ignore[return-value]

        last_exception: Optional[Exception] = None
        for attempt in range(1, max_attempts + 1):
            try:
                res = func(*args, **kwargs)
                if cb:
                    cb.record_success()
                return res, attempt, True
            except Exception as ex:
                last_exception = ex
                if cb:
                    cb.record_failure()

                if attempt < max_attempts:
                    delay = self.calculate_backoff(attempt, base_delay_seconds, max_delay_seconds)
                    self._sleep_fn(delay)

        # Retries exhausted: record failure event
        self.record_failure_event(
            component=component,
            failure_type=failure_type,
            description=f"Retries exhausted ({max_attempts} attempts): {last_exception}",
            severity=FailureSeverity.HIGH,
            retry_count=max_attempts,
            safe_fallback=str(safe_fallback),
        )
        return safe_fallback, max_attempts, False  # type: ignore[return-value]

    # ── Failure Event Registration & Tracking (Step 2) ─────────────────────────

    def record_failure_event(
        self,
        component: ResilienceComponent,
        failure_type: FailureDomainType,
        description: str,
        severity: FailureSeverity = FailureSeverity.MEDIUM,
        safe_fallback: str = "NONE",
        trading_halted: bool = False,
        audit_metadata: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
        retry_count: int = 0,
    ) -> FailureEvent:
        """Record and track a strongly typed failure event."""
        with self._lock:
            safe_meta = _sanitize_metadata(audit_metadata or {})
            event = FailureEvent(
                failure_id=f"fail-{uuid.uuid4().hex[:10]}",
                correlation_id=correlation_id or f"corr-{uuid.uuid4().hex[:12]}",
                component=component,
                timestamp=datetime.now(timezone.utc),
                severity=severity,
                failure_type=failure_type,
                description=description,
                recovery_state=RecoveryState.DETECTED,
                retry_count=retry_count,
                safe_fallback=safe_fallback,
                trading_halted=trading_halted,
                audit_metadata=safe_meta,
            )
            self._failure_events.append(event)
            self._active_failures[event.failure_id] = event

            # Emit to telemetry if available
            self._emit_telemetry_event(event)

            logger.warning(
                f"[ResilienceEngine] FAILURE DETECTED: [{component.value}:{failure_type.value}] "
                f"corr_id={event.correlation_id} — {description}"
            )
            return event

    def update_failure_recovery_state(
        self,
        failure_id: str,
        state: RecoveryState,
        retry_increment: int = 0,
    ) -> Optional[FailureEvent]:
        with self._lock:
            event = self._active_failures.get(failure_id)
            if not event:
                return None
            event.recovery_state = state
            event.retry_count += retry_increment
            if state in (RecoveryState.RECOVERED, RecoveryState.FAILED_SAFE, RecoveryState.UNRECOVERABLE):
                self._active_failures.pop(failure_id, None)
            return event

    def record_recovery_action(
        self,
        correlation_id: str,
        component: ResilienceComponent,
        failure_type: FailureDomainType,
        action_taken: str,
        success: bool,
        result_message: str,
        duration_ms: float = 0.0,
        audit_metadata: Optional[Dict[str, Any]] = None,
    ) -> RecoveryAction:
        """Record the outcome of an automated or supervised recovery action."""
        with self._lock:
            action = RecoveryAction(
                action_id=f"rec-{uuid.uuid4().hex[:10]}",
                correlation_id=correlation_id,
                component=component,
                failure_type=failure_type,
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                duration_ms=duration_ms,
                success=success,
                action_taken=action_taken,
                result_message=result_message,
                audit_metadata=_sanitize_metadata(audit_metadata or {}),
            )
            self._recovery_actions.append(action)
            return action

    def get_active_failures(self) -> List[FailureEvent]:
        with self._lock:
            return list(self._active_failures.values())

    def get_failure_history(self, limit: int = 100) -> List[FailureEvent]:
        with self._lock:
            return list(self._failure_events)[-limit:]

    def get_recovery_history(self, limit: int = 100) -> List[RecoveryAction]:
        with self._lock:
            return list(self._recovery_actions)[-limit:]

    def _emit_telemetry_event(self, event: FailureEvent) -> None:
        """Safely forward failure notification to the telemetry engine."""
        if self.telemetry_engine and hasattr(self.telemetry_engine, "record_event"):
            try:
                from backend.domain.telemetry_schemas import EventSeverity, ExecutionEventType
                sev = (
                    EventSeverity.CRITICAL
                    if event.severity == FailureSeverity.CRITICAL
                    else EventSeverity.WARNING
                )
                self.telemetry_engine.record_event(
                    event_type=ExecutionEventType.EXECUTION_ERROR,
                    execution_id=event.correlation_id,
                    reason=f"[{event.failure_type.value}] {event.description}",
                    severity=sev,
                    metadata={
                        "failure_id": event.failure_id,
                        "component": event.component.value,
                        "safe_fallback": event.safe_fallback,
                    },
                )
            except Exception as ex:
                logger.debug(f"[ResilienceEngine] Telemetry emission skipped: {ex}")

    def reset(self) -> None:
        """Reset state for clean testing."""
        with self._lock:
            self._failure_events.clear()
            self._active_failures.clear()
            self._recovery_actions.clear()
            self.reset_all_circuits()


# Global singleton instance
global_resilience_engine = ResilienceEngine()
