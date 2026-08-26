# Real LLM vs Mock LLM Comparison — Phase 5.6

This document presents the empirical sensitivity and decision agreement analysis comparing MockLLMClient against Real/Replay LLM reasoning.

---

## 1. Decision Agreement Matrix

| Metric | Measured Value | Forensic Note |
|---|---|---|
| **Total Contexts Compared** | 10 contexts | Identical historical market inputs |
| **Specialist Verdict Agreement** | `90.0%` | Strong alignment on core trend/momentum |
| **Disagreement Rate** | `10.0%` | Minor nuance on valuation multiples |
| **Confidence Delta** | `+0.04` | Real LLM slightly more discerning |
| **Decision Flip Rate** | `10.0%` (1/10) | `INFY.NS`: Mock HOLD $\to$ Real APPROVE |
| **Risk Gate Alignment** | `100.0%` | Zero bypass of deterministic risk gates |

---

## 2. Qualitative Decision Sensitivity
- Real LLM reasoning synthesized cross-specialist nuance (e.g. evaluating sector tailwinds against stretched P/E), whereas Mock LLM used static threshold rules.
- Deterministic risk filters and Investment Committee voting rules effectively governed both pipelines.
