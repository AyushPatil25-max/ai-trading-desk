# Real LLM Execution Mode & Determinism Taxonomy — Phase 5.6

This document specifies the execution modes and determinism guarantees of the AI Trading Desk LLM reasoning subsystem.

---

## 1. Execution Modes

1. **`REAL_LLM` (Live API Call):**
   - Directly connects asynchronously to the upstream LLM API (Groq `llama-3.3-70b-versatile`).
   - Automatically populates the `LLMReplayCache` upon successful response.
   - Non-deterministic across runs due to upstream provider sampling.

2. **`REPLAY_LLM` (Deterministic Replay):**
   - Retrieves identical bitwise responses from `LLMReplayCache` using SHA-256 request hashes.
   - 100% deterministic, zero latency, zero API rate limits, and 100% test reproducibility.

3. **`MOCK_LLM` (Deterministic Test Double):**
   - Uses static Pydantic test doubles for rapid offline development and unit tests.

---

## 2. Invalidation & Cache Eviction Rules
- Any modification to system prompts, user prompt templates, or response schemas alters the computed SHA-256 key and invalidates the cached entry, triggering a fresh LLM query.
