# Execution Risk Matrix — Phase 5.1

This matrix defines all deterministic execution risk controls, rejection conditions, thresholds, and fallback actions.

---

## 1. Risk Control Table

| Risk Check | Trigger Condition | Severity | Action | Rejection Reason |
|---|---|---|---|---|
| **Kill Switch** | `KillSwitch.is_active() == True` | CRITICAL | Block Order | `KILL_SWITCH` |
| **Duplicate Order** | Same `(symbol, side, qty, context_id, run_id)` already executed | CRITICAL | Block Order | `DUPLICATE_ORDER` |
| **Risk Veto** | `decision.state == RISK_VETO` or `risk_veto_triggered` | CRITICAL | Block Order | `RISK_VETO` |
| **Data Quality Veto** | `decision.state == DATA_QUALITY_VETO` or `quality_status == CRITICAL_FAILURE` | HIGH | Block Order | `DATA_QUALITY` |
| **Stale Context** | `(now - data_timestamp) > maximum_context_age_seconds` (300s) | HIGH | Revalidation Required | `STALE_DATA` |
| **Insufficient Evidence** | `decision.state == INSUFFICIENT_EVIDENCE` | HIGH | Block Order | `INSUFFICIENT_EVIDENCE` |
| **Committee Non-Approve** | `decision.state in [HOLD, REJECT]` | HIGH | Block Order | `COMMITTEE_REJECT` |
| **Low Confidence** | `decision.confidence < minimum_confidence` (0.5) | MEDIUM | Block Order | `RISK_LIMIT` |
| **Daily Loss Limit** | `daily_realized_pnl < -max_daily_loss` (₹10,000) | HIGH | Halt New Buys | `DAILY_LOSS_LIMIT` |
| **Max Order Value** | `quantity * price > max_order_value` (₹25,000) | MEDIUM | Block Order | `RISK_LIMIT` |
| **Max Position Value** | `pos_val + order_val > max_position_value` (₹50,000) | MEDIUM | Block Order | `POSITION_LIMIT` |
| **Single Symbol Exposure** | `(pos_val + order_val) / equity > max_single_symbol_exposure` (30%) | MEDIUM | Block Order | `POSITION_LIMIT` |
| **Total Exposure** | `(total_market_val + order_val) / equity > max_portfolio_exposure` (80%) | MEDIUM | Block Order | `RISK_LIMIT` |
| **Insufficient Cash** | `quantity * price > available_cash` | HIGH | Block Order | `INSUFFICIENT_CASH` |
| **Insufficient Position** | `sell_quantity > owned_quantity` | HIGH | Block Order | `INSUFFICIENT_POSITION` |
| **Invalid Price/Quantity** | `price <= 0` or `quantity <= 0` | HIGH | Block Order | `INVALID_PRICE` / `INVALID_QUANTITY` |

---

## 2. Configuration Reference

All thresholds are centralized in `backend/config/execution_risk_config.json`:

```json
{
    "risk_limits": {
        "max_position_value": 50000.0,
        "max_order_value": 25000.0,
        "max_portfolio_exposure": 0.8,
        "max_daily_loss": 10000.0,
        "max_single_symbol_exposure": 0.3,
        "max_orders_per_symbol": 5,
        "minimum_confidence": 0.5,
        "maximum_context_age_seconds": 300.0
    },
    "portfolio": {
        "initial_cash": 100000.0,
        "commission_rate": 0.0003
    },
    "safety": {
        "kill_switch_enabled": false,
        "allow_short_selling": false,
        "enforce_provenance": true
    }
}
```
