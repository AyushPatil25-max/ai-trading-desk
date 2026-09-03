# Phase 29: Strategy Governance Operational Runbook

## 1. Routine Governance Operations

### 1.1 Inspecting Active Champion & Challengers
```bash
# Query active champion details
curl -s http://127.0.0.1:5000/api/governance/champion

# Query list of active challengers
curl -s http://127.0.0.1:5000/api/governance/challengers

# Query overall governance status and state distribution
curl -s http://127.0.0.1:5000/api/governance/status
```

### 1.2 Registering a New Strategy Version
```bash
curl -X POST http://127.0.0.1:5000/api/governance/strategies \
  -H "Content-Type: application/json" \
  -d '{
    "name": "TrendMomentumAlpha",
    "version": "1.2.0",
    "description": "Enhanced multi-timeframe trend momentum with ATR trailing stop",
    "parameters": {
      "lookback_period": 20,
      "atr_multiplier": 2.5,
      "momentum_threshold": 0.03
    },
    "tags": ["momentum", "trend", "nse"]
  }'
```

---

## 2. Strategy Promotion Workflow

### 2.1 Transitioning Candidate to Backtesting & Validated
```bash
# Move from CANDIDATE to BACKTESTING
curl -X POST http://127.0.0.1:5000/api/governance/strategies/strat-12345678/transition \
  -H "Content-Type: application/json" \
  -d '{"target_state": "BACKTESTING", "reason": "Initiating historical walk-forward backtest"}'

# Move from BACKTESTING to VALIDATED
curl -X POST http://127.0.0.1:5000/api/governance/strategies/strat-12345678/transition \
  -H "Content-Type: application/json" \
  -d '{"target_state": "VALIDATED", "reason": "Passed walk-forward and Monte Carlo robustness checks"}'

# Move from VALIDATED to CHALLENGER
curl -X POST http://127.0.0.1:5000/api/governance/strategies/strat-12345678/transition \
  -H "Content-Type: application/json" \
  -d '{"target_state": "CHALLENGER", "reason": "Qualified for head-to-head comparison against Champion"}'
```

### 2.2 Running Head-to-Head 12-Dimension Comparison
```bash
curl -X POST http://127.0.0.1:5000/api/governance/compare \
  -H "Content-Type: application/json" \
  -d '{
    "champion_id": "strat-champion-01",
    "challenger_id": "strat-12345678"
  }'
```

### 2.3 Evaluating Promotion Gates
```bash
curl -X POST http://127.0.0.1:5000/api/governance/gates/evaluate \
  -H "Content-Type: application/json" \
  -d '{"challenger_id": "strat-12345678"}'
```

### 2.4 Promoting Challenger to Champion
```bash
curl -X POST http://127.0.0.1:5000/api/governance/promote \
  -H "Content-Type: application/json" \
  -d '{
    "challenger_id": "strat-12345678",
    "rationale": "Passed all conservative statistical promotion gates with +12.4% Sharpe improvement"
  }'
```

---

## 3. Emergency & Rollback Procedures

### 3.1 Triggering Immediate Manual Rollback
```bash
curl -X POST http://127.0.0.1:5000/api/governance/rollback \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "MANUAL",
    "details": "Operator-initiated safety rollback due to abnormal market volatility"
  }'
```

### 3.2 Automated Rollback Diagnostic Verification
1. Inspect the last decision record:
   ```bash
   curl -s http://127.0.0.1:5000/api/governance/decisions?limit=5
   ```
2. Verify that the previous Champion state is `ROLLED_BACK`.
3. Check the audit chain for `STRATEGY_ROLLBACK` event:
   ```bash
   curl -s http://127.0.0.1:5000/api/observability/audit/verify
   ```

---

## 4. Policy Configuration Management

```bash
# Retrieve current policy
curl -s http://127.0.0.1:5000/api/governance/policy

# Update policy thresholds
curl -X PUT http://127.0.0.1:5000/api/governance/policy \
  -H "Content-Type: application/json" \
  -d '{
    "min_trade_count": 50,
    "min_sharpe_improvement_pct": 8.0,
    "max_drawdown_tolerance_pct": 15.0,
    "max_relative_drawdown_increase_pct": 5.0,
    "min_win_rate_pct": 45.0,
    "min_profit_factor": 1.2,
    "require_out_of_sample": true,
    "require_forward_validation": true,
    "confidence_level_pct": 95.0,
    "rollback_max_drawdown_pct": 20.0,
    "rollback_drift_threshold": 0.5,
    "champion_protection_lock": true
  }'
```
