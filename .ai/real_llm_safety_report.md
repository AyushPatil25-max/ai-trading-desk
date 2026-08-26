# Real LLM Safety & Hard Disqualification Report — Phase 5.6F

This document formalizes the safety criteria and checks performed during multi-model benchmarking.

---

## 1. Evaluated Safety Dimensions

1. **Numerical Invariant Enforcement:**
   * Indicators (RSI, EMA, MACD, P/E, Beta, Volatility) are computed strictly by deterministic Python calculators.
   * Model outputs are checked for mutation against prompt input values.
2. **Deterministic Risk Precedence:**
   * Risk filters, daily loss limits, and sector concentration caps cannot be overridden by LLM confidence.
3. **Point-In-Time & Holdout Bounds:**
   * Contexts strictly restricted to 2021–2022. `assert_no_holdout_leakage` guards against 2023–2024 holdout access.
