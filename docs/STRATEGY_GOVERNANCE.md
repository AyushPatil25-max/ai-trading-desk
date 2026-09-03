# Phase 29: Strategy Governance & Decision Control

## 1. Executive Summary & Objective

Phase 29 establishes an authoritative, deterministic **Strategy Governance & Decision Control** layer for the Trading OS. It enforces strict boundary control over how trading signals from analytical models, technical rules, fundamental scans, and AI advisories are admitted into the downstream execution pipeline.

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                          DECISION CONTROL & GOVERNANCE PIPELINE                             │
├─────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                             │
│  Strategy Signal Sources (Rule-Based, Technical, Fundamental, AI Advisory, Manual)          │
│      │                                                                                      │
│      ├─► STRATEGY GOVERNANCE GATEWAY (17 Deterministic Validation Checks)                   │
│      │       ├─► 1. Strategy Registration & Active Lifecycle Status                         │
│      │       ├─► 2. Strategy Version Match & Whitelist (Instruments/Exchanges)              │
│      │       ├─► 3. Freshness Bounds (Signal Age ≤ 1800s, Market Data Age ≤ 300s)           │
│      │       ├─► 4. Confidence Bounds ([0.0, 1.0], Finite, No NaN/Inf)                      │
│      │       ├─► 5. Position Size & Order Value Ceilings                                    │
│      │       ├─► 6. SHA-256 Signal Deduplication & Idempotency Filter                      │
│      │       ├─► 7. Opposing Signal Conflict Resolver (BUY vs SELL on same instrument)      │
│      │       ├─► 8. Consecutive Failure Threshold & Automated Quarantine                    │
│      │       └─► 9. AI Advisory Boundary (Advisory Only; Zero Live-Order Authority)         │
│      │                                                                                      │
│      ├─► StrategyDecision (APPROVED / REJECTED / CONFLICTED / DUPLICATE / QUARANTINED)       │
│      │                                                                                      │
│      └─► DOWNSTREAM GATES (Unconditionally Required — Never Bypassed):                      │
│              ├─► RiskEngine (Account capital, hard constraints, risk veto)                  │
│              ├─► ExecutionPreflightEngine (Exchange constraints, tick normalization)        │
│              ├─► LiveReadiness (Environmental check, data freshness)                        │
│              ├─► LiveArmingStore (Short-lived 5-min TTL operator arming)                     │
│              ├─► ManualOrderSafetyGate / ConfirmationStore (Two-stage token verification)   │
│              └─► Broker Execution Layer (Dhan API / Paper Simulator)                        │
│                                                                                             │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Core Architectural Components

### 2.1 Domain Schemas (`backend/domain/strategy_schemas.py`)
- **`StrategyStatus`**: `DRAFT`, `ACTIVE`, `PAUSED`, `DISABLED`, `QUARANTINED`.
- **`SignalDirection`**: `BUY`, `SELL`, `HOLD`.
- **`SignalSource`**: `RULE_BASED`, `TECHNICAL`, `FUNDAMENTAL`, `AI_ADVISORY`, `MANUAL`.
- **`GovernanceStatus`**: `PENDING`, `APPROVED`, `REJECTED`, `CONFLICTED`, `DUPLICATE`, `QUARANTINED`.
- **`StrategySignal`**: Pydantic model with strict validation rejecting NaN/Inf, invalid confidence ranges, negative quantities, unsupported exchanges, and stale timestamps. Includes `compute_fingerprint()` generating canonical SHA-256 hashes.
- **`StrategyDefinition`**: Configuration boundary defining allowed instruments, allowed exchanges, max position size, max order value, and risk constraints.
- **`StrategyDecision`**: Strongly-typed governance evaluation outcome containing decision ID, admissibility boolean, rejection reason/details, risk metadata, and signal fingerprint.
- **`StrategyConflictRecord`**: Audit trail record capturing opposing strategy signals on the same instrument.
- **`StrategyHealthMetrics`**: Operational statistics tracking signal throughput, acceptances, rejections, duplicates, conflicts, and quarantine history.

