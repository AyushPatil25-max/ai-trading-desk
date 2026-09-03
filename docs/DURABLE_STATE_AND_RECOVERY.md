# Phase 28: Durable State & Crash-Recovery Foundation

## 1. Architecture Overview

Phase 28 establishes a deterministic, crash-safe, write-ahead persistent state layer for the AI-Trading-Desk execution engine. It ensures that critical operational state (order tracking, reconciliation history, recovery status, and account cache metadata) survives process crashes and restarts without compromising fail-closed security invariants or granting unauthorized trading capabilities.

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                       DURABLE STATE & CRASH RECOVERY FOUNDATION                             │
├─────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                             │
│  State Mutation Request (Order submission, status change, reconciliation run)               │
│      │                                                                                      │
│      ├─► 1. Recursive Secret Scrubbing (All API keys, tokens, passwords redacted)           │
│      │                                                                                      │
│      ├─► 2. Append to StateJournal (JSONL, monotonic sequence, SHA-256 hash chaining)       │
│      │                                                                                      │
│      ├─► 3. PersistentStateStore Commit Mutation                                             │
│      │       ├─► Check Idempotency Key (prevent duplicate mutations)                        │
│      │       ├─► Verify Monotonic Revision (reject stale revisions)                         │
│      │       ├─► Write to Temp File -> fsync() -> Atomic os.replace()                       │
│      │       └─► Replicate to execution_state.backup.json                                   │
│      │                                                                                      │
│      └─► 4. Emit Standardized Tamper-Evident Audit Events (STATE_MUTATION_COMMITTED, etc.)   │
│                                                                                             │
├─────────────────────────────────────────────────────────────────────────────────────────────┤
│  STARTUP CRASH RECOVERY SEQUENCE:                                                           │
│                                                                                             │
│  Application Startup                                                                        │
│      │                                                                                      │
│      ├─► Step 1: STATE_RECOVERY_STARTED Audit Event                                         │
│      ├─► Step 2: Load Persistent Snapshot & Verify SHA-256 Checksum (Backup fallback)       │
│      ├─► Step 3: Load StateJournal & Cryptographically Verify Full Hash Chain from Genesis  │
│      ├─► Step 4: Identify & Replay Committed Journal Mutations                              │
│      ├─► Step 5: Restore Order Tracker & Flag In-Flight as RECOVERY_REQUIRES_RECONCILIATION │
│      ├─► Step 6: Force Disarm Live Trading & Purge Transient Failure Recovery Loops         │
│      ├─► Step 7: Expose Recovery Diagnostics & Transition to OPERATIONAL (or BLOCKED)       │
│                                                                                             │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Core Components

### 2.1 `PersistentStateStore` (`backend/execution/persistent_state_store.py`)
- **Monotonic Revisioning**: Every mutation increments `revision`. Out-of-order or stale revisions raise `StaleRevisionError`.
- **Atomic Disk Commits**: Writes to a temp file on the same filesystem, flushes, syncs to disk via `os.fsync`, and atomically replaces the primary file using `os.replace`.
- **Dual-Layer Corruption Protection**: Verifies SHA-256 payload checksum on every load. Automatically falls back to `execution_state.backup.json` upon corruption.
- **Fail-Safe Integrity**: If both primary and backup files are corrupted, fails safely with a clean empty state, emits `STATE_CORRUPTION_DETECTED`, and never fabricates historical records.

### 2.2 `StateJournal` (`backend/execution/state_journal.py`)
- **Append-Only Write-Ahead Log**: Stored in `backend/data/execution_state/state_journal.jsonl`.
- **Cryptographic Hash Chaining**: Every record computes `record_hash = SHA256(canonical(data + prev_hash))`, chained from a verified genesis constant.
- **Tamper & Deletion Detection**: `verify_integrity()` validates sequence numbers, payload checksums, and hash continuity. Any detected tampering, gap, or truncated record immediately triggers a fail-closed response.
- **Deterministic Replay**: Missing committed journal mutations are safely replayed into the `PersistentStateStore` during startup.

### 2.3 `CrashRecoveryEngine` (`backend/execution/crash_recovery.py`)
- Coordinates startup state reconstruction.
- Restores historical order records into `InMemoryOrderTracker` so `is_duplicate()` remains active across restarts.
- Flags any previously in-flight orders (`PENDING_SUBMISSION`, `SUBMITTED`, `OPEN`) with status `RECOVERY_REQUIRES_RECONCILIATION`.
- Guarantees live trading authorization is strictly **DISARMED** upon startup.
- Emits audit events: `STATE_RECOVERY_STARTED`, `STATE_RECOVERY_COMPLETED`, `STATE_RECOVERY_FAILED`, `ORDER_STATE_RESTORED`, `ORDER_RECOVERY_REQUIRES_RECONCILIATION`.

---

## 3. Subsystem Integrations

| Subsystem | File Path | Phase 28 Behavior |
|---|---|---|
| **Order Tracker** | `backend/execution/order_tracker.py` | Order submissions, successes, status updates, and deletions are committed to `PersistentStateStore` and `StateJournal`. |
| **Reconciliation** | `backend/execution/reconciliation_service.py` | Loads durable order state before reconciliation, matches against Dhan order books, updates local state, and persists resolution. |
| **Failure Recovery** | `backend/execution/live_failure_recovery.py` | Transient retry loops are purged on restart. No blind automatic live retries after a crash. |
| **Live Arming** | `backend/execution/live_arming_store.py` | Armed state is strictly in-memory with TTL; **NEVER** restored as active after a restart. |
| **Broker REST API** | `backend/application/broker_routes.py` | `/api/broker/live/status` exposes `persistent_store`, `state_journal`, and `crash_recovery` status. `/api/broker/live/recovery/run` provides on-demand recovery testing. |

---

## 4. Safety Invariants & Security Boundaries

1. **Zero Real-Money Authority**: Persistence and crash recovery are strictly operational. They can never place orders or bypass live readiness.
2. **Fail-Closed Default**: `LIVE_EXECUTION_ENABLED=false` remains strictly enforced.
3. **Live Arming Does NOT Survive Restart**: A fresh operator arming action is always mandatory after process restart.
4. **No Blind Retries**: Orders in ambiguous or incomplete states are quarantined into `RECOVERY_REQUIRES_RECONCILIATION` until verified against Dhan's order book.
5. **Recursive Secret Scrubbing**: All passwords, API credentials, `dhan_access_token`, and confirmation tokens are stripped before writing to disk or journals.
6. **Kill Switch Authority**: Engaging the emergency kill switch immediately purges pending retry loops and disables execution.
