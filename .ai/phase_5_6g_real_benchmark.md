# Phase 5.6G — Real Empirical Model Benchmark Execution Report

> **EMPIRICAL MODEL BENCHMARK STATUS & INTEGRITY AUDIT**  
> Verifies provider candidate models, evaluates live credential availability, enforces zero-placeholder policy, and records empirical measurements.

---

## 1. Cleaned Candidate Model Registry

| Slot Name | Provider | Exact Verified Model ID | Context Window | Verified Pricing | Status |
|---|---|---|---|---|---|
| **`groq_primary`** | `GROQ` | `llama-3.3-70b-versatile` | 128k | \$0.59 / M in, \$0.79 / M out | Baseline (Ready) |
| **`gemini_flash`** | `GEMINI` | `gemini-3.7-flash` | 1M | \$0.15 / M in, \$0.60 / M out | Candidate (Ready) |
| **`openai_lightweight`**| `OPENAI` | `gpt-4o-mini` | 128k | \$0.15 / M in, \$0.60 / M out | Candidate (Ready) |
| **`openai_reasoning`** | `OPENAI` | `gpt-4o` | 128k | \$2.50 / M in, \$10.00 / M out| Candidate (Ready) |

*Note: Unverified / unsupported entries (`gemini-3.7-pro`, `gemini-2.5-pro`) were removed from the executable registry.*

---

## 2. Live Credential Audit Findings

| Provider | Environment Variable | Status | Execution Permitted |
|---|---|---|---|
| **Groq** | `GROQ_API_KEY` | **`MISSING`** | ❌ Blocked |
| **Google Gemini** | `GEMINI_API_KEY` / `GOOGLE_API_KEY` | **`MISSING`** | ❌ Blocked |
| **OpenAI** | `OPENAI_API_KEY` | **`MISSING`** | ❌ Blocked |

*Classification:* **`REAL_BENCHMARK_BLOCKED — MISSING_CREDENTIALS`**  
*Zero synthetic scores or mock results substituted.*
