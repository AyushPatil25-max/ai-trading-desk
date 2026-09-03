"""
Phase 23 — System Health & SLO Telemetry Engine

Pure-Python operational metrics, throughput tracking, latency percentiles (p50, p95, p99),
queue utilization, and health classification for the Trading OS. Zero LLM math.

Safety Invariant:
- STRICTLY OBSERVATIONAL: Zero authority to submit orders.
- Pure Python deterministic math for all SLO metrics.
- TIER_4_LIVE_REAL_MONEY remains permanently locked and fail-closed.
"""

from collections import deque
from datetime import datetime, timezone
import logging
import math
import threading
import time
from typing import Any, Deque, Dict, List, Optional

from backend.domain.observability_schemas import (
    AuditVerificationStatus,
    OperationalHealthLevel,
    SLOMetricsSnapshot,
)

logger = logging.getLogger(__name__)


def _calculate_percentile(data: List[float], percentile: float) -> float:
    """Calculate percentile using pure-Python linear interpolation."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    n = len(sorted_data)
    if n == 1:
        return sorted_data[0]

    k = (n - 1) * (percentile / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    d0 = sorted_data[int(f)] * (c - k)
    d1 = sorted_data[int(c)] * (k - f)
    return d0 + d1


class SLOTelemetryEngine:
    """
    Real-time operational SLO tracking engine.
    Calculates pure-Python latency percentiles, throughput, and error metrics.
    """

    def __init__(self, latency_window_size: int = 1_000, throughput_window_seconds: float = 60.0):
        self._lock = threading.RLock()
        self._latencies: Deque[float] = deque(maxlen=latency_window_size)
        self._event_timestamps: Deque[float] = deque(maxlen=10_000)
        self._throughput_window_seconds = throughput_window_seconds

        # SLO event counters
        self._dropped_events: int = 0
        self._rejected_events: int = 0
        self._stale_events: int = 0
        self._duplicate_events: int = 0
        self._out_of_order_events: int = 0
        self._worker_failures: int = 0
        self._degraded_started_at: Optional[float] = None
        self._total_degraded_duration_ms: float = 0.0

        # Subsystem references (lazy-loaded)
        self._supervisor: Optional[Any] = None
        self._stream_manager: Optional[Any] = None
        self._worker_pool: Optional[Any] = None
        self._audit_chain: Optional[Any] = None

    # ── Telemetry Ingestion (Step 5) ──────────────────────────────────────────

    def record_operation_latency(self, latency_ms: float) -> None:
        """Record operational latency observation in the rolling window."""
        with self._lock:
            self._latencies.append(max(0.0, float(latency_ms)))
            self._event_timestamps.append(time.monotonic())

    def record_event_processed(self) -> None:
        """Record an operational event timestamp for throughput calculation."""
        with self._lock:
            self._event_timestamps.append(time.monotonic())

    def record_anomaly(
        self,
        is_dropped: bool = False,
        is_rejected: bool = False,
        is_stale: bool = False,
        is_duplicate: bool = False,
        is_out_of_order: bool = False,
        is_worker_failure: bool = False,
    ) -> None:
        """Record operational anomaly counts."""
        with self._lock:
            if is_dropped:
                self._dropped_events += 1
            if is_rejected:
                self._rejected_events += 1
            if is_stale:
                self._stale_events += 1
            if is_duplicate:
                self._duplicate_events += 1
            if is_out_of_order:
                self._out_of_order_events += 1
            if is_worker_failure:
                self._worker_failures += 1

    def set_degraded_state(self, is_degraded: bool) -> None:
        """Track duration spent in degraded operational states."""
        with self._lock:
            now = time.monotonic()
            if is_degraded and self._degraded_started_at is None:
                self._degraded_started_at = now
            elif not is_degraded and self._degraded_started_at is not None:
                self._total_degraded_duration_ms += (now - self._degraded_started_at) * 1000.0
                self._degraded_started_at = None

    # ── Snapshot Generation (Step 6) ──────────────────────────────────────────

    def get_metrics_snapshot(self) -> SLOMetricsSnapshot:
        """
        Generate complete operational SLO snapshot with percentiles and health state.
        """
        with self._lock:
            now = time.monotonic()
            cutoff = now - self._throughput_window_seconds

            # Purge expired timestamps for throughput calculation
            while self._event_timestamps and self._event_timestamps[0] < cutoff:
                self._event_timestamps.popleft()

            throughput = len(self._event_timestamps) / self._throughput_window_seconds

            # Calculate pure-Python percentiles
            lat_list = list(self._latencies)
            p50 = _calculate_percentile(lat_list, 50.0)
            p95 = _calculate_percentile(lat_list, 95.0)
            p99 = _calculate_percentile(lat_list, 99.0)
            avg_lat = (sum(lat_list) / len(lat_list)) if lat_list else 0.0

            # Subsystem telemetry
            active_workers = 0
            total_workers = 0
            queue_depth = 0
            queue_cap = 1000

            if self._worker_pool is None:
                try:
                    from backend.application.distributed_paper_worker import global_worker_pool
                    self._worker_pool = global_worker_pool
                except ImportError:
                    pass

            if self._worker_pool:
                try:
                    status = self._worker_pool.get_pool_status()
                    active_workers = status.healthy_workers
                    total_workers = status.total_workers
                except Exception:
                    pass

            if self._stream_manager is None:
                try:
                    from backend.application.stream_manager import global_stream_manager
                    self._stream_manager = global_stream_manager
                except ImportError:
                    pass

            if self._stream_manager and hasattr(self._stream_manager, "get_metrics"):
                try:
                    m = self._stream_manager.get_metrics()
                    queue_depth = getattr(m, "queue_depth", 0)
                    queue_cap = getattr(m, "queue_capacity", 1000)
                except Exception:
                    pass

            queue_pct = (queue_depth / queue_cap * 100.0) if queue_cap > 0 else 0.0

            # Determine health state
            overall_health = OperationalHealthLevel.HEALTHY
            if self._worker_failures > 5 or p99 > 5000.0 or queue_pct > 90.0:
                overall_health = OperationalHealthLevel.UNHEALTHY
            elif self._dropped_events > 0 or p95 > 1000.0 or queue_pct > 60.0 or self._degraded_started_at:
                overall_health = OperationalHealthLevel.DEGRADED

            # Check audit chain verification
            audit_status = AuditVerificationStatus.VALID
            if self._audit_chain is None:
                try:
                    from backend.application.tamper_evident_audit_chain import global_audit_chain
                    self._audit_chain = global_audit_chain
                except ImportError:
                    pass

            if self._audit_chain:
                try:
                    rep = self._audit_chain.verify_integrity()
                    audit_status = rep.status
                except Exception:
                    audit_status = AuditVerificationStatus.MALFORMED_EVENT

            # Calculate ongoing degraded duration
            ongoing_degraded = (
                (now - self._degraded_started_at) * 1000.0
                if self._degraded_started_at
                else 0.0
            )

            return SLOMetricsSnapshot(
                evaluated_at=datetime.now(timezone.utc),
                overall_health=overall_health,
                throughput_events_per_sec=round(throughput, 2),
                latency_p50_ms=round(p50, 2),
                latency_p95_ms=round(p95, 2),
                latency_p99_ms=round(p99, 2),
                avg_latency_ms=round(avg_lat, 2),
                queue_depth=queue_depth,
                queue_utilization_pct=round(queue_pct, 2),
                dropped_events=self._dropped_events,
                rejected_events=self._rejected_events,
                stale_events=self._stale_events,
                duplicate_events=self._duplicate_events,
                out_of_order_events=self._out_of_order_events,
                worker_failures=self._worker_failures,
                recovery_success_rate=1.0 if self._worker_failures == 0 else max(0.0, 1.0 - (self._worker_failures * 0.1)),
                degraded_duration_ms=round(self._total_degraded_duration_ms + ongoing_degraded, 2),
                audit_verification_status=audit_status,
                active_workers_count=active_workers,
                total_workers_count=total_workers,
                live_trading_permanently_locked=True,
            )

    def reset(self) -> None:
        """Reset internal metrics for test cases."""
        with self._lock:
            self._latencies.clear()
            self._event_timestamps.clear()
            self._dropped_events = 0
            self._rejected_events = 0
            self._stale_events = 0
            self._duplicate_events = 0
            self._out_of_order_events = 0
            self._worker_failures = 0
            self._degraded_started_at = None
            self._total_degraded_duration_ms = 0.0


# Global singleton instance
global_slo_telemetry_engine = SLOTelemetryEngine()
