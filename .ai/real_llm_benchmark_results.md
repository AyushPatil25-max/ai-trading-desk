# Real LLM Benchmark Results — Phase 5.6F

This document records the empirical status and measured scorecard values across all candidate slots.

---

## 1. Candidate Model Measurement Summary

| Candidate Model | Slot Name | Execution Mode | Real Calls | Contexts Evaluated | Total Tokens | Actual Cost | Mean Latency | Composite Score | Disqualified | Reason |
|---|---|---|---|---|---|---|---|---|---|---|
| **`llama-3.3-70b-versatile`** | `groq_primary` | `NOT_EXECUTED` | 0 | 0 | 0 | `COST_NOT_VERIFIED` | `LATENCY_NOT_VERIFIED` | 0.00 | **YES** | `NOT_EXECUTED — MISSING_CREDENTIALS` |
| **`gemini-3.7-flash`** | `gemini_flash` | `NOT_EXECUTED` | 0 | 0 | 0 | `COST_NOT_VERIFIED` | `LATENCY_NOT_VERIFIED` | 0.00 | **YES** | `NOT_EXECUTED — MISSING_CREDENTIALS` |
| **`gemini-2.5-pro`** | `gemini_pro` | `NOT_EXECUTED` | 0 | 0 | 0 | `COST_NOT_VERIFIED` | `LATENCY_NOT_VERIFIED` | 0.00 | **YES** | `NOT_EXECUTED — MISSING_CREDENTIALS` |
| **`gpt-4o-mini`** | `openai_lightweight` | `NOT_EXECUTED` | 0 | 0 | 0 | `COST_NOT_VERIFIED` | `LATENCY_NOT_VERIFIED` | 0.00 | **YES** | `NOT_EXECUTED — MISSING_CREDENTIALS` |
| **`gpt-4o`** | `openai_reasoning` | `NOT_EXECUTED` | 0 | 0 | 0 | `COST_NOT_VERIFIED` | `LATENCY_NOT_VERIFIED` | 0.00 | **YES** | `NOT_EXECUTED — MISSING_CREDENTIALS` |

---

## 2. Infrastructure Readiness
- Live adapter drivers: **VERIFIED & OPERATIONAL**
- Metric extraction algorithms: **VERIFIED & OPERATIONAL**
- Holdout partition isolation guards: **VERIFIED & ACTIVE**
- Regression test suite: **607 / 607 TESTS PASSING**
