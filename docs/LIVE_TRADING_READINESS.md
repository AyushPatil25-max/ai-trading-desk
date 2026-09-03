# Live Trading Readiness & Controlled Activation Architecture

**Phase 26 Specification & Operational Guide**

> [!IMPORTANT]
> **FAIL-CLOSED SAFETY INVARIANT:**
> `LIVE_EXECUTION_ENABLED=false` by default in all environments. Real-money live trading remains permanently locked until explicit multi-stage operator authorization is verified.

---

## 1. Architectural Overview

The **Live Trading Readiness & Controlled Activation** layer introduces deterministic, multi-tier validation before any real-money transaction can reach the Dhan v2 execution endpoint.

```
                    ┌─────────────────────────┐
                    │    Trading Dashboard    │
                    └────────────┬────────────┘
                                 │
                         1. Manual Order
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │      Order Preview      │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │    Safety Gate #1       │  (Structural, Quantity, Price, Symbol)
                    └────────────┬────────────┘
                                 │
                         2. Confirmation Token
                            (256-bit, 2m TTL,
                             SHA-256 Fingerprint)
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │    Safety Gate #2       │  (Re-validation + Kill Switch Check)
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │   Live Readiness Gate   │  (17+ Subsystem & Connectivity Checks)
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │   Live Armed State      │  (Explicit User Ack + Short-Lived TTL)
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │   Dhan Broker Adapter   │  (v2 Payload Construction & Sanitization)
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │      Dhan v2 API        │
                    └─────────────────────────┘
```

---

## 2. Readiness Evaluation Checks (17+ Deterministic Rules)

The `LiveTradingReadinessEngine` (`backend/execution/live_readiness.py`) continuously evaluates four subsystem categories without placing orders:

### Category A: Safety Subsystem
1. **Kill Switch Verification (`KILL_SWITCH_ACTIVE` / `KILL_SWITCH_CLEAR`):**
   - Immediate emergency stop. If active, returns `BLOCKED` status and force-disarms any active session.
2. **Safety Engine Availability (`SAFETY_ENGINE_AVAILABLE` / `SAFETY_ENGINE_UNAVAILABLE`):**
   - Verifies `ManualOrderSafetyGate` is online.
3. **Confirmation Store Availability (`CONFIRMATION_STORE_AVAILABLE` / `CONFIRMATION_STORE_UNAVAILABLE`):**
   - Verifies in-memory token store is operational.
4. **Audit Chain Availability (`AUDIT_CHAIN_AVAILABLE` / `AUDIT_CHAIN_UNAVAILABLE`):**
   - Verifies cryptographic SHA-256 event log is operational.

### Category B: Dhan Broker Connectivity & Account State
5. **Dhan Integration Flag (`DHAN_ENABLED` / `DHAN_DISABLED`):**
   - Validates environment toggle.
6. **Dhan Client ID (`DHAN_CLIENT_ID_CONFIGURED` / `DHAN_CLIENT_ID_MISSING`):**
   - Validates client ID presence.
7. **Dhan Access Token (`DHAN_ACCESS_TOKEN_CONFIGURED` / `DHAN_ACCESS_TOKEN_MISSING`):**
   - Validates token presence while keeping token secrets masked.
8. **Dhan API Connectivity & Authentication (`DHAN_CONNECTED`, `DHAN_AUTH_FAILED`, `DHAN_UNAVAILABLE`):**
   - Verifies live handshake via Dhan `/profile` endpoint.
9. **Broker Account Synchronization (`ACCOUNT_AVAILABLE` / `ACCOUNT_UNAVAILABLE`):**
   - Confirms profile, funds, and portfolio state can be retrieved.
10. **Buying Power Availability (`BUYING_POWER_AVAILABLE` / `BUYING_POWER_UNAVAILABLE`):**
    - Confirms account has positive buying power ($>0$).

### Category C: Market Session & Data Freshness
11. **Market Session State (`MARKET_SESSION_OPEN`, `MARKET_SESSION_PRE_OPEN`, `MARKET_SESSION_CLOSED`, `MARKET_SESSION_UNKNOWN`):**
    - Indian Equity Market (IST = UTC + 5:30): Monday–Friday, 09:15 to 15:30 IST.
    - Fails closed for market orders outside trading hours or on holidays/weekends.
