# Model Benchmark Protocol & Normalization — Phase 5.6C

> **BENCHMARK NORMALIZATION & ISOLATION PROTOCOL**  
> Guarantees identical evaluation conditions across all candidate LLMs.

---

## 1. Input Invariance & Normalization Standards

To ensure pure reasoning comparison, all models receive:
1. **Identical Market Context:** Identical price history, financial ratios, sector benchmarks, and news headlines.
2. **Identical System & User Prompts:** Same canonical templates, same Point-in-Time timestamps.
3. **Identical Response Schemas:** Standardized Pydantic schemas across all specialists.
4. **Identical Pre-Calculated Indicators:** RSI, EMAs, P/E, beta, volatility calculated by Python.
5. **Identical Temperature Policy:** $T = 0.1$ across all candidate models.

---

## 2. Partition Isolation & Leakage Prevention

To prevent model-selection data snooping:

$$\begin{matrix}
\mathbf{Historical\ Equity\ Timeline} \\
\Downarrow \\
\mathbf{Model\ Selection\ Dataset\ (2021-01-01\ \to\ 2022-12-31)} \\
\text{(Stratified } N = 120 \text{ contexts used to evaluate \& rank candidate LLMs)} \\
\Downarrow \\
\mathbf{LOCK\ PRODUCTION\ MODEL} \\
\Downarrow \\
\mathbf{Holdout\ Validation\ Dataset\ (2023-01-01\ \to\ 2024-12-31)} \\
\text{(Strictly unseen out-of-sample data for final production strategy validation)}
\end{matrix}$$
