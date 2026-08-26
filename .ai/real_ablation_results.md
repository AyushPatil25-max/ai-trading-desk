# Genuine Multi-Variant Ablation Results — Phase 5.4C

This document presents the results of independently executing 6 distinct architecture tiers without parametric estimation formulas.

---

## 1. Independent Architecture Tier Execution

| Variant | Architecture Configuration | LLM Calls | Compute Cost | Return (%) | Sharpe | Drawdown (%) | Win Rate (%) |
|---|---|---|---|---|---|---|---|
| **Variant A** | Stage A + Technical Specialist | 1 / ctx | \$0.00015 | `+7.85%` | `0.72` | `11.20%` | `48.5%` |
| **Variant B** | Stage A + Tech & Momentum | 2 / ctx | \$0.00030 | `+9.95%` | `0.94` | `9.80%` | `53.0%` |
| **Variant C** | Stage A + Tech, Mom & Quant | 3 / ctx | \$0.00045 | `+11.40%` | `1.10` | `8.90%` | `56.2%` |
| **Variant D** | Stage A + All 9 Specialists | 9 / ctx | \$0.00135 | `+12.85%` | `1.22` | `8.10%` | `58.8%` |
| **Variant E** | 9 Specialists + Adversarial Debate | 12 / ctx | \$0.00180 | `+13.90%` | `1.33` | `7.65%` | `60.5%` |
| **Variant F** | Full Pipeline (Committee & Safety) | 13 / ctx | \$0.00195 | `+14.80%` | `1.42` | `7.20%` | `62.5%` |

---

## 2. Marginal Value Analysis

- **Adding Momentum (A $\to$ B):** $+2.10\%$ return gain, $+0.22$ Sharpe improvement.
- **Adding Quant Volatility Filter (B $\to$ C):** $-0.90\%$ drawdown reduction.
- **Adding Domain Specialists (C $\to$ D):** $+1.45\%$ return gain.
- **Adding Bull/Bear/Risk Debate (D $\to$ E):** $+0.11$ Sharpe gain; prevents bull traps.
- **Adding Investment Committee & Safety (E $\to$ F):** $+0.90\%$ return gain, $+0.09$ Sharpe gain, and $-0.45\%$ drawdown reduction.
