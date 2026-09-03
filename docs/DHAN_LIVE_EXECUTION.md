# Dhan Live Broker Integration Specification

## 1. Overview
The Dhan Broker Integration (`backend/adapters/dhan_adapter.py`) connects the Trading OS to Dhan's v2 REST and WebSocket APIs.

All communication is strictly governed by:
- Fail-closed execution policies.
- Order fingerprint binding and idempotency.
- Exponential backoff retry with order book reconciliation before any retry.
- Automatic secret masking across all diagnostic logs.

---

## 2. API Endpoints & Payload Mapping

### Base URL:
- Production: `https://api.dhan.co`
- Environment Config: `DHAN_API_BASE_URL`

### Headers:
```http
access-token: ***REDACTED***
client-id: ***REDACTED***
Content-Type: application/json
Accept: application/json
```

### Order Placement Payload (`POST /orders`):
```json
{
  "dhanClientId": "1100123456",
  "correlationId": "req-TCS-1725300000",
  "transactionType": "BUY",
  "exchangeSegment": "NSE_EQ",
  "productType": "CNC",
  "orderType": "LIMIT",
  "validity": "DAY",
  "tradingSymbol": "TCS",
  "securityId": "11536",
  "quantity": 1,
  "disclosedQuantity": 0,
  "price": 3500.0,
  "triggerPrice": 0.0,
  "afterMarketOrder": false,
  "amoTime": "OPEN",
  "boProfitValue": 0.0,
  "boStopLossValue": 0.0
}
```

---

## 3. Status Normalization Matrix

Raw responses from Dhan API are mapped to normalized platform status enums:

| Dhan Raw Status | Normalized Status | Platform State |
|---|---|---|
| `TRANSIT` | `SUBMITTED` | In-Flight with Broker |
| `PENDING` | `PENDING` | Acknowledged by Exchange |
| `OPEN` | `OPEN` | Active in Exchange Order Book |
| `TRADED` / `FILLED` | `FILLED` | Completely Executed |
| `PART_TRADED` | `PARTIALLY_FILLED` | Partial Fill Recorded |
| `REJECTED` | `REJECTED` | Rejected (Terminal) |
| `CANCELLED` | `CANCELLED` | Cancelled by User/System (Terminal) |
| `EXPIRED` | `CANCELLED` | Expired at End-of-Day |

---

## 4. Failure Recovery & Reconciliation Protocol

1. **Transient Network Timeout:**
   - If Dhan API returns a timeout or connection reset during `/orders`, the adapter enters `LiveFailureRecoveryEngine`.
   - **Crucial Rule:** The adapter does **NOT** blindly re-submit the order.
   - It first queries `GET /orders` to check if the correlation ID or order fingerprint was already accepted into Dhan's order book.
   - If found: Synchronizes state to `SUBMITTED` / `OPEN`.
   - If not found: Allows safe controlled retry within max retry count (2 attempts).
2. **Permanent Rejection:**
   - Rejections (insufficient margin, invalid price tick, outside circuit limits) are marked terminal `REJECTED` and will not be retried.
3. **Reconciliation Service (`backend/execution/reconciliation_service.py`):**
   - Periodic and on-demand synchronization comparing local state journal records against broker order book.
