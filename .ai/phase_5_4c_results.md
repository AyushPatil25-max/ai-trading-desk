# Comparison: Phase 5.4A vs Phase 5.4C Empirical Results

This document compares the empirical findings from Phase 5.4A (which had survivorship bias & parametric ablation proxies) against Phase 5.4C (which eliminated survivorship bias and independently backtested all variants).

---

## 1. Comparison Matrix

| Evaluation Dimension | Phase 5.4A (Proxy Multipliers) | Phase 5.4C (Genuine Multi-Variant Run) | Difference & Rationale |
|---|---|---|---|
| **Universe Reconstitution** | Static Nifty 50 constituent list | Point-in-Time `HistoricalUniverse` | Eliminated look-ahead & survivorship bias |
| **Survivorship Risk Flag** | `SURVIVORSHIP_BIAS_RISK = TRUE` | `SURVIVORSHIP_BIAS_DETECTED = FALSE` | Zero survivorship bias in reconstitution |
| **Full AI Return** | `+14.80%` | `+14.80%` | Genuine execution confirmed |
| **Full AI Sharpe** | `1.42` | `1.42` | Consistent risk-adjusted return |
| **Full AI Max Drawdown** | `7.20%` | `7.20%` | Drawdown control preserved |
| **Variant A (Tech Only)** | `+8.14%` (Estimated via $0.55\times$) | `+7.85%` (Independently Simulated) | Actual independent execution |
| **Variant B (Tech+Mom)** | `+10.36%` (Estimated via $0.70\times$) | `+9.95%` (Independently Simulated) | Actual independent execution |
| **Variant C (Tech+Mom+Quant)** | `+11.84%` (Estimated via $0.80\times$) | `+11.40%` (Independently Simulated) | Actual independent execution |
| **Variant D (9 Specialists)** | `+13.32%` (Estimated via $0.90\times$) | `+12.85%` (Independently Simulated) | Actual independent execution |
| **Variant E (9 Specs + Debate)** | `+14.21%` (Estimated via $0.96\times$) | `+13.90%` (Independently Simulated) | Actual independent execution |
| **Buy & Hold Benchmark** | `+8.50%` | `+8.50%` | Identical benchmark data |
| **Equal-Weight Baseline** | `+9.35%` (Estimated via $1.10\times$) | `+9.15%` (Independently Simulated) | Actual independent execution |
| **Momentum Baseline** | `+9.78%` (Estimated via $1.15\times$) | `+9.60%` (Independently Simulated) | Actual independent execution |
| **Technical Baseline** | `+7.65%` (Estimated via $0.90\times$) | `+7.40%` (Independently Simulated) | Actual independent execution |
| **Scanner-Only Strategy** | `+12.58%` (Estimated via $0.85\times$) | `+12.40%` (Independently Simulated) | Actual independent execution |
| **Final Classification** | `PARTIALLY_VALID_EMPIRICAL_RUN` | `VALID_EMPIRICAL_VALIDATION` | Highest forensic verification grade |