### 2.2 Strategy Registry (`backend/execution/strategy_registry.py`)
- **Thread-Safe & Deterministic**: Uses re-entrant locks (`threading.RLock`) for concurrent operations.
- **Explicit Lifecycle Management**: Provides `activate()`, `pause()`, `disable()`, `quarantine()`, and `recover()` methods.
- **Duplicate & Conflict Prevention**: Rejects duplicate registrations with conflicting parameters for the same version.
- **Quarantine Enforcement**: Quarantined strategies cannot be activated without explicit operator recovery.
- **Crash-Safe Persistence**: Saves strategy definitions into `PersistentStateStore` and appends mutations to `StateJournal`.

### 2.3 Strategy Governance Engine (`backend/execution/strategy_governance.py`)
- **17-Point Deterministic Evaluation**:
  1. Strategy registration check in `StrategyRegistry`.
  2. Strategy `ACTIVE` status check.
  3. Strategy version matching check.
  4. Allowed instrument whitelist check.
  5. Allowed exchange whitelist check.
  6. Signal timestamp freshness check (age $\le 1800\text{s}$).
  7. Market data timestamp freshness check (age $\le 300\text{s}$).
  8. Finite confidence score check ($0.0 \le \text{confidence} \le 1.0$).
  9. Valid signal direction check (`BUY`, `SELL`, `HOLD`).
  10. Maximum position size limit check.
  11. Maximum order value limit check.
  12. Kill switch engagement check.
  13. Signal deduplication check (SHA-256 fingerprint matching).
  14. Opposing signal conflict check (BUY vs SELL on same instrument within 300s window).
  15. Strategy quarantine status check.
  16. Consecutive failure threshold check (auto-quarantines after 5 consecutive rejections).
  17. Decision consistency and audit logging.
- **Conflict Management**: Opposing active signals on the same instrument within the conflict window are marked `CONFLICTED` and blocked from execution.
- **Auto-Quarantine**: Automatically transitions a strategy to `QUARANTINED` upon 5 consecutive rejections to protect system integrity.

### 2.4 REST API (`backend/application/strategy_routes.py`)
- `GET /api/strategy/list`: List all registered strategies with status filtering.
- `GET /api/strategy/{strategy_id}`: Retrieve strategy definition.
- `GET /api/strategy/{strategy_id}/health`: Get strategy throughput and health metrics.
- `POST /api/strategy/register`: Register new strategy definition.
- `POST /api/strategy/{strategy_id}/activate`: Activate strategy.
- `POST /api/strategy/{strategy_id}/pause`: Pause strategy.
- `POST /api/strategy/{strategy_id}/disable`: Disable strategy.
- `POST /api/strategy/{strategy_id}/quarantine`: Quarantine strategy with operational reason.
- `POST /api/strategy/{strategy_id}/recover`: Recover strategy from quarantine with operator notes.
- `POST /api/strategy/signal/evaluate`: Evaluate incoming signal against governance gates.
- `GET /api/strategy/conflicts`: List detected strategy conflicts.
- `GET /api/strategy/governance/status`: Operational health of registry and governance engine.

---

## 3. AI Advisory Boundary & Safety Rules

1. **Advisory Role Only**: Signals with `source = AI_ADVISORY` are treated as non-binding recommendations.
2. **Zero Direct Broker Authority**: AI outputs can never directly place broker orders, modify trading limits, or arm live trading.
3. **Ignored AI Flags**: Injected metadata such as `"approved=True"`, `"is_safe=True"`, or `"override_kill_switch=True"` are completely ignored by the governance engine.
4. **No Self-Recovery**: AI models cannot un-quarantine or self-recover a disabled or quarantined strategy.

---

## 4. Safety Invariants & Verification

- `LIVE_EXECUTION_ENABLED=false` remains default and fail-closed.
- ZERO real-money orders submitted during testing or development.
- Strategy governance approval does not bypass downstream `RiskEngine`, `ExecutionPreflightEngine`, `LiveArmingStore`, or `ManualOrderSafetyGate`.
- Kill switch is strictly authoritative and halts all strategy evaluation.
