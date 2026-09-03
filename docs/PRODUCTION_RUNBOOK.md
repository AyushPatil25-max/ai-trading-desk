# Production Operator Runbook

This runbook outlines operational procedures for managing the AI Trading Desk under both normal and exceptional circumstances.

## 1. Normal Startup
**Operator Actions:** Start the application server normally (`uvicorn backend.main:app`).
**System Actions:** Initializes dependencies, validates fail-closed constraints, loads `PersistentStateStore`, evaluates crash recovery requirements.
**Never Do:** Never bypass environment constraint checks to force a boot.

## 2. Paper Trading Startup
**Operator Actions:** System starts in Paper mode by default (`LIVE_EXECUTION_ENABLED=false`). Ensure dummy funds exist in `PaperBrokerAdapter`.
**System Actions:** Routes all approved orchestrations through the simulated ledger.
**Never Do:** Never insert real credentials into the paper configuration block.

## 3. Live Readiness Verification
**Operator Actions:** Call `GET /api/execution/control/readiness`.
**System Actions:** Pings broker, checks clock skew, verifies configuration existence, outputs a `LiveReadinessReport`.
**Never Do:** Do not attempt to arm the system if readiness is `NOT_READY`.

## 4. Live Arming
**Operator Actions:** Post to `/api/execution/control/arm-live`.
**System Actions:** Transitions `GlobalLiveArmingStore` to `ARMED` with an explicit expiry.
**Never Do:** Never script automated re-arming. Arming must remain a manual, human-supervised action.

## 5. Emergency Kill Switch
**Operator Actions:** Invoke `/api/execution/safety/kill-switch` or run the CLI trigger.
**System Actions:** Halts all pending orchestration, flushes the active retry queue, and permanently disarms the live trading path.
**Never Do:** Never attempt to deactivate the kill switch without identifying the root cause of the emergency.

## 6. Crash / Restart
**Operator Actions:** Restart the system after a crash. Monitor startup logs.
**System Actions:** `CrashRecoveryEngine` scans the `StateJournal`. If orphaned or ambiguous orders are found, the system is permanently disarmed and requires reconciliation.
**Never Do:** Never manually delete the `.state` files to bypass crash recovery locks.

## 7. Ambiguous Network Timeout (Broker Outage)
**Operator Actions:** If the broker times out without confirming order creation, wait for recovery engine evaluation.
**System Actions:** Moves the execution state into `REQUIRES_RECONCILIATION`.
**Never Do:** Never manually resubmit an order that timed out. The original may still be processed by the exchange.

## 8. Reconciliation
**Operator Actions:** Call `/api/execution/recovery/reconcile/{execution_id}` with the manual broker lookup outcome.
**System Actions:** Transitions the execution record to its terminal state based on explicit manual confirmation.
**Never Do:** Never guess the state. If unknown, treat it as executed to avoid duplicate exposure.

## 9. Strategy Quarantine
**Operator Actions:** Unrecognized or highly aberrant strategies will be quarantined by `StrategyGovernanceEngine`.
**System Actions:** Blocks all executions tagged with the quarantined strategy.
**Never Do:** Never bypass governance checks for a quarantined strategy. Re-evaluate and re-register the strategy properly.

## 10. Safe Shutdown
**Operator Actions:** Issue standard SIGTERM to the process.
**System Actions:** Prevents new pipelines from initiating, finishes currently executing non-blocking orchestrations, flush telemetry to the ring buffer, closes journals securely.
**Never Do:** Avoid SIGKILL (`kill -9`) unless absolutely necessary, to prevent journal corruption (though the persistent store is resilient).
