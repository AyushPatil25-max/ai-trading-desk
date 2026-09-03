# Phase 31: Execution Orchestration & Control Plane

## 1. Executive Summary & Objective

Phase 31 establishes the **Execution Orchestration & Control Plane** for the Trading OS. It takes an approved `ExecutionPipelineDecision` from Phase 30 and deterministically coordinates execution across isolated Paper Simulation and Live Broker pathways while managing lifecycle state transitions, concurrency control, durable persistence, recovery, and audit provenance.

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                          EXECUTION ORCHESTRATION & CONTROL PLANE                            │
├─────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                             │
│  Approved ExecutionPipelineDecision (Phase 30)                                              │
│      │                                                                                      │
│      ├─► 1. Decision Integrity, Provenance & Freshness (Age ≤ 300s, Fingerprint verification)│
│      ├─► 2. Control Plane & Kill Switch Guard (RUNNING vs PAUSED / HALTED)                  │
│      ├─► 3. Lifecycle Initialization (RECEIVED ─► VALIDATING ─► APPROVED ─► PREPARING)       │
│      │                                                                                      │
│      ├───► [BRANCH: PAPER MODE]                                                             │
│      │         ├─► State: PAPER_EXECUTING                                                   │
│      │         ├─► PaperBrokerAdapter Simulation & Position Ledger Settlement               │
│      │         └─► State: FILLED ─► COMPLETED (Zero Live Network Calls)                     │
│      │                                                                                      │
│      └───► [BRANCH: LIVE MODE] (Fail-Closed Default):                                       │
│                ├─► State: LIVE_AWAITING_CONFIRMATION ─► LIVE_EXECUTING                      │
│                ├─► LiveReadiness / LiveArmingStore / ManualOrderSafetyGate / Confirmation   │
│                ├─► OrderTracker Duplicate Filter ─► LiveFailureRecoveryEngine               │
│                ├─► DhanBrokerAdapter v2 Order Submission                                    │
│                └─► State: SUBMITTED ─► FILLED / RECONCILIATION_REQUIRED ─► COMPLETED        │
│                                                                                             │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Core Architectural Components

### 2.1 Domain Schemas (`backend/domain/execution_orchestration_schemas.py`)
- **`ExecutionLifecycleState`**:
  `RECEIVED`, `VALIDATING`, `APPROVED`, `QUEUED`, `PREPARING`, `PAPER_EXECUTING`, `LIVE_AWAITING_CONFIRMATION`, `LIVE_EXECUTING`, `SUBMITTED`, `PARTIALLY_FILLED`, `FILLED`, `CANCEL_PENDING`, `CANCELLED`, `REJECTED`, `FAILED`, `RECONCILIATION_REQUIRED`, `RECOVERY_REQUIRED`, `COMPLETED`.
- **`ExecutionControlState`**: `RUNNING`, `PAUSED`, `DRAINING`, `HALTED`.
- **`ExecutionStage`**: `INITIAL_SUBMISSION`, `DECISION_VERIFICATION`, `ROUTING`, `BROKER_DISPATCH`, `SETTLEMENT`, `COMPLETED`.
- **`ExecutionRecord`**: Durable execution lifecycle container with full transition history (`state_history`), filled metrics, fill price, broker order ID, rejection reasons, and audit correlation IDs.
- **`VALID_ORCHESTRATION_TRANSITIONS`**: Authoritative deterministic state transition table raising `InvalidTransitionError` on illegal lifecycle paths.

### 2.2 Execution Orchestrator (`backend/execution/execution_orchestrator.py`)
- **Orchestration Only**: Does not generate signals, override governance, or alter risk limits.
- **Strict Path Separation**:
  - **Paper Mode**: Dispatches exclusively to `PaperBrokerAdapter`, calculates slippage/commissions, updates ledger, and transitions to `FILLED` $\to$ `COMPLETED` without contacting external broker endpoints.
  - **Live Mode**: Requires explicit opt-in (`LIVE_EXECUTION_ENABLED=true`), unexpired `LiveArmingStore` session, `ManualOrderSafetyGate` approval, valid single-use `ConfirmationStore` token, and routes via `LiveFailureRecoveryEngine` with pre-retry broker reconciliation.
- **Control Plane Operations**:
  - `pause()`: Suspends new execution submissions.
  - `resume()`: Restores orchestrator to `RUNNING` status (unless kill switch active).
  - `halt()`: Emergency halt stopping all pipeline execution.
- **Reconciliation & Cancellation**:
  - `cancel_execution()`: Safely transitions active executions to `CANCEL_PENDING` $\to$ `CANCELLED`.
  - `reconcile_execution()`: Reconciles `RECONCILIATION_REQUIRED` states against broker order book.
- **Durable State Persistence**: Monotonically commits execution mutations to `PersistentStateStore` and appends transition entries to `StateJournal`.
- **Tamper-Evident Audit Logging**: Emits `EXECUTION_ORCHESTRATION_STARTED`, `EXECUTION_FILLED`, `EXECUTION_REJECTED`, `EXECUTION_FAILED`, `EXECUTION_CANCELLED`, `EXECUTION_PAUSED`, `EXECUTION_RESUMED`, and `EXECUTION_HALTED` with sanitized payloads.

### 2.3 REST API Routes (`backend/application/orchestration_routes.py`)
- `POST /api/orchestration/submit`: Submits an approved `ExecutionPipelineDecision` for execution.
- `GET /api/orchestration/{execution_id}`: Retrieves execution lifecycle status.
- `POST /api/orchestration/{execution_id}/cancel`: Requests cancellation of an active execution.
- `POST /api/orchestration/{execution_id}/reconcile`: Triggers reconciliation for an ambiguous state.
- `GET /api/orchestration/status`: Returns control plane state and execution throughput metrics.
- `GET /api/orchestration/history`: Lists all execution history records.
- `POST /api/orchestration/control/pause`: Pauses orchestration.
- `POST /api/orchestration/control/resume`: Resumes orchestration.
- `POST /api/orchestration/control/halt`: Halts orchestration.

---

## 3. Safety Invariants & AI Boundary

1. **Advisory AI Boundary**: AI models and signals with `source = AI_ADVISORY` have zero direct broker authority. Injected approval metadata (`"approved=True"`, `"safe=True"`) is ignored.
2. **Fail-Closed Live Execution**: `LIVE_EXECUTION_ENABLED=false` remains enforced by default.
3. **Emergency Kill Switch Priority**: Kill switch activation halts all orchestration immediately and cannot be overridden by control plane resume commands.
4. **Idempotency & Duplicate Replay Protection**: Requests with identical `decision_id` return existing execution records rather than creating duplicate orders.
5. **No Secret Persistence**: All state mutations and audit payloads are recursively sanitized (zero plaintext tokens or credentials).
