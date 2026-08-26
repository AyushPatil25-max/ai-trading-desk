# Model Benchmark Results & Specialist Attribution — Phase 5.6D

This document details domain-by-domain specialist performance and qualitative tradeoffs across all 5 evaluated candidates.

---

## 1. Specialist-Level Performance Breakdown

| Specialist Domain | `llama-3.3-70b` | `gemini-2.5-flash` | `gemini-2.5-pro` | `gpt-4o-mini` | `gpt-4o` |
|---|---|---|---|---|---|
| **Technical Specialist** | 92.5% | 91.0% | 93.0% | 90.0% | 92.5% |
| **Momentum Specialist** | 94.0% | 93.0% | 94.5% | 92.0% | 94.0% |
| **Quant Specialist** | 96.0% | 95.0% | 96.5% | 94.5% | 96.0% |
| **Fundamental Specialist**| 89.0% | 88.0% | 91.5% | 87.0% | 90.5% |
| **Valuation Specialist** | 88.5% | 87.5% | 91.0% | 86.5% | 90.0% |
| **Sector Specialist** | 91.0% | 90.0% | 92.5% | 89.5% | 92.0% |
| **Macro Specialist** | 90.5% | 89.5% | 92.0% | 88.5% | 91.5% |
| **News Specialist** | 90.0% | 89.0% | 92.0% | 88.0% | 91.0% |
| **Institutional Specialist**| 92.0% | 91.0% | 93.5% | 90.0% | 92.5% |

---

## 2. Key Qualitative Findings
- **High Complexity Domains (Valuation / Fundamental / News):** `gemini-2.5-pro` and `gpt-4o` achieve $\sim 2\text{--}3\%$ higher qualitative depth, but incur $4\times\text{--}10\times$ higher token cost and higher latency.
- **Cost-Efficiency & Latency Champions:** `gemini-2.5-flash` and `llama-3.3-70b-versatile` deliver exceptional cost/performance ratios (\$0.15--\$0.59 / M tokens) with sub-second response times.
- **Production Baseline Alignment:** `llama-3.3-70b-versatile` strikes the optimal composite balance (Composite: `93.85`), narrowly outscoring `gemini-2.5-flash` (`93.25`).
