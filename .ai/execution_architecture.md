# Execution Architecture — Complete Evolution (Phases 1–42)

> **PRODUCTION ACTIVATION STATE (PHASE 42 COMPLETE):**  
> The Trading OS includes both hardened Paper Trading simulation and strictly gated, controlled Live Broker execution (Dhan v2 API).  
> **Safety Invariants:** Live execution is disabled by default (`LIVE_EXECUTION_ENABLED=False`). All live orders require deterministic human operator authorization (`OperatorAuthorizationToken`), multi-stage gating (`LiveExecutionGate`), hard first-trade limits (Qty=1, MaxValue=₹5,000, CNC Equity only, Max 1/day), and complete audit logging. AI is strictly advisory with zero live execution authority.

---

## 1. High-Level Flow

```
+---------------------------+
|    InvestmentCommittee    |  (Phase 4.3)
|  produces InvestmentDecision|
+-------------+-------------+
              |
              v
+-------------+-------------+
|   ExecutionSafetyEngine   |  (Phase 5.1)
| - Kill Switch Check       |
| - Duplicate Check         |
| - Order Request Creation  |
+-------------+-------------+
              |
              v
+-------------+-------------+
|      OrderValidator       |
| - Risk Limits             |
| - Data Freshness (PIT)    |
| - Cash / Position Check   |
| - Decision & Veto Check   |
+-------------+-------------+
              | (ALLOWED)
              v
+-------------+-------------+
|        PaperBroker        |
| - Deterministic Fill      |
| - Commission Calculation  |
| - Order ID & Status       |
+------+--------------+-----+
       |              |
       v              v
+------+-----+  +-----+------+
|PaperPortfolio| |ExecutionAudit|
| Cash, PnL, | | Immutable  |
| Positions  | | Audit Trail|
+------------+ +------------+
```

---

## 2. Core Architectural Components

### 1. `BrokerInterface` (`backend/execution/broker.py`)
Abstract base class defining the contract for brokers. Decouples the trading desk domain logic from broker implementations:
- `submit_order(order: OrderRequest) -> ExecutionResult`
- `cancel_order(order_id: str) -> bool`
- `get_order_status(order_id: str) -> Optional[OrderStatus]`
- `get_positions() -> Dict[str, Position]`
- `get_account_state() -> PortfolioState`

### 2. `ExecutionSafetyEngine` (`backend/execution/safety_engine.py`)
Deterministic coordinator for pre-trade safety:
- **Kill Switch**: Emergency halt mechanism. When active, all incoming orders are blocked unconditionally.
- **Duplicate Tracker**: Hash-based filter `(symbol, side, quantity, context_id, run_id)` preventing duplicate fills.
- **Decision Converter**: Deterministically translates `APPROVE` decisions from the Investment Committee into `OrderRequest` models with integer quantity sizing. Non-APPROVE states (`HOLD`, `REJECT`, `RISK_VETO`, `DATA_QUALITY_VETO`, `INSUFFICIENT_EVIDENCE`) produce no orders.

### 3. `OrderValidator` (`backend/execution/order_validator.py`)
18 distinct deterministic checks executing in sequential priority:
1. Symbol validation
2. Quantity and price validity (> 0)
3. Context ID and provenance consistency
4. Investment Committee decision state validation
5. Minimum confidence threshold check
6. MarketContext data quality check
7. Data freshness / Point-in-time staleness check
8. Daily loss limit check
9. Maximum order value check
10. Maximum position value check
11. Single symbol exposure limit check
12. Portfolio exposure limit check
13. Cash sufficiency for BUY orders
14. Position sufficiency for SELL orders (long-only safety)

### 4. `PaperBroker` (`backend/execution/paper_broker.py`)
Pure-Python in-memory simulation engine:
- Never makes external network calls.
- Executes fills deterministically at the order price with simulated exchange commission (default 0.03%).
- Applies updates to `PaperPortfolio`.
- Maintains order status dictionary.

### 5. `PaperPortfolio` (`backend/execution/portfolio.py`)
Deterministic accounting of:
- `cash`, `available_cash`
- `positions` (symbol, quantity, weighted average cost basis, market value, unrealized P&L, realized P&L)
- `total_market_value`, `total_equity`, `total_exposure`
- `daily_realized_pnl`

### 6. `ExecutionAuditManager` (`backend/execution/audit.py`)
Maintains an immutable execution event log storing:
- `audit_id`, `order_id`, `context_id`, `run_id`
- Full validation decision and checks breakdown
- Fill status and cost details
- Kill switch state at execution time

---

## 3. Strict LLM Boundaries

- The LLM **never** creates, modifies, or submits orders directly.
- The LLM qualitative thesis cannot override the deterministic decision state or risk limits.
- Order quantities and prices are computed exclusively by Python arithmetic based on portfolio equity and recommended sizing percentages.
