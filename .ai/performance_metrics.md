# Performance Metrics & Mathematical Formulations — Phase 5.2

This document details the exact mathematical formulas, zero-division guards, and boundary conditions implemented in the Performance Engine.

---

## 1. Formulas

### Total & Cumulative Return
$$\text{Total Return (\%)} = \left( \frac{\text{Final Capital} - \text{Initial Capital}}{\text{Initial Capital}} \right) \times 100$$

### Benchmark Excess Return
$$\text{Excess Return (\%)} = \text{Strategy Return (\%)} - \text{Benchmark Return (\%))}$$

### Annualized Volatility
$$\sigma_{\text{ann}} = \sigma_{\text{daily}} \times \sqrt{252} \times 100$$

### Maximum Drawdown
For each simulation point $t$:
$$\text{Peak}_t = \max_{0 \le s \le t}(\text{Equity}_s)$$
$$\text{Drawdown}_t = \text{Peak}_t - \text{Equity}_t$$
$$\text{Drawdown (\%)}_t = \left( \frac{\text{Drawdown}_t}{\text{Peak}_t} \right) \times 100$$
$$\text{Max Drawdown} = \max_t(\text{Drawdown}_t)$$

### Sharpe Ratio
$$\text{Sharpe} = \frac{\bar{R}_{\text{daily}} - R_{f,\text{daily}}}{\sigma_{\text{daily}}} \times \sqrt{252}$$
- **Guard:** If $\sigma_{\text{daily}} \le 10^{-8}$ or $N < 2$, returns `None`.

### Sortino Ratio
$$\text{Sortino} = \frac{\bar{R}_{\text{daily}} - R_{f,\text{daily}}}{\sigma_{\text{downside}}} \times \sqrt{252}$$
where:
$$\sigma_{\text{downside}} = \sqrt{\frac{1}{M}\sum_{R_t < R_f}(R_t - R_f)^2}$$
- **Guard:** If $\sigma_{\text{downside}} \le 10^{-8}$ or $M = 0$, returns `None`.

### Profit Factor
$$\text{Profit Factor} = \frac{\sum \text{Gross Profits}}{\sum |\text{Gross Losses}|}$$
- **Guard:** If $\sum |\text{Gross Losses}| = 0$ and $\sum \text{Gross Profits} > 0$, capped safely at `999.99`.

---

## 2. Commission & Slippage Models

- **BUY Execution Price:**
  $$P_{\text{fill}} = P_{\text{order}} \times (1 + \text{slippage\_rate})$$
- **SELL Execution Price:**
  $$P_{\text{fill}} = P_{\text{order}} \times (1 - \text{slippage\_rate})$$
- **Commission Fee:**
  $$\text{Commission} = (\text{Quantity} \times P_{\text{fill}} \times \text{commission\_rate}) + \text{fee}_{\text{flat}}$$
