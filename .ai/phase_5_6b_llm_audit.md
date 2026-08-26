# Phase 5.6B — Forensic LLM Audit Report

> **FORENSIC AUDIT: REAL LLM EXECUTION INTEGRITY & SAMPLE EVALUATION**  
> Comprehensive audit of provider configurations, execution modes, sample sizing, numerical boundaries, and decision sensitivity.

---

## 1. Provider & Configuration Inventory

From direct code inspection of `backend/infrastructure/llm.py`, `backend/validation/real_llm_runner.py`, and `backend/config/real_llm_validation_config.json`:

* **Provider:** Groq API via `groq.AsyncGroq(api_key=...)`.
* **Configured Model Identifier:** `llama-3.3-70b-versatile` (or overridden dynamically per experiment).
* **API Protocol:** OpenAI-compatible Async Chat Completions (`chat.completions.create`).
* **Temperature:** `0.1` (deterministic low-entropy sampling).
* **Sampling Settings:** Default Top-p / penalty not explicitly passed.
* **Structured Output Mechanism:** `response_format={"type": "json_object"}` + prompt injection of `response_model.model_json_schema()` + Pydantic validation `response_model.model_validate_json(raw_text)`.
* **Retry Behavior:** Orchestrator-level retries via `backend/application/retry_policy.py`; direct client catches unrecoverable errors as `LLMClientError` / `LLMParseError`.
* **Timeout Behavior:** Upstream HTTP client default timeout ($\sim 60\text{s}$).
* **Token Limits:** Max output tokens: `2048`.

---

## 2. Model Label vs Live Model Verification

* **Live Execution Verification:** In `GroqLLMClient`, `self._model` is passed directly to the Groq API when initialized with `GROQ_API_KEY`.
* **Offline CI / Test Harness Behavior:** When credentials are absent or during offline regression runs, execution uses `REPLAY_LLM` (from `LLMReplayCache`) or `MockLLMClient` test doubles.
* **Forensic Finding:** The Phase 5.6 test run validated the pipeline architecture using `REPLAY_LLM` / structured test doubles. Claims of live empirical reasoning are valid only when backed by recorded hashes in `LLMReplayCache` or active `GROQ_API_KEY` executions.

---

## 3. End-to-End Decision Trace

For any decision timestamp $T$:
1. **`MarketContext` Ingestion:** Historical OHLCV, fundamentals, sector data, macro data, news.
2. **Specialist Parallel Execution:** 9 Specialists evaluate input.
3. **Deterministic Pre-Calculations:** Python modules calculate RSI, EMA, P/E, beta, volatility.
4. **LLM Qualitative Synthesis:** LLM receives pre-calculated numbers and provides qualitative domain reasoning.
5. **`EvidenceAggregator`:** Merges 9 specialist outputs into `UnifiedEvidencePackage` with verified conflict/agreement maps.
6. **`DebateOrchestrator`:** `BullAgent` $\to$ `BearAgent` $\to$ `RiskAgent` debate sequence produces `DebateResult`.
7. **`InvestmentCommittee`:** Evaluates evidence package, debate result, consensus threshold, and minimum confidence to produce `InvestmentCommitteeDecision`.
8. **`ExecutionSafetyEngine`:** Enforces deterministic risk limits, max position size (10%), daily loss limits, and stale-data checks $\to$ `ALLOWED` or `BLOCKED`.
9. **`PaperBroker`:** Simulates execution with 5 bps slippage and 3 bps commission $\to$ `TradeJournalEntry` and `PortfolioState`.

---

## 4. Execution Mode Separation Matrix

| Execution Mode | Backend Component | Deterministic? | External API Call? | Token Cost | Primary Use Case |
|---|---|---|---|---|---|
| **`REAL_LLM`** | `GroqLLMClient` | No (API sampling) | Yes (Groq API) | Standard API Rate | Live Trading / Initial Cache Pop |
| **`REPLAY_LLM`**| `LLMReplayCache` | Yes (SHA-256) | No (Local Cache) | \$0.00 | Backtests, Validation Replays |
| **`MOCK_LLM`**  | `MockLLMClient` | Yes (Test Double) | No (In-Memory) | \$0.00 | Unit Tests & Fast Regression |
| **`DEGRADED`**  | Specialist Fallback| Yes (Data Rules) | No | \$0.00 | Missing/Incomplete Modality |

---

## 5. Statistical Audit of Phase 5.6 10-Context Sample

* **Sample Size:** $N = 10$ contexts across 5 symbols (`RELIANCE.NS`, `TCS.NS`, `INFY.NS`, `HDFCBANK.NS`, `TATAMOTORS.NS`).
* **Statistical Power:** $N = 10$ has a standard error of $\pm 9.5\%$ on a $90\%$ agreement rate ($95\%\ \text{CI} = [71.4\%, 100\%]$).
* **Selection Bias:** Confirmed Mega-Cap bias and sector concentration (Energy, IT, Auto, Banking). Did not include midcaps, cyclicals, or high-stress crisis windows (COVID-19 March 2020, Russia-Ukraine Feb 2022).
* **Conclusion:** The 10-context sample successfully validated pipeline plumbing, but is **statistically insufficient** to declare final production model readiness. A minimum of $N \ge 120$ stratified contexts is required.
