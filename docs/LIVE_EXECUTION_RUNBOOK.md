# Live Execution Runbook (Operator Guide)

## Overview
This runbook provides step-by-step instructions for authorized human operators to conduct controlled real-money live trades on the AI Trading Desk / Trading OS with Dhan Broker.

> **CRITICAL RULE:** Autonomous or AI-initiated live trading is physically impossible in this architecture. Every single live order requires explicit human token generation, cryptographic parameter matching, and manual arming.

---

## Step 1: Pre-Flight Environment Checklist

Before activating live trading, verify all environment prerequisites:

1. **Verify Network & Connectivity:**
   - Stable internet connection.
   - Target broker: Dhan API v2 (`https://api.dhan.co`).
2. **Verify Static IP / Broker Whitelisting:**
   - Static IP configured in environment if required by Dhan API settings.
3. **Inspect Account Balance & Funds:**
   - Ensure sufficient unencumbered cash balance in Dhan equity ledger (minimum ₹5,000).
4. **Inspect Market Hours:**
   - NSE Equity Cash market hours: 09:15 to 15:30 IST on trading days.

---

## Step 2: Live Arming Session Activation

Arming creates a 5-minute time-to-live session for live trade operations:

```bash
# Call API to arm live execution
curl -X POST http://127.0.0.1:5000/api/live/arm \
  -H "Content-Type: application/json" \
  -d '{"acknowledgement": true, "duration_seconds": 300}'
```

*Note: Arming expires automatically in 300 seconds. Engaging the Emergency Kill Switch disarms immediately.*

---

## Step 3: Issue Human Operator Authorization Token

Issue a single-use token specifically bound to the planned order parameters:

```bash
curl -X POST http://127.0.0.1:5000/api/production/operator/token \
  -H "Content-Type: application/json" \
  -d '{
    "operator_id": "OPERATOR_AYUSH",
    "symbol": "TCS.NS",
    "side": "BUY",
    "quantity": 1,
    "price": 3500.0,
    "order_type": "LIMIT",
    "exchange_segment": "NSE",
    "product_type": "CNC",
    "ttl_seconds": 120,
    "source": "HUMAN_OPERATOR",
    "operator_notes": "First controlled production test order"
  }'
```

**Response Example:**
```json
{
  "token_id": "opauth-7a8f9c1b-...",
  "order_fingerprint": "a3b2c1...",
  "operator_id": "OPERATOR_AYUSH",
  "issued_at": "2026-09-02T10:00:00Z",
  "expires_at": "2026-09-02T10:02:00Z",
  "ttl_seconds": 120,
  "status": "ISSUED"
}
```

---

## Step 4: Execute Controlled Live Trade

Submit the order payload with the issued `operator_token_id`:

```bash
curl -X POST http://127.0.0.1:5000/api/production/execute \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "TCS.NS",
    "side": "BUY",
    "quantity": 1,
    "price": 3500.0,
    "order_type": "LIMIT",
    "exchange_segment": "NSE",
    "product_type": "CNC",
    "operator_token_id": "opauth-7a8f9c1b-..."
  }'
```

**Execution Flow:**
1. `LiveExecutionGate` verifies 11+ safety gates.
2. Operator token consumed and marked non-reusable.
3. Order submitted to Dhan API v2.
4. Immediate status query executed.
5. Order state transitions: `CREATED -> AUTHORIZED -> SUBMITTED -> ACKNOWLEDGED -> OPEN/FILLED`.
6. Record appended to immutable state journal and audit chain.

---

## Step 5: Post-Submission Verification & Reconciliation

1. **Query Order History:**
   ```bash
   curl -X GET http://127.0.0.1:5000/api/production/orders
   ```
2. **Trigger Broker Order Book Reconciliation:**
   ```bash
   curl -X POST http://127.0.0.1:5000/api/production/reconcile
   ```
3. **Verify Broker Account:**
   - Log into Dhan web portal / app to verify trade fill and position.

---

## Step 6: Emergency Operations & Kill Switch

If any unexpected behavior, network instability, or abnormal spread is observed:

### Emergency Kill Switch Activation:
```bash
curl -X POST http://127.0.0.1:5000/api/live/kill-switch/activate \
  -H "Content-Type: application/json" \
  -d '{"reason": "Manual operator emergency halt"}'
```

**Immediate Effects:**
- Live arming session immediately purged.
- All in-flight requests rejected.
- Live execution gate locked fail-closed.
- Audit event logged.
