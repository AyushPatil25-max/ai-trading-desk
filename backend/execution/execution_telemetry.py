"""
Phase 32 — Real-Time Execution Telemetry, Latency Profiler & Drift Observability

Pure-Python deterministic observability engine that collects monotonic execution
timing spans, profiles latency distributions (p50, p90, p95, p99), computes real-time
health metrics, and detects operational drift.

Safety Invariants:
- OBSERVABILITY ONLY: Telemetry metrics NEVER modify execution authority or safety gates.
- Nanosecond monotonic clock precision: Durations computed from time.perf_counter_ns().
- Pure Python deterministic statistics (zero LLM numerical hallucination).
- Bounded in-memory retention: Ring buffer preventing unbounded memory growth.
- Zero plaintext credentials or sensitive confirmation tokens logged or stored.
"""

from collections import deque
from datetime import datetime, timezone
import logging
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

from backend.domain.execution_decision_schemas import ExecutionMode
from backend.domain.execution_telemetry_schemas import (
    DriftDetectionReport,
    ExecutionHealthMetrics,
    ExecutionLatencyProfile,
    ExecutionTelemetrySample,
    LatencyPercentiles,
    ObservabilityHealthState,
)
from backend.domain.observability_schemas import (
    EventCategory,
    EventSeverity,
    _sanitize_payload,
)
from backend.application.tamper_evident_audit_chain import global_audit_chain
from backend.config.execution_telemetry_config import (
    get_all_telemetry_config,
    get_broker_latency_critical_ms,
    get_broker_latency_warn_ms,
    get_drift_baseline_window,
    get_drift_sensitivity_ratio,
    get_execution_error_rate_critical,
    get_execution_error_rate_warn,
    get_execution_latency_critical_ms,
    get_execution_latency_warn_ms,
    get_telemetry_retention_limit,
)
from backend.execution.safety_engine import global_kill_switch

logger = logging.getLogger(__name__)


