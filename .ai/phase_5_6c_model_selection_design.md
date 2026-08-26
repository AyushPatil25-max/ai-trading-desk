# Phase 5.6C — Production LLM Selection & Benchmark Preparation

> **SYSTEM ARCHITECTURE & BENCHMARK PREPARATION SPECIFICATION**  
> Prepares candidate reasoning models, normalization protocols, multi-dimensional scoring frameworks, and dataset partition leakage boundaries.

---

## 1. Current Model Baseline & Available Candidate Slots

From [`LLMAdapterFactory`](file:///c:/Users/Ayush%20Suryavanshi/AI-Trading-Desk/backend/infrastructure/llm_provider_adapter.py#L198) and [`llm_candidates_registry.json`](file:///c:/Users/Ayush%20Suryavanshi/AI-Trading-Desk/backend/config/llm_candidates_registry.json):

| Slot Name | Provider | Model ID | Target Role | Context Window | Status |
|---|---|---|---|---|---|
| **`groq_primary`** | `GROQ` | `llama-3.3-70b-versatile` | Current Production Baseline | 128k | Verified / Supported |
| **`gemini_flash`** | `GEMINI` | `gemini-2.5-flash` | High-Speed / High-Throughput Reasoning | 1M | Slot Prepared / Adapter Wired |
| **`gemini_pro`** | `GEMINI` | `gemini-2.5-pro` | Deep Qualitative & Cross-Domain Synthesis| 2M | Slot Prepared / Adapter Wired |
| **`openai_lightweight`**| `OPENAI` | `gpt-4o-mini` | Lightweight Proprietary Reasoning | 128k | Slot Prepared / Adapter Wired |
| **`openai_reasoning`** | `OPENAI` | `gpt-4o` | Strong Multi-Modal Reasoning | 128k | Slot Prepared / Adapter Wired |

---

## 2. Invariant Rules for Production Selection
1. **No Logic Alteration:** The 9 specialists, mathematical calculators, Evidence Aggregator, Debate Engine, and Investment Committee algorithms remain 100% frozen.
2. **Deterministic Risk Precedence:** Execution safety filters and risk limits cannot be altered or bypassed by any candidate model.
3. **No Model Superiority Claim:** No candidate model is declared superior without empirical evaluation across the $N \ge 120$ stratified benchmark.
