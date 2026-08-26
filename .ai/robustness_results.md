# Robustness & Sensitivity Specification — Phase 5.4

This document details transaction cost sensitivity matrices, slippage drag analysis, and stochastic perturbation tests.

---

## 1. Transaction Cost & Slippage Sensitivity Matrix

Evaluates strategy survivability across 30 cost-slippage combinations:

- **Commission Rates:** 0 bps, 5 bps, 10 bps, 20 bps, 30 bps, 50 bps.
- **Slippage Rates:** 0.0%, 0.05%, 0.10%, 0.20%, 0.50%.

$$\text{Drag (\%)} = \text{Turnover} \times (\text{Commission Rate} + 2 \times \text{Slippage Rate}) \times 100$$
$$\text{Adjusted Return} = \text{Base Return} - \text{Drag}$$

---

## 2. Perturbation Robustness Tests

1. **Trade-Order Permutation:** Evaluates whether return sequence is fragile or path-dependent.
2. **Price Perturbation (+/- 0.05%):** Evaluates fill price noise resilience.
3. **Missing-Data Perturbation:** Evaluates performance degradation when corporate disclosures are sparse.
