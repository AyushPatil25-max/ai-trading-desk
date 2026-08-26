# Model Selection Forensic Audit — Phase 5.6D

This document provides a forensic audit of the benchmark dataset, provider configurations, and partition isolation.

---

## 1. Benchmark Execution Parameters

1. **Models Tested:**
   - `llama-3.3-70b-versatile` (Groq API — Evaluated)
   - `gemini-2.5-flash` (Google GenAI — Evaluated)
   - `gemini-2.5-pro` (Google GenAI — Evaluated)
   - `gpt-4o-mini` (OpenAI API — Evaluated)
   - `gpt-4o` (OpenAI API — Evaluated)

2. **Dataset Configuration:**
   - **Dataset Period:** 2021-01-01 to 2022-12-31 (Strict Selection Period)
   - **Sample Size:** $N = 120$ Stratified Contexts
   - **Regime Coverage:** 5 Regimes (Strong Bull, Bull Pullback, Sideways High Vol, Sideways Low Vol, Bear Trend)
   - **Sector Representation:** 7 Sectors (Energy, IT, Banking, Auto, Pharma, Metals, Industrials)
   - **Market Cap Distribution:** 70% Large Cap (Nifty 50), 30% High-Growth Midcaps

3. **Invariance Audit:**
   - **Holdout Dataset (2023–2024) Invocation:** `0` (Zero snooping)
   - **Python Calculator Modifications:** `0`
   - **Risk Filter Overrides:** `0`
   - **Production Model State:** `UNMODIFIED` (`llama-3.3-70b-versatile`)
