# AI-Trading-Desk: Operational Runbook & Production Readiness Guide

## 1. System Architecture & Modalities

The AI-Trading-Desk operates as a hardened Multi-Agent Trading OS. In production environments, execution is strictly constrained to authorized validation modes:

| Mode | Real Money? | Order Submission Authority | Description |
|---|---|---|---|
| **RESEARCH** | ✗ NO | NONE | Point-in-time historical backtesting, walk-forward validation, parameter sensitivity surfaces, and Monte Carlo resampling. |
| **SHADOW** | ✗ NO | NONE | Live market tick ingestion, momentum signal evaluation, committee debate, risk gating, and hypothetical decision generation with zero order submission. |
| **PAPER** | ✗ NO | SIMULATED ONLY | Authoritative paper orders routed through `ExecutionGuard` $\to$ `RiskEngine` $\to$ `PreFlight` $\to$ `PaperBrokerAdapter` $\to$ `Accounting`. |
| **LIVE (TIER_4)** | ✗ NO | **PERMANENTLY LOCKED** | `TIER_4_LIVE_REAL_MONEY` is disabled, unroutable, and fail-closed. `BrokerFactory.get_adapter("live")` raises `ConfigurationSafetyError`. |

---

## 2. Startup & Readiness Procedures

### 2.1 Starting the System
Run the main FastAPI server:
```powershell
.\venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### 2.2 Verifying Readiness
Check the readiness endpoint:
```http
GET /api/system/readiness/status
```
Expected response:
```json
{
  "readiness": true,
  "operational_state": "READY",
  "safety_health": {
    "name": "ExecutionGuard & RealMoneySafetyLock",
    "status": "HEALTHY"
  }
}
```
> [!CAUTION]
> If `readiness` is `false` or `operational_state` is `NOT_READY` / `DEGRADED`, do NOT proceed to forward paper simulation. Inspect `dependency_health` for offline components.

---

## 3. Health & Liveness Semantics

- **Liveness Endpoint**: `GET /api/system/health/liveness`
  - Returns `{"liveness": true, "process": "UP"}`. Indicates the Python process is responding.
- **Readiness Endpoint**: `GET /api/system/health/readiness`
  - Verifies that `RiskEngine`, `PreFlight`, `PaperBrokerAdapter`, and `TamperEvidentAuditChain` are operational.
- **Complete Health Summary**: `GET /api/system/health/summary`
  - Provides aggregated status across all subsystems, active worker counts, and queue depths.

---

## 4. Paper Worker & Forward Session Management

### 4.1 Pausing Paper Workers
If market volatility or anomalous streaming ticks are detected, pause worker processing:
```http
POST /api/forward-validation/sessions/{session_id}/pause
```
Or use Dashboard Tab 13 (`[FORWARD]`) / Tab 14 (`[CERT]`).

### 4.2 Resuming Paper Workers
Once feed integrity is restored:
```http
POST /api/forward-validation/sessions/{session_id}/resume
```

---

## 5. Graceful Shutdown & Recovery Procedures

### 5.1 Graceful Shutdown
To cleanly drain in-flight paper operations and preserve accounting state:
```http
POST /api/system/shutdown
```
1. System enters `SHUTTING_DOWN`.
2. New tick ingestion is rejected.
3. In-flight paper operations drain to completion.
4. Audit chain flushes all events.
5. System enters `STOPPED`.

### 5.2 Creating a State Checkpoint
Before maintenance or container restarts, create a cryptographically sealed checkpoint:
```http
POST /api/system/checkpoint
```
The checkpoint saves active symbols, accounting balances, and audit sequence numbers with a SHA-256 payload checksum.

### 5.3 Restoring from Checkpoint
```http
POST /api/system/restore
Content-Type: application/json

{"checkpoint_id": "chk-xxxxxxxx"}
```
> [!IMPORTANT]
> If a checkpoint has been tampered with or modified on disk, `restore_checkpoint` detects the checksum mismatch and **fails closed** with `CHECKPOINT_CORRUPTION_DETECTED`.

---

## 6. Incident Response & Troubleshooting

| Symptom | Cause | Diagnostic Command | Remediation |
|---|---|---|---|
| `DataQualityDegraded` event | Stale ticks (>300s) or out-of-order timestamps | Check Dashboard Tab 13 Data Quality card | Switch data provider via Tab 7 (`[DATA]`) or pause session. |
| Audit chain `BROKEN_CHAIN` | Event payload modified or hash mismatch | `GET /api/observability/audit/verify` | Investigate disk logs. Do not resume until audit integrity is restored. |
| `ConfigurationSafetyError` | Live mode requested | Normal safety behavior | Live mode is permanently locked. No remediation needed. |

---

## 7. System Certification Checklist

Before running any forward paper simulation:
1. Run System Certification: `GET /api/system/certification`.
2. Verify all 12 categories pass:
   - Configuration Safety: 100/100
   - Startup Readiness: 95+/100
   - Dependency Health: 100/100
   - Audit Integrity: 100/100
   - Paper Execution Safety: 100/100
3. Verify overall status is `CERTIFIED`.
