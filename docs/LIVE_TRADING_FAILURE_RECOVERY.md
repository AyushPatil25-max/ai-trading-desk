# Phase 27: Live Trading Operational Verification & Failure Recovery Architecture

## Overview

Phase 27 establishes the operational resilience, failure recovery, idempotency protection, and authoritative reconciliation subsystem for live broker operations in the AI Trading Desk Trading OS.

---

## 1. Core Safety Principles

1. **Transient-Only Retries**: Only explicitly transient network and gateway failures (`URLError`, `TimeoutError`, `ConnectionResetError`, `DHAN_UNAVAILABLE`, `502`, `503`, `504`) may be retried.
2. **Permanent Error Fast-Rejection**: Authentication errors (`DHAN_AUTH_FAILED`, `401`, `403`), safety gate rejections, validation errors, duplicate errors, and client errors (`400`, `422`) immediately fail closed with zero retries.
3. **Pre-Retry Broker Reconciliation**: When network ambiguity or timeout occurs during order submission, the system verifies Dhan's order book by correlation ID before attempting resubmission. If the broker already received the order, it is treated as accepted rather than resubmitted, eliminating duplicate real-money orders.
4. **In-Memory Duplicate Tracking**: Strict fingerprint-to-order-ID tracking rejects duplicate order submissions before invoking broker adapters.
5. **Emergency Kill Switch Purge**: Activating `KillSwitch` halts all active retry loops, purges the in-memory order tracker, immediately force-disarms active live sessions, and emits `KILL_SWITCH_RECOVERY`.
6. **Authoritative Order Book Reconciliation**: `ReconciliationService` aligns local order states with Dhan order books without placing automated replacement orders.
7. **Read-Only Account Synchronization**: `AccountSyncService` caches balances and positions for fast UI and pre-flight evaluation without granting live execution authorization on its own.
8. **Fail-Closed Default**: `LIVE_EXECUTION_ENABLED=false` remains strictly enforced.

---

## 2. Multi-Stage Order Submission Pipeline

```
  AI / LLM Analysis (Observational Support Only)
      │
      ▼
  Deterministic Execution Boundary (Zero Direct AI Execution Authority)
      │
      ▼
  Phase 24: ManualOrderSafetyGate #1 (Structural, Risk Limits, Sizing, Price)
      │
      ▼
  Phase 24: ConfirmationStore (Cryptographic Single-Use 2m TTL Token Generation)
      │
      ▼
  Phase 26: LiveTradingReadinessEngine (17+ Subsystem Deterministic Health Checks)
      │
      ▼
  Phase 26: LiveArmingStore (Explicit Operator Risk Acknowledgement & 5m TTL Arming)
      │
      ▼
  Phase 24: ManualOrderSafetyGate #2 (Live-Enabled Requirement & Buying Power Re-Check)
      │
      ▼
  Phase 27: InMemoryOrderTracker (Fingerprint-Based Duplicate Detection)
      │
      ▼
  Phase 27: LiveFailureRecoveryEngine (Transient-Only Retry with Configurable Backoff)
      │
      ├─► Pre-Retry Broker Reconciliation (Authoritative Dhan Order Book Correlation Check)
      │
      ▼
  Authoritative Broker Boundary (Dhan v2 REST API - Fail-Closed Default)
      │
      ├─► Phase 27: Periodic ReconciliationService (Authoritative State Alignment)
      │
      ├─► Phase 27: AccountSyncService (Read-Only Balances & Positions Cache)
      │
      └─► Phase 27: KillSwitch Recovery Hook (Purges Pending Retries, Clears Tracker & Arms)
```

---

## 3. Configuration Reference

| Parameter | Environment Variable | Default | Bounds | Description |
|---|---|---|---|---|
| Max Retries | `LIVE_RETRY_MAX` | `3` | `[0, 10]` | Maximum retry attempts for transient broker errors |
| Retry Backoff | `LIVE_RETRY_BACKOFF` | `5.0` | `[0.0, 60.0]` | Delay in seconds between retry attempts |
| Reconciliation Interval | `RECONCILIATION_INTERVAL` | `60` | `[1, 3600]` | Interval in seconds for order book reconciliation |
| Account Sync Interval | `ACCOUNT_SYNC_INTERVAL` | `60` | `[1, 3600]` | Interval in seconds for account balance cache updates |

---

## 4. Tamper-Evident Audit Event Catalog

The following immutable events are emitted to `global_audit_chain`:

- `ORDER_RETRY_ATTEMPTED`: Logged on each transient retry attempt with attempt counter.
- `ORDER_RETRY_SUCCEEDED`: Logged when an order succeeds on a retry attempt or pre-retry reconciliation.
- `ORDER_RETRY_EXCEEDED`: Logged when max retries are exhausted without broker acceptance.
- `ORDER_DUPLICATE_DETECTED`: Logged when a duplicate order fingerprint is rejected.
- `KILL_SWITCH_RECOVERY`: Logged on emergency kill switch engagement and state purge.
- `RECONCILIATION_RUN`: Logged on completion of each order book reconciliation cycle.
- `ACCOUNT_SYNC`: Logged on account balance/position synchronization with sanitized metrics.
