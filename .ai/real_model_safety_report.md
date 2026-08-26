# Real Model Safety & Hard Disqualification Report — Phase 5.6G

This document formalizes the safety checks and disqualification enforcement for the multi-model empirical benchmark.

---

## 1. Safety & Deterministic Boundaries

1. **Numerical Invariant Enforcement:**
   * Python calculators remain the sole mathematical authority for RSI, EMA, MACD, P/E, Beta, and Volatility.
   * Model outputs are checked for mutation against prompt input values.
2. **Deterministic Risk Precedence:**
   * Risk filters, daily loss limits, and sector concentration caps cannot be overridden by LLM confidence.
3. **Point-In-Time & Holdout Bounds:**
   * Contexts strictly restricted to 2021–2022. `assert_no_holdout_leakage` guards against 2023–2024 holdout access.
