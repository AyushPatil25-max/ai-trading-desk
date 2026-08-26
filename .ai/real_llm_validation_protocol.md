# Real LLM Validation Protocol — Phase 5.6B

> **STANDARDIZED PROTOCOL FOR EMPIRICAL LLM REASONING VALIDATION**  
> Statistically rigorous, multi-regime, multi-sector historical validation framework.

---

## 1. Stratified Multi-Regime Sampling Matrix ($N \ge 120$)

To eliminate selection bias, the validation dataset must be deterministically sampled across 5 market regimes and 6 economic sectors:

### A. Market Regimes (Min 20 Contexts Each):
1. **Strong Bull:** Persistent upward trend (Nifty 50 ADX > 25, 20 EMA > 50 EMA).
2. **Bull Pullback:** Uptrend with sharp short-term retracements (RSI < 45).
3. **Sideways High Volatility:** Range-bound market with wide intraday ATR (> 2.0%).
4. **Sideways Low Volatility:** Low ATR (< 0.8%), narrow Bollinger Bands.
5. **Bear Trend & Liquidity Shock:** Prolonged drawdown / systemic panic (e.g. March 2020, Feb 2022).

### B. Sector & Market Cap Diversity:
- **Large Cap Equities:** `RELIANCE.NS`, `TCS.NS`, `HDFCBANK.NS`, `TATAMOTORS.NS`, `SUNPHARMA.NS`, `TATASTEEL.NS`, `LT.NS`.
- **Mid Cap Equities:** `DIXON.NS`, `POLYCAB.NS`, `PERSISTENT.NS`.

### C. Specific Event Windows:
- **Earnings Season:** Contexts captured within $\pm 3$ trading days of quarterly financial announcements.
- **Macro Announcements:** RBI Monetary Policy dates and Union Budget announcement dates.
- **News Extremes:** High-news event spikes vs zero-news quiet periods.

---

## 2. Invariant Execution Protocol

For every candidate model $M$:
1. **Identical Inputs:** Feed identical, canonical `MarketContext` snapshots.
2. **Identical Prompts:** Use SHA-256 verified prompt templates with strict Point-in-Time bounds.
3. **Identical Pre-Calculators:** All mathematical indicators computed by deterministic Python libraries.
4. **Identical Risk Controls:** Downstream `ExecutionSafetyEngine` applies identical position limits.

---

## 3. Model Quality & Decision Integrity Metrics

| Metric Category | Specific KPI | Target Threshold |
|---|---|---|
| **Agreement & Sensitivity** | Specialist Agreement Rate vs Baseline | $\ge 85.0\%$ |
| | Final Committee Decision Agreement | $\ge 80.0\%$ |
| | Decision Flip Rate | $\le 15.0\%$ |
| **Risk Calibration** | Risk Recognition Rate (Flags overbought/cyclical risks)| $\ge 95.0\%$ |
| | Numerical Boundary Hallucination Violations | **0 Violations (Strict)** |
| | Look-ahead Information Leakage | **0 Violations (Strict)** |
| **Operational Feasibility**| Pydantic Schema Violation Rate | $0.0\%$ |
| | Average Inference Latency (p95) | $\le 1,200\text{ms}$ |
| | Compute Cost Per 100 Contexts | $\le \$0.50\text{ USD}$ |
