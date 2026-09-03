# AI-Trading-Desk: Distributed Recovery & Failover Runbook

## 1. Failure Modes & Automated Responses

| Failure Mode | Detection Point | Automated Safe State | Recovery Action |
|---|---|---|---|
| **Process Crash During Write** | `PersistentStateStore._load_from_disk` | Temp file ignored; latest atomic replace preserved | Replay unapplied records from `StateJournal` |
| **Corrupted State Checksum** | SHA-256 mismatch in `latest_state.json` | `StateCorruptionError` raised; fails closed | Restore from last verified `StateSnapshot` |
| **Journal Chain Disruption** | Hash mismatch in `StateJournal.verify_integrity` | Replay halts; audit event emitted | Reconcile uncommitted transactions |
| **Worker Lease Expiration** | `WorkerLease.is_expired()` | Worker halts paper ingestion on symbol | Renew lease or allow safe takeover |
| **Split-Brain Ownership** | Contending node requests active lease | `EXECUTION_QUARANTINED` emitted; partition isolated | Run 14-Step Recovery Verification |
| **Accounting Balance Divergence** | `StateConflictResolver.detect_accounting_conflict` | Conflicting partition quarantined | Verify audit ledger and reconstruct balances |

---

## 2. Triggering 14-Step Recovery

To trigger full deterministic recovery verification:
```http
POST /api/distributed/recovery/verify
```

Expected Response:
```json
{
  "status": "RECOVERED",
  "steps_completed": 14,
  "total_steps": 14,
  "is_safe_for_execution": true,
  "last_valid_revision": 42
}
```

If any step fails, `is_safe_for_execution` is `false`, and `blockers` lists the root cause. Do NOT unquarantine partitions until blockers are resolved.

---

## 3. Manual Partition Quarantine & Unquarantine

### Quarantining a Suspect Partition
```http
POST /api/distributed/workers/TCS.NS/quarantine
Content-Type: application/json

{"reason": "Manual operator intervention due to suspected data divergence"}
```

### Checking Quarantined Partitions
```http
GET /api/distributed/conflicts
```

### Unquarantining Post-Recovery
Once the 14-step recovery verification report is `RECOVERED` and `is_safe_for_execution: true`, partitions can be safely resumed via the dashboard or API.