def compute_percentiles(values: List[float]) -> LatencyPercentiles:
    """
    Pure-Python deterministic calculation of standard latency distribution percentiles.
    """
    if not values:
        return LatencyPercentiles(
            count=0,
            min_ms=0.0,
            max_ms=0.0,
            mean_ms=0.0,
            median_ms=0.0,
            p50_ms=0.0,
            p90_ms=0.0,
            p95_ms=0.0,
            p99_ms=0.0,
            std_dev_ms=0.0,
        )

    clean_vals = [float(v) for v in values if not (math.isnan(v) or math.isinf(v)) and v >= 0.0]
    if not clean_vals:
        return LatencyPercentiles(
            count=0, min_ms=0.0, max_ms=0.0, mean_ms=0.0, median_ms=0.0,
            p50_ms=0.0, p90_ms=0.0, p95_ms=0.0, p99_ms=0.0, std_dev_ms=0.0,
        )

    n = len(clean_vals)
    sorted_vals = sorted(clean_vals)
    min_v = sorted_vals[0]
    max_v = sorted_vals[-1]
    mean_v = sum(sorted_vals) / n

    # Variance and standard deviation
    variance = sum((x - mean_v) ** 2 for x in sorted_vals) / n if n > 1 else 0.0
    std_dev = math.sqrt(variance)

    def _get_percentile(pct: float) -> float:
        if n == 1:
            return sorted_vals[0]
        k = (n - 1) * (pct / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_vals[int(k)]
        d0 = sorted_vals[int(f)] * (c - k)
        d1 = sorted_vals[int(c)] * (k - f)
        return d0 + d1

    median_v = _get_percentile(50.0)
    p50_v = median_v
    p90_v = _get_percentile(90.0)
    p95_v = _get_percentile(95.0)
    p99_v = _get_percentile(99.0)

    return LatencyPercentiles(
        count=n,
        min_ms=round(min_v, 4),
        max_ms=round(max_v, 4),
        mean_ms=round(mean_v, 4),
        median_ms=round(median_v, 4),
        p50_ms=round(p50_v, 4),
        p90_ms=round(p90_v, 4),
        p95_ms=round(p95_v, 4),
        p99_ms=round(p99_v, 4),
        std_dev_ms=round(std_dev, 4),
    )


class ExecutionTelemetryCollector:
    """
    Central, thread-safe, bounded in-memory telemetry collector and drift analyzer.
    """

    def __init__(self, capacity: Optional[int] = None):
        self._lock = threading.RLock()
        self._capacity = capacity or get_telemetry_retention_limit()
        self._samples: deque[ExecutionTelemetrySample] = deque(maxlen=self._capacity)
        self._sample_by_id: Dict[str, ExecutionTelemetrySample] = {}
        self._sample_by_exec: Dict[str, List[ExecutionTelemetrySample]] = {}

        # Counters for real-time health
        self._total_count = 0
        self._success_count = 0
        self._rejection_count = 0
        self._failure_count = 0
        self._timeout_count = 0
        self._retry_count = 0
        self._duplicate_count = 0
        self._reconciliation_count = 0
        self._kill_switch_count = 0
        self._stale_signal_rejections_count = 0
        self._duplicate_order_rejections_count = 0
        self._retry_reconciliation_count = 0

    # ── Tracking & Counter Helpers ────────────────────────────────────────────

    def record_stale_rejection(self) -> None:
        """Increment stale signal rejection counter."""
        with self._lock:
            self._stale_signal_rejections_count += 1
            self._rejection_count += 1
            self._total_count += 1

    def record_duplicate_rejection(self) -> None:
        """Increment duplicate order rejection counter."""
        with self._lock:
            self._duplicate_order_rejections_count += 1
            self._duplicate_count += 1
            self._rejection_count += 1
            self._total_count += 1

    def record_reconciliation(self) -> None:
        """Increment reconciliation counter."""
        with self._lock:
            self._retry_reconciliation_count += 1
            self._reconciliation_count += 1

    # ── Sample Recording ──────────────────────────────────────────────────────

    def record_sample(self, sample: ExecutionTelemetrySample) -> None:
        """
        Record an execution telemetry sample into the bounded in-memory store.
        """
        with self._lock:
            # Enforce ring buffer capacity
            if len(self._samples) >= self._samples.maxlen:
                oldest = self._samples.popleft()
                self._sample_by_id.pop(oldest.sample_id, None)
                if oldest.execution_id in self._sample_by_exec:
                    self._sample_by_exec[oldest.execution_id] = [
                        s for s in self._sample_by_exec[oldest.execution_id] if s.sample_id != oldest.sample_id
                    ]
                    if not self._sample_by_exec[oldest.execution_id]:
                        self._sample_by_exec.pop(oldest.execution_id, None)

            self._samples.append(sample)
            self._sample_by_id[sample.sample_id] = sample
            self._sample_by_exec.setdefault(sample.execution_id, []).append(sample)

            # Update counters
            self._total_count += 1
            if sample.outcome == "SUCCESS":
                self._success_count += 1
            elif sample.outcome in ("REJECTED", "BLOCKED", "CONFLICTED"):
                self._rejection_count += 1
            elif sample.outcome == "FAILED":
                self._failure_count += 1

            if sample.failure_category == "TIMEOUT":
                self._timeout_count += 1
            if sample.retry_count > 0:
                self._retry_count += sample.retry_count
            if sample.reconciliation_status:
                self._reconciliation_count += 1
                self._retry_reconciliation_count += 1

            if global_kill_switch.is_active():
                self._kill_switch_count += 1

            # Check for Latency Threshold Warnings
            self._evaluate_threshold_alerts(sample)

    def _evaluate_threshold_alerts(self, sample: ExecutionTelemetrySample) -> None:
        """Check sample against latency thresholds and emit audit alerts if exceeded."""
        crit_thresh = get_execution_latency_critical_ms()
        warn_thresh = get_execution_latency_warn_ms()

        if sample.total_end_to_end_latency_ms >= crit_thresh:
            self._emit_audit(
                event_type="EXECUTION_TELEMETRY_CRITICAL",
                severity=EventSeverity.CRITICAL,
                reason=f"Execution latency critical: {sample.total_end_to_end_latency_ms:.2f}ms >= {crit_thresh}ms",
                correlation_id=sample.audit_correlation_id,
                payload={
                    "sample_id": sample.sample_id,
                    "symbol": sample.symbol,
                    "latency_ms": sample.total_end_to_end_latency_ms,
                    "threshold_ms": crit_thresh,
                },
            )
        elif sample.total_end_to_end_latency_ms >= warn_thresh:
            self._emit_audit(
                event_type="EXECUTION_TELEMETRY_WARNING",
                severity=EventSeverity.WARNING,
                reason=f"Execution latency warning: {sample.total_end_to_end_latency_ms:.2f}ms >= {warn_thresh}ms",
                correlation_id=sample.audit_correlation_id,
                payload={
                    "sample_id": sample.sample_id,
                    "symbol": sample.symbol,
                    "latency_ms": sample.total_end_to_end_latency_ms,
                    "threshold_ms": warn_thresh,
                },
            )

    # ── Latency Profiling ─────────────────────────────────────────────────────

    def get_latency_profile(
        self,
        mode: Optional[ExecutionMode] = None,
        limit: Optional[int] = None,
    ) -> ExecutionLatencyProfile:
        """
        Generate statistical latency distribution percentiles across collected samples.
        """
        with self._lock:
            samples = list(self._samples)
            if mode is not None:
                samples = [s for s in samples if s.execution_mode == mode]

            if limit is not None and limit > 0:
                samples = samples[-limit:]

            decision_latencies = [s.total_decision_latency_ms for s in samples]
            orch_latencies = [s.total_orchestration_latency_ms for s in samples]
            broker_latencies = [
                s.broker_response_latency_ms if s.broker_response_latency_ms is not None else s.broker_latency_ms
                for s in samples
                if (s.broker_response_latency_ms is not None or s.broker_latency_ms is not None)
            ]
            e2e_latencies = [s.total_end_to_end_latency_ms for s in samples]

            sig_to_gov_latencies = [s.signal_received_to_governance_ms or s.signal_to_governance_ms for s in samples]
            gov_to_risk_latencies = [s.governance_to_risk_ms for s in samples if s.governance_to_risk_ms > 0]
            risk_to_preflight_latencies = [s.risk_to_preflight_ms for s in samples if s.risk_to_preflight_ms > 0]
            preflight_to_readiness_latencies = [s.preflight_to_live_readiness_ms for s in samples if s.preflight_to_live_readiness_ms > 0]
            readiness_to_sub_latencies = [s.readiness_to_broker_submission_ms for s in samples if s.readiness_to_broker_submission_ms > 0]
            ai_latencies = [s.ai_advisory_latency_ms for s in samples if s.ai_advisory_latency_ms is not None]
            retry_recon_latencies = [s.retry_reconciliation_latency_ms for s in samples if s.retry_reconciliation_latency_ms is not None]

            dec_pct = compute_percentiles(decision_latencies)
            orch_pct = compute_percentiles(orch_latencies)
            broker_pct = compute_percentiles(broker_latencies) if broker_latencies else None
            e2e_pct = compute_percentiles(e2e_latencies)

            return ExecutionLatencyProfile(
                total_samples=len(samples),
                execution_mode=mode,
                signal_received_to_governance=compute_percentiles(sig_to_gov_latencies) if sig_to_gov_latencies else None,
                governance_to_risk=compute_percentiles(gov_to_risk_latencies) if gov_to_risk_latencies else None,
                risk_to_preflight=compute_percentiles(risk_to_preflight_latencies) if risk_to_preflight_latencies else None,
                preflight_to_live_readiness=compute_percentiles(preflight_to_readiness_latencies) if preflight_to_readiness_latencies else None,
                readiness_to_broker_submission=compute_percentiles(readiness_to_sub_latencies) if readiness_to_sub_latencies else None,
                broker_response_latency=broker_pct,
                total_execution_decision_latency=compute_percentiles([s.total_execution_decision_latency_ms or s.total_decision_latency_ms for s in samples]),
                ai_advisory_latency=compute_percentiles(ai_latencies) if ai_latencies else None,
                retry_reconciliation_latency=compute_percentiles(retry_recon_latencies) if retry_recon_latencies else None,
                decision_pipeline_latency=dec_pct,
                orchestration_latency=orch_pct,
                broker_latency=broker_pct,
                end_to_end_latency=e2e_pct,
                evaluated_at=datetime.now(timezone.utc),
            )

    # ── Health Metrics ────────────────────────────────────────────────────────

    def get_health_metrics(self) -> ExecutionHealthMetrics:
        """
        Calculate current execution health rates and operational status.
        """
        with self._lock:
            tot = max(self._total_count, self._success_count + self._rejection_count + self._failure_count)
            succ = self._success_count
            rej = self._rejection_count
            fail = self._failure_count
            to = self._timeout_count
            retries = self._retry_count

            succ_rate = min(1.0, max(0.0, round(succ / tot, 4))) if tot > 0 else 1.0
            rej_rate = min(1.0, max(0.0, round(rej / tot, 4))) if tot > 0 else 0.0
            fail_rate = min(1.0, max(0.0, round(fail / tot, 4))) if tot > 0 else 0.0
            to_rate = min(1.0, max(0.0, round(to / tot, 4))) if tot > 0 else 0.0
            retry_rate = min(1.0, max(0.0, round(retries / tot, 4))) if tot > 0 else 0.0

            # Determine health state
            crit_fail_rate = get_execution_error_rate_critical()
            warn_fail_rate = get_execution_error_rate_warn()

            if global_kill_switch.is_active():
                state = ObservabilityHealthState.CRITICAL
            elif fail_rate >= crit_fail_rate or to_rate >= crit_fail_rate:
                state = ObservabilityHealthState.CRITICAL
            elif fail_rate >= warn_fail_rate or to_rate >= warn_fail_rate:
                state = ObservabilityHealthState.WARNING
            elif rej_rate > 0.50:
                state = ObservabilityHealthState.DEGRADED
            else:
                state = ObservabilityHealthState.HEALTHY

            last_ts = self._samples[-1].timestamp if self._samples else None

            return ExecutionHealthMetrics(
                total_executions=tot,
                success_count=succ,
                rejection_count=rej,
                failure_count=fail,
                timeout_count=to,
                retry_count=retries,
                duplicate_count=self._duplicate_count,
                reconciliation_count=self._reconciliation_count,
                kill_switch_interventions=self._kill_switch_count,
                stale_signal_rejections_count=self._stale_signal_rejections_count,
                duplicate_order_rejections_count=self._duplicate_order_rejections_count,
                retry_reconciliation_count=self._retry_reconciliation_count,
                success_rate=succ_rate,
                rejection_rate=rej_rate,
                failure_rate=fail_rate,
                retry_rate=retry_rate,
                timeout_rate=to_rate,
                health_state=state,
                last_sample_timestamp=last_ts,
            )

    # ── Operational Drift Detection ───────────────────────────────────────────

    def detect_drift(
        self,
        baseline_window: Optional[int] = None,
        recent_window: Optional[int] = None,
    ) -> DriftDetectionReport:
        """
        Evaluate latency, error, and rejection drift between recent and baseline windows.
        """
        with self._lock:
            samples = list(self._samples)
            total = len(samples)

            base_w = baseline_window or get_drift_baseline_window()
            rec_w = recent_window or max(5, base_w // 5)
            sensitivity = get_drift_sensitivity_ratio()

            now = datetime.now(timezone.utc)

            # Insufficient sample protection
            if total < (rec_w + 5):
                return DriftDetectionReport(
                    is_drift_detected=False,
                    drift_category=None,
                    baseline_samples_count=total,
                    recent_samples_count=0,
                    summary="Insufficient samples for drift analysis.",
                    detected_at=now,
                )

            recent_samples = samples[-rec_w:]
            baseline_samples = samples[-(base_w + rec_w):-rec_w]
            if not baseline_samples:
                baseline_samples = samples[:-rec_w]

            base_e2e = [s.total_end_to_end_latency_ms for s in baseline_samples]
            rec_e2e = [s.total_end_to_end_latency_ms for s in recent_samples]

            base_mean = sum(base_e2e) / len(base_e2e) if base_e2e else 0.0
            rec_mean = sum(rec_e2e) / len(rec_e2e) if rec_e2e else 0.0

            ratio = round(rec_mean / base_mean, 4) if base_mean > 0.0 else 1.0

            # Error rates
            base_errors = sum(1 for s in baseline_samples if s.outcome == "FAILED")
            rec_errors = sum(1 for s in recent_samples if s.outcome == "FAILED")
            base_err_rate = base_errors / len(baseline_samples) if baseline_samples else 0.0
            rec_err_rate = rec_errors / len(recent_samples) if recent_samples else 0.0
            err_drift = round(rec_err_rate - base_err_rate, 4)

            # Rejection rates
            base_rejs = sum(1 for s in baseline_samples if s.outcome in ("REJECTED", "BLOCKED"))
            rec_rejs = sum(1 for s in recent_samples if s.outcome in ("REJECTED", "BLOCKED"))
            base_rej_rate = base_rejs / len(baseline_samples) if baseline_samples else 0.0
            rec_rej_rate = rec_rejs / len(recent_samples) if recent_samples else 0.0
            rej_drift = round(rec_rej_rate - base_rej_rate, 4)

            is_drift = False
            drift_cat = None
            summary = "Operational metrics within expected baseline tolerances."

            if ratio >= sensitivity and rec_mean > get_execution_latency_warn_ms():
                is_drift = True
                drift_cat = "LATENCY_DRIFT"
                summary = f"Latency drift detected: recent mean ({rec_mean:.2f}ms) is {ratio:.2f}x baseline ({base_mean:.2f}ms)."
                self._emit_audit(
                    event_type="LATENCY_DRIFT_DETECTED",
                    severity=EventSeverity.WARNING,
                    reason=summary,
                    correlation_id=f"drift-{uuid.uuid4().hex[:8]}",
                    payload={"recent_mean_ms": rec_mean, "baseline_mean_ms": base_mean, "ratio": ratio},
                )
            elif err_drift >= 0.10:
                is_drift = True
                drift_cat = "ERROR_RATE_DRIFT"
                summary = f"Error rate drift detected: recent error rate shifted +{err_drift * 100:.1f}%."

            return DriftDetectionReport(
                is_drift_detected=is_drift,
                drift_category=drift_cat,
                baseline_samples_count=len(baseline_samples),
                recent_samples_count=len(recent_samples),
                baseline_mean_latency_ms=round(base_mean, 4),
                recent_mean_latency_ms=round(rec_mean, 4),
                latency_drift_ratio=ratio,
                broker_error_rate_drift=err_drift,
                rejection_rate_drift=rej_drift,
                health_state=ObservabilityHealthState.WARNING if is_drift else ObservabilityHealthState.HEALTHY,
                summary=summary,
                detected_at=now,
            )

    # ── Queries & Observability ───────────────────────────────────────────────

    def get_sample(self, sample_id: str) -> Optional[ExecutionTelemetrySample]:
        """Retrieve telemetry sample by ID."""
        with self._lock:
            return self._sample_by_id.get(sample_id)

    def get_samples_by_execution(self, execution_id: str) -> List[ExecutionTelemetrySample]:
        """Retrieve telemetry samples associated with an execution ID."""
        with self._lock:
            return list(self._sample_by_exec.get(execution_id, []))

    def get_recent_samples(self, limit: int = 50) -> List[ExecutionTelemetrySample]:
        """Retrieve latest N samples."""
        with self._lock:
            bounded_limit = min(limit, len(self._samples))
            return list(self._samples)[-bounded_limit:]

    def clear(self) -> None:
        """Clear all in-memory telemetry samples (used for test isolation)."""
        with self._lock:
            self._samples.clear()
            self._sample_by_id.clear()
            self._sample_by_exec.clear()
            self._total_count = 0
            self._success_count = 0
            self._rejection_count = 0
            self._failure_count = 0
            self._timeout_count = 0
            self._retry_count = 0
            self._duplicate_count = 0
            self._reconciliation_count = 0
            self._kill_switch_count = 0

    def _emit_audit(
        self,
        event_type: str,
        severity: EventSeverity,
        reason: str,
        correlation_id: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            global_audit_chain.append_event(
                event_type=event_type,
                category=EventCategory.OBSERVABILITY,
                component="ExecutionTelemetryCollector",
                correlation_id=correlation_id,
                severity=severity,
                reason=reason,
                payload=_sanitize_payload(payload or {}),
            )
        except Exception:
            pass


# Global singleton instance
global_execution_telemetry_collector = ExecutionTelemetryCollector()
