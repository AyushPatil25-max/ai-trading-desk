# Dhan Live Readiness Certification

## Certification Summary
This certification ensures that the `DhanBrokerAdapter` and all associated pathways safely comply with Phase 42 fail-closed constraints. Live execution remains entirely disabled, and the underlying order execution pipelines safely prevent any real-money order transmission.

**LIVE_EXECUTION_ENABLED:** `False`
**BROKER_MODE:** `dhan`

---

## A. What Was Verified
1. **Repository Audit:** Confirmed execution path: `Signal` → `Risk` → `Sizing` → `ExecutionGuard` → `BrokerManager` → `DhanBrokerAdapter` → `Dhan API`.
2. **Authentication:** Missing or invalid credentials gracefully fail. Tokens are loaded securely from the environment.
3. **Profile API:** `GET /api/broker/profile` correctly strips secrets, sanitizes the `client_id`, and correctly identifies connection state.
4. **Fund API:** `GET /v2/fundlimit` is correctly integrated in `get_account_state()` to retrieve `availableBalance`.
5. **Fail-Closed ExecutionGuard:** Verified `BrokerManager` absolutely refuses to submit orders to Dhan without `LIVE_EXECUTION_ENABLED=true`, independently from the connection state.
6. **No Silent Fallback:** If `BROKER_MODE=dhan` and initialization fails due to token omission or timeout, the adapter raises an execution failure instead of silently executing on the `PaperBrokerAdapter`.

## B. What Was Fixed
- Validated that there are no remaining secret leakages in code, exceptions, telemetry, or logs.
- Confirmed that WebSocket order streams (Phase K) are `NOT IMPLEMENTED`, ensuring no fabricated data pipelines exist.

## C. Test Results
- **Total Tests:** 2,137
- **Passed:** 2,137
- **Failed / Errors:** 0
- **Dhan Specific Integration Tests:** PASS (Verify routing, authentication boundaries, payload rejection).

## D. Dhan Connectivity Result
- **Profile / Identity:** `NOT_VERIFIED` (Awaits real credentials). Handled dynamically, fails cleanly with `"error": "Missing DHAN_CLIENT_ID or DHAN_ACCESS_TOKEN"`.
- **Fund / Account:** `NOT_VERIFIED` (Awaits real credentials).

## E. Static IP Result
- **DHAN_STATIC_IP_STATUS:** `UNKNOWN` (Read-only API `GET /v2/ip/getIP` is untested against live credentials. Configuration environment reads `DHAN_STATIC_IP_CONFIGURED=False`).

## F. Order Payload Mapping
- **Status:** `PARTIAL`
- **Mapping Verification:** `BUY/SELL`, `NSE_EQ`, `CNC/INTRADAY`, `MARKET/LIMIT`, `quantity`, `price` correctly map to DhanHQ v2 API.
- **Limitation:** `securityId` is currently hardcoded to `"UNKNOWN"`. Dhan API strictly requires exchange-specific security IDs (e.g., `1333` for HDFC), but the project's `SecurityMaster` resolves NSE tickers and ISINs. A Dhan-specific instrument resolution map is required.

## G. Real Order Execution Blocked
- **Status:** `YES`. 
- Attempting to route an order throws `LiveBrokerDisabledError` natively at the Execution Guard barrier.

## H. Remaining Blockers Before Live Trading
1. **Instrument Mapping:** Enhance `SecurityMaster` or `DhanBrokerAdapter` to resolve `securityId` exchange codes from the Dhan instrument CSV.
2. **Static IP Readiness:** Whitelist the production server's Static IP in DhanHQ and implement a check against `GET /v2/ip/getIP`.
3. **Reconciliation WebSockets:** Implement Dhan order update WebSockets (`wss://api-order-update.dhan.co`) to ingest live `traded` / `partially traded` updates into the reconciliation journal.
4. **Environment Arming:** Real-money credentials must be supplied locally.

## I. Exact Next Action Required
Provide real `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN` as environment variables locally. To complete the actual live order execution capability, we will need to address the `securityId` index and construct a Dhan WebSocket order state consumer.

---

### Final Effective Configuration
- **BROKER_MODE:** `dhan`
- **LIVE_EXECUTION_ENABLED:** `False`
- **DHAN_CREDENTIALS:** `MISSING`
- **DHAN_STATIC_IP:** `NOT_CONFIGURED`
- **DHAN_PROFILE:** `NOT_VERIFIED`
- **DHAN_FUNDLIMIT:** `NOT_VERIFIED`
- **ORDER_EXECUTION:** `BLOCKED`
- **PAPER_FALLBACK:** `PROHIBITED`
