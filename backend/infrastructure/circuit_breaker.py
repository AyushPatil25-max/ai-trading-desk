"""
Phase 21 — Market Data Provider Circuit Breaker

Deterministic, bounded circuit breaker maintaining CLOSED, OPEN, and HALF_OPEN states
with configurable recovery timeouts, probe requests, latency percentile tracking,
and thread-safe state transitions. Pure Python, zero LLM dependencies.
"""

from collections import deque
from datetime import datetime, timezone
import math
import threading
import time
from typing import Deque, Dict, List, Optional
import numpy as np

from backend.domain.provider_schemas import (
    CircuitState,
    FailureType,
    ProviderHealthMetrics,
    ProviderStatus,
)


class CircuitBreaker:
    """
    Thread-safe, stateful circuit breaker for isolating faulty or slow data providers.
    Prevents cascading timeouts and resource exhaustion during upstream outages.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 30.0,
        half_open_success_threshold: int = 1,
        max_latency_history: int = 200,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.half_open_success_threshold = half_open_success_threshold

        self._lock = threading.Lock()
        self._state: CircuitState = CircuitState.CLOSED
        self._opened_at: Optional[float] = None

        self._total_requests: int = 0
        self._successful_requests: int = 0
        self._failed_requests: int = 0
        self._timeout_count: int = 0
        self._validation_rejection_count: int = 0
        self._consecutive_failures: int = 0
        self._consecutive_successes: int = 0
        self._half_open_successes: int = 0
        self._probe_in_flight: bool = False

        self._last_success_timestamp: Optional[datetime] = None
        self._last_failure_timestamp: Optional[datetime] = None
        self._last_failure_type: Optional[FailureType] = None
        self._last_failure_reason: Optional[str] = None

        self._latencies: Deque[float] = deque(maxlen=max_latency_history)

    @property
    def state(self) -> CircuitState:
        """Evaluate and return current state, checking automatic recovery transition."""
        with self._lock:
            if self._state == CircuitState.OPEN:
                if self._opened_at and (time.monotonic() - self._opened_at >= self.recovery_timeout_seconds):
                    self._state = CircuitState.HALF_OPEN
                    self._probe_in_flight = False
                    self._half_open_successes = 0
            return self._state

    def allow_request(self) -> bool:
        """Check whether a request should be dispatched to the underlying provider."""
        with self._lock:
            # Check timeout transition to HALF_OPEN if OPEN
            if self._state == CircuitState.OPEN:
                if self._opened_at and (time.monotonic() - self._opened_at >= self.recovery_timeout_seconds):
                    self._state = CircuitState.HALF_OPEN
                    self._probe_in_flight = False
                    self._half_open_successes = 0

            if self._state == CircuitState.CLOSED:
                self._total_requests += 1
                return True
            elif self._state == CircuitState.HALF_OPEN:
                if not self._probe_in_flight:
                    self._probe_in_flight = True
                    self._total_requests += 1
                    return True
                return False
            else: # OPEN
                return False

    def record_success(self, latency_ms: float = 0.0) -> None:
        """Record a successful provider request and handle recovery transitions."""
        with self._lock:
            self._successful_requests += 1
            self._consecutive_successes += 1
            self._consecutive_failures = 0
            self._last_success_timestamp = datetime.now(timezone.utc)
            if latency_ms > 0:
                self._latencies.append(latency_ms)

            if self._state == CircuitState.HALF_OPEN:
                self._half_open_successes += 1
                self._probe_in_flight = False
                if self._half_open_successes >= self.half_open_success_threshold:
                    self._state = CircuitState.CLOSED
                    self._opened_at = None
                    self._consecutive_failures = 0

    def record_failure(
        self,
        failure_type: FailureType = FailureType.UNKNOWN,
        reason: str = "",
        latency_ms: float = 0.0,
    ) -> None:
        """Record a failed provider request and handle trip transitions."""
        with self._lock:
            self._failed_requests += 1
            self._consecutive_failures += 1
            self._consecutive_successes = 0
            self._last_failure_timestamp = datetime.now(timezone.utc)
            self._last_failure_type = failure_type
            self._last_failure_reason = reason
            if latency_ms > 0:
                self._latencies.append(latency_ms)

            if failure_type == FailureType.TIMEOUT:
                self._timeout_count += 1
            elif failure_type == FailureType.VALIDATION_FAILED:
                self._validation_rejection_count += 1

            if self._state == CircuitState.CLOSED:
                if self._consecutive_failures >= self.failure_threshold:
                    self._state = CircuitState.OPEN
                    self._opened_at = time.monotonic()
            elif self._state == CircuitState.HALF_OPEN:
                self._probe_in_flight = False
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()

    def reset(self) -> None:
        """Operator manual reset back to CLOSED state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._opened_at = None
            self._consecutive_failures = 0
            self._probe_in_flight = False
            self._half_open_successes = 0

    def get_metrics(
        self,
        priority: int = 1,
        is_primary: bool = False,
    ) -> ProviderHealthMetrics:
        """Compute and return pure-Python deterministic health metrics and latencies."""
        with self._lock:
            curr_state = self._state
            if curr_state == CircuitState.OPEN:
                if self._opened_at and (time.monotonic() - self._opened_at >= self.recovery_timeout_seconds):
                    curr_state = CircuitState.HALF_OPEN
                    self._state = CircuitState.HALF_OPEN

            total = self._total_requests
            succ = self._successful_requests
            avail_rate = (succ / total) if total > 0 else 1.0

            # Latency calculations
            if self._latencies:
                l_arr = np.array(self._latencies)
                avg_l = float(np.mean(l_arr))
                p50 = float(np.percentile(l_arr, 50))
                p95 = float(np.percentile(l_arr, 95))
                p99 = float(np.percentile(l_arr, 99))
            else:
                avg_l, p50, p95, p99 = 0.0, 0.0, 0.0, 0.0

            # Determine overall health status
            if curr_state == CircuitState.OPEN:
                status = ProviderStatus.UNAVAILABLE
            elif curr_state == CircuitState.HALF_OPEN:
                status = ProviderStatus.DEGRADED
            elif avail_rate < 0.90 or self._consecutive_failures > 0:
                status = ProviderStatus.DEGRADED
            else:
                status = ProviderStatus.HEALTHY

            return ProviderHealthMetrics(
                provider_name=self.name,
                priority=priority,
                is_primary=is_primary,
                status=status,
                circuit_state=curr_state,
                total_requests=total,
                successful_requests=succ,
                failed_requests=self._failed_requests,
                timeout_count=self._timeout_count,
                validation_rejection_count=self._validation_rejection_count,
                consecutive_failures=self._consecutive_failures,
                consecutive_successes=self._consecutive_successes,
                availability_rate=round(avail_rate, 4),
                avg_latency_ms=round(avg_l, 2),
                p50_latency_ms=round(p50, 2),
                p95_latency_ms=round(p95, 2),
                p99_latency_ms=round(p99, 2),
                last_success_timestamp=self._last_success_timestamp,
                last_failure_timestamp=self._last_failure_timestamp,
                last_failure_type=self._last_failure_type,
                last_failure_reason=self._last_failure_reason,
            )
