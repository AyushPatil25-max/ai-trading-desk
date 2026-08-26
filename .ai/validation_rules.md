# Strategy Validation Rules — Phase 5.4

This document defines the strict chronological validation rules, out-of-sample partitioning, and scorecard metrics for the AI Trading Desk.

---

## 1. Out-of-Sample Window Partitioning

1. **Chronological Preservation:** Financial market data must never be split randomly. Slices must follow time forward:
   $$\text{Train Start} < \text{Train End} \le \text{Val Start} < \text{Val End} \le \text{Test Start} < \text{Test End}$$
2. **Isolation:** No hyperparameter tuning or candidate ranking threshold adjustments may use data from the Test window.
3. **Rolling Step:** Windows roll forward by `step_days` (default 252 trading days / 1 year).

---

## 2. Validation Scorecard Formulation

The `ValidationScorecard` is computed deterministically across 6 dimensions:

| Dimension | Weight | Primary Factors | Pass Threshold |
|---|---|---|---|
| **Predictive Quality** | 20% | Win Rate ($>50\%$), Profit Factor ($>1.5$) | $\ge 50.0$ |
| **Risk-Adjusted Performance** | 20% | Sharpe Ratio ($>1.0$), Sortino Ratio ($>1.2$) | $\ge 50.0$ |
| **Drawdown Control** | 15% | Maximum Drawdown ($<15\%$) | $\ge 50.0$ |
| **Consistency** | 15% | Positive Out-of-Sample Returns across windows | $\ge 50.0$ |
| **Robustness** | 10% | Stability under cost and execution perturbations | $\ge 50.0$ |
| **PIT & Data Integrity** | 20% | Zero CRITICAL or HIGH leakage findings | $= 100.0$ |

$$\text{Overall Score} = \sum_{i=1}^6 \text{Weight}_i \times \text{Score}_i$$
- **Validation Pass Condition:** $\text{Overall Score} \ge 60.0$ **AND** $\text{PIT Integrity Score} = 100.0$.
