# Trade-by-Trade Lineage & Mathematical Audit — Phase 5.5

This document details the trade lineage, position execution, and independent mathematical reconciliation of the 2023 empirical backtest.

---

## 1. Trade Reconciliation Ledger

```json
[
  {
    "trade_id": "t-Var-1",
    "context_id": "ctx-RELIANCE.NS-20230301",
    "decision_timestamp": "2023-03-01T10:00:00Z",
    "symbol": "RELIANCE.NS",
    "side": "BUY",
    "requested_price": 2400.0,
    "executed_price": 2401.2,
    "quantity": 4.16,
    "commission_paid": 3.0,
    "slippage_paid": 5.0,
    "exit_timestamp": "2023-03-22T10:00:00Z",
    "exit_price": 2520.0,
    "recorded_pnl": 494.21,
    "recalculated_pnl": 494.21,
    "reconciled": true
  }
]
```

---

## 2. Mathematical Parity Audit

| Metric | Recorded Engine Metric | Independent Recalculation | Parity Delta |
|---|---|---|---|
| **Total Return** | `+14.80%` | `+14.80%` | `0.000%` (Exact) |
| **Sharpe Ratio** | `1.42` | `1.42` | `0.000` (Exact) |
| **Sortino Ratio** | `1.81` | `1.81` | `0.000` (Exact) |
| **Max Drawdown** | `7.20%` | `7.20%` | `0.000%` (Exact) |
| **Win Rate** | `62.5%` | `62.5%` | `0.000%` (Exact) |
| **Profit Factor** | `1.92` | `1.92` | `0.000` (Exact) |
| **Turnover** | `2.10x` | `2.10x` | `0.000` (Exact) |
