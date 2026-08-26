# LLM Execution Mode & Determinism Disclosure — Phase 5.5

This document explicitly defines the LLM execution mode and determinism guarantees of the AI Trading Desk backtesting engine.

---

## 1. LLM Execution Mode Classification

$$\textbf{Execution Mode:} \quad \mathbf{REAL\_DATA\_SIMULATION\_WITH\_MOCKED\_AI}$$

### Technical Definition:
- **Market Data Layer:** 100% Real historical Indian equity data (daily OHLCV, financial disclosures, macroeconomic time series, and verified reconstitution circulars).
- **Specialist LLM Reasoning Layer:** In offline test and backtesting harness, specialist outputs were evaluated using deterministic structured heuristic doubles (`MockLLMClient` with schema validation) to guarantee 100% test reproducibility, eliminate external API rate limits, and ensure zero floating-point nondeterminism.
- **Production Boundary:** When `GroqLLMClient` is enabled with `GROQ_API_KEY`, live inference queries the LLM API asynchronously.

---

## 2. Determinism Guarantees
- No `numpy.random` or non-deterministic uuid state affects order generation, allocation sizing, or risk veto decisions.
- Identical configuration + dataset hashes produce 100% bitwise identical trade journals.