12. **Market Data Freshness Gate (`MARKET_DATA_FRESH` / `MARKET_DATA_STALE`):**
    - Ensures market prices are within the 300-second freshness threshold.

### Category D: Execution & Mode Isolation
13. **Live Execution Flag (`LIVE_EXECUTION_FLAG_ENABLED` / `LIVE_EXECUTION_FLAG_DISABLED`):**
    - Checks `LIVE_EXECUTION_ENABLED=true` in environment.
14. **Broker Adapter Availability (`BROKER_ADAPTER_AVAILABLE` / `BROKER_ADAPTER_UNAVAILABLE`):**
    - Verifies `DhanBrokerAdapter` instance.
15. **Paper / Live Isolation (`MODE_ISOLATED`):**
    - Strict deterministic routing isolation. Paper orders cannot reach live APIs; live orders cannot silently drop to paper.
16. **Live Trading Armed State (`ARMED_STATE_ACTIVE` / `ARMED_STATE_INACTIVE`):**
    - Verifies active temporary operator authorization.

---

## 3. Controlled Live Activation Workflow

Live trading cannot be enabled by toggling a flag or sending a raw order. It requires an explicit activation workflow:

```
[1. Operator Requests Audit] ──> GET /api/broker/live/readiness
                                       │
                                       ▼ (All 17 Checks PASS)
[2. Operator Opens Arm Modal] ──> Warning & Risk Acknowledgment
                                       │
                                       ▼ (Explicit Checkbox: true)
[3. Operator Arms Live Session] ──> POST /api/broker/live/arm
                                       │ (Generates 5-min TTL Session)
                                       ▼
[4. Live Trading is ARMED] ─────> Visual Countdown Timer in UI
                                       │
                                       ▼
[5. Manual Order Submission] ───> Preview ──> Token ──> Confirm
                                       │
                                       ▼ (Checks: Armed + Ready + Valid Token)
[6. Real Order Placed to Dhan] ─> POST /orders
```

---

## 4. Armed State Lifecycle & Disarm Triggers

| Trigger | Action | Resulting State |
|---------|--------|-----------------|
| **Explicit Arm Request** | `POST /api/broker/live/arm` (with ack=true) | **ARMED** (300s TTL) |
| **TTL Expiration** | 300 seconds elapsed | **DISARMED** (Auto-expired) |
| **Manual Disarm** | `POST /api/broker/live/disarm` | **DISARMED** (Immediate) |
| **Emergency Kill Switch** | `KillSwitch.activate()` | **BLOCKED & DISARMED** |
| **Dhan Disconnect / Auth Error** | Connectivity lost during readiness poll | **DISARMED** |

---

## 5. Paper vs Live Isolation

- **Paper Trading:** Routes through `PaperBrokerAdapter` to in-memory order books and simulated market fills. Never invokes `DhanHTTPClient.request("/orders")`.
- **Live Trading:** Routes through `DhanBrokerAdapter` to `https://api.dhan.co/v2/orders`. Only active when:
  1. `LIVE_EXECUTION_ENABLED=true`
  2. `is_currently_armed=True`
  3. `is_ready_for_order=True`
  4. Valid, unexpired single-use confirmation token presented.

---

## 6. AI Agent Boundary

- **AI Agents / LLMs:** Strictly observational. Allowed to analyze data, compute factor scores, detect IPO anomalies, and propose ideas.
- **AI Agents CANNOT:**
  - Arm live trading.
  - Generate confirmation tokens.
  - Disable kill switches.
  - Bypass safety gates.
  - Place live orders.

---

## 7. Cryptographic Tamper-Evident Audit Events

All live readiness and arming events are immutably logged with sanitized payloads:

- `LIVE_READINESS_CHECKED`
- `LIVE_READINESS_FAILED`
- `LIVE_TRADING_ARMED`
- `LIVE_TRADING_DISARMED`
- `LIVE_ORDER_BLOCKED`
- `BROKER_ACCOUNT_SYNCED`
