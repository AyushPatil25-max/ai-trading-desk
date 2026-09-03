# Phase 30: Authoritative Execution Decision Pipeline

## 1. Executive Summary & Objective

Phase 30 establishes an authoritative, deterministic **Execution Decision Pipeline** for the Trading OS. It creates an explicit multi-stage gating architecture connecting raw strategy signals to broker execution while maintaining absolute separation between Paper Simulation and Live Broker routing.

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                          AUTHORITATIVE EXECUTION DECISION PIPELINE                          │
├─────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                             │
│  Strategy Signal (Rule-Based, Technical, Fundamental, AI Advisory, Manual)                 │
│      │                                                                                      │
│      ├─► Gate 1: SIGNAL_VALIDATION (Schema conformity, finite numbers, fresh timestamps)    │
│      ├─► Gate 2: STRATEGY_GOVERNANCE (Strategy registration, ACTIVE status, whitelists)     │
│      ├─► Gate 3: RISK_ENGINE (Position size ceilings, order value caps, kill switch)        │
│      ├─► Gate 4: EXECUTION_PREFLIGHT (Exchange constraints, tick & symbol sanity)           │
│      │                                                                                      │
│      ├───► [BRANCH: PAPER MODE]                                                             │
│      │         └─► Authorize for Paper Broker Simulator                                     │
│      │                                                                                      │
│      └───► [BRANCH: LIVE MODE] (All gates below are mandatory & fail-closed):               │
│                ├─► Gate 5: LIVE_READINESS (17+ system, connectivity, session checks)        │
│                ├─► Gate 6: LIVE_ARMING (Unexpired 5-min TTL operator arming session)        │
│                ├─► Gate 7: MANUAL_SAFETY_GATE (Price corridor, circuit limits, buying power)│
│                ├─► Gate 8: DUPLICATE_CHECK (OrderTracker SHA-256 fingerprint deduplication) │
│                ├─► Gate 9: CONFIRMATION_CHECK (Cryptographic single-use token verification) │
│                └─► Gate 10: FINAL_AUTHORIZATION -> Live Broker Execution (Dhan v2 API)       │
│                                                                                             │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Core Architectural Components

### 2.1 Domain Schemas (`backend/domain/execution_decision_schemas.py`)
- **`ExecutionPipelineStatus`**: `APPROVED`, `REJECTED`, `BLOCKED`, `CONFLICTED`, `NOT_READY`, `DEGRADED`.
- **`ExecutionMode`**: `PAPER`, `LIVE`.
- **`PipelineGateName`**: `SIGNAL_VALIDATION`, `STRATEGY_GOVERNANCE`, `RISK_ENGINE`, `EXECUTION_PREFLIGHT`, `LIVE_READINESS`, `LIVE_ARMING`, `MANUAL_SAFETY_GATE`, `DUPLICATE_CHECK`, `CONFIRMATION_CHECK`, `FINAL_AUTHORIZATION`.
- **`GateExecutionResult`**: Records the pass/fail outcome, timestamp, reason, and subsystem details for each gate in the pipeline.
- **`ExecutionPipelineDecision`**: Authoritative decision container with full stage-by-stage trace, authorization boolean, decision fingerprint, and rejection reasons.
- **`ExecutionPipelineRequest`**: Strongly-typed request DTO for pipeline evaluation.

### 2.2 Execution Decision Engine (`backend/execution/execution_decision_pipeline.py`)
- **Deterministic 10-Stage Sequential Gating**: Evaluates gates in strict sequence. Any single gate failure immediately halts evaluation and marks the decision `BLOCKED` / `REJECTED` / `NOT_READY` / `CONFLICTED`.
- **Advisory Strategy Rule**: Strategy governance approval is strictly non-authorizing on its own. Execution authorization requires the full downstream risk, safety, readiness, and confirmation gates.
- **AI Advisory Boundary**: `AI_ADVISORY` signals undergo the exact same deterministic pipeline gates. AI-provided flags like `"approved=True"` or `"safe=True"` are completely ignored.
- **Paper vs Live Separation**:
  - **Paper Mode**: Bypasses live broker credentials and arming requirements, enabling continuous safe offline simulation.
  - **Live Mode**: Requires active live arming, live readiness clearance, safety gate validation, and single-use confirmation token verification.
- **Durable Persistence**: Persists decision history into `PersistentStateStore` and write-ahead `StateJournal`.
- **Tamper-Evident Audit Logging**: Emits `EXECUTION_DECISION_STARTED`, `EXECUTION_GOVERNANCE_APPROVED`, `EXECUTION_RISK_APPROVED`, `EXECUTION_PREFLIGHT_APPROVED`, `EXECUTION_BLOCKED`, and `EXECUTION_AUTHORIZED` events with recursively sanitized payloads.

### 2.3 REST API Routes (`backend/application/execution_routes.py`)
- `POST /api/execution/decision`: Evaluates the complete execution pipeline without placing broker orders.
- `POST /api/execution/live/evaluate`: Evaluates live mode rules and reports blocking conditions.
- `GET /api/execution/status`: Returns operational throughput statistics of the execution decision pipeline.
- `GET /api/execution/history`: Returns recent decision records.

---

## 3. Safety Invariants & Fail-Closed Enforcement

1. **`LIVE_EXECUTION_ENABLED=false` Default**: Environment configuration default remains fail-closed.
2. **Zero Real-Money Orders**: All automated tests and development workflows execute with mocked broker interfaces or paper simulators.
3. **No Direct Route from Strategy to Broker**: Every strategy signal must traverse the complete execution decision pipeline before any broker submission can occur.
4. **Idempotency & Duplicate Protection**: The `InMemoryOrderTracker` rejects repeated submissions sharing the same SHA-256 fingerprint.
5. **Single-Use Confirmation Tokens**: Live execution requires cryptographically bound, single-use confirmation tokens with 120-second TTLs.
6. **Kill Switch Authority**: Engaging the emergency kill switch halts all pipeline evaluations immediately.
