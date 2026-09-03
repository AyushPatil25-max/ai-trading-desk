# Phase 32: Real-Time Execution Telemetry, Latency Profiling & Drift Observability

## 1. Executive Summary & Objective

Phase 32 establishes a **production-grade observability layer** for the Trading OS. It measures, records, profiles, and exposes execution behavior, latency percentiles, operational health metrics, and drift detection **without changing execution authority or bypassing any safety mechanisms**.

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                    EXECUTION TELEMETRY, LATENCY PROFILING & DRIFT                           │
├─────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                             │
│  Pipeline Lifecycle Execution                                                               │
│      │                                                                                      │
│      ├─► Monotonic Clock Timing Spans (time.perf_counter_ns())                              │
│      ├─► ExecutionTelemetrySample (Decisions, Orchestration, Broker latencies)              │
│      │                                                                                      │
│      ▼                                                                                      │
│  ExecutionTelemetryCollector (Thread-safe Bounded In-Memory Store, default 1000 capacity)   │
│      │                                                                                      │
│      ├─► Latency Profiler: Statistical Distribution (p50, p90, p95, p99, min, max, mean)   │
│      ├─► Real-Time Health Metrics: Success, Rejection, Failure, Retry, Timeout rates        │
│      ├─► Operational Drift Detector: Latency Drift, Error Rate Drift, Rejection Drift       │
│      ├─► Latency Threshold Evaluator: EXECUTION_LATENCY_WARN / CRITICAL                     │
│      └─► Tamper-Evident Audit Logging: LATENCY_DRIFT_DETECTED / EXECUTION_TELEMETRY_WARN    │
│                                                                                             │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Core Architectural Components

### 2.1 Domain Schemas (`backend/domain/execution_telemetry_schemas.py`)
- **`ObservabilityHealthState`**: `HEALTHY`, `DEGRADED`, `WARNING`, `CRITICAL`, `UNAVAILABLE`.
- **`TelemetryLifecycleStage`**: Stages across the entire signal $\to$ governance $\to$ decision $\to$ preflight $\to$ readiness $\to$ broker $\to$ reconciliation path.
- **`ExecutionTimingSpan`**: Monotonic nanosecond timing span with computed millisecond duration.
- **`ExecutionTelemetrySample`**: Individual execution measurement record with granular stage latencies, outcome, failure category, retry count, and reconciliation status.
- **`LatencyPercentiles`** & **`ExecutionLatencyProfile`**: Pure-Python deterministic statistical distribution metrics ($p50, p90, p95, p99$, min, max, mean, standard deviation).
- **`ExecutionHealthMetrics`**: Real-time operational rates (success rate, rejection rate, failure rate, retry rate, timeout rate).
- **`DriftDetectionReport`**: Comparative drift report comparing recent sample distribution against historical baseline window.

### 2.2 Telemetry Collector & Drift Engine (`backend/execution/execution_telemetry.py`)
- **`ExecutionTelemetryCollector`**: Thread-safe (`threading.RLock`) bounded in-memory ring buffer preventing unbounded memory growth.
- **`compute_percentiles`**: Pure-Python deterministic percentile calculation handling empty/small sample sizes gracefully without mathematical errors or LLM hallucinations.
- **`detect_drift`**: Evaluates `latency_drift_ratio = recent_mean / baseline_mean` against `DRIFT_SENSITIVITY_RATIO` and detects error/rejection shifts.
- **Audit Integration**: Emits `LATENCY_DRIFT_DETECTED`, `EXECUTION_TELEMETRY_WARNING`, and `EXECUTION_TELEMETRY_CRITICAL` events into `global_audit_chain` with recursive secret redaction.

### 2.3 Configuration (`backend/config/execution_telemetry_config.py`)
- Environment-overridable, bounds-checked thresholds:
  - `EXECUTION_LATENCY_WARN_MS`: 50.0 ms (bounds: 1.0 to 5000.0)
  - `EXECUTION_LATENCY_CRITICAL_MS`: 200.0 ms (bounds: 5.0 to 10000.0)
  - `BROKER_LATENCY_WARN_MS`: 500.0 ms (bounds: 10.0 to 15000.0)
  - `BROKER_LATENCY_CRITICAL_MS`: 2000.0 ms (bounds: 50.0 to 30000.0)
  - `EXECUTION_ERROR_RATE_WARN`: 0.05 (5%)
  - `EXECUTION_ERROR_RATE_CRITICAL`: 0.15 (15%)
  - `TELEMETRY_RETENTION_LIMIT`: 1000 samples
  - `DRIFT_BASELINE_WINDOW`: 50 samples
  - `DRIFT_SENSITIVITY_RATIO`: 1.5x

### 2.4 REST API Endpoints (`backend/application/execution_telemetry_routes.py`)
- `GET /api/execution/telemetry/status`: Overall operational health and active configuration.
- `GET /api/execution/telemetry/metrics`: Detailed rates and failure counts.
- `GET /api/execution/telemetry/latency`: Latency percentiles profile (optional mode filter).
- `GET /api/execution/telemetry/drift`: Operational drift report.
- `GET /api/execution/telemetry/history`: Bounded recent telemetry samples.
- `GET /api/execution/telemetry/history/{execution_id}`: Samples for a specific execution.

---

## 3. Safety Invariants & AI Boundary

1. **Observability Only**: Telemetry metrics and drift alerts **NEVER** alter execution decisions, modify risk limits, or bypass safety controls.
2. **AI Advisory Boundary**: AI models cannot alter telemetry thresholds, clear history, or execute trades via telemetry interfaces.
3. **Fail-Closed Default**: `LIVE_EXECUTION_ENABLED=false` remains enforced.
4. **Zero Secret Persistence**: Telemetry models and audit payloads strictly redact access tokens, client secrets, and confirmation tokens.
5. **Monotonic Timing Precision**: All durations are measured using monotonic clock nanoseconds (`time.perf_counter_ns()`).
