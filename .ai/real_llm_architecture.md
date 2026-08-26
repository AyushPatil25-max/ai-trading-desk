# Real LLM Historical Replay Architecture — Phase 5.6

> **ARCHITECTURAL OVERVIEW: HYBRID DETERMINISTIC-AI ENGINE**  
> Preserves numerical precision and point-in-time guarantees while validating LLM reasoning models.

---

## 1. Pipeline Separation & Numerical Boundaries

$$\begin{matrix}
\text{Raw Historical Market Context} \\
\Downarrow \\
\mathbf{Python\ Numerical\ Engine\ (Deterministic)} \\
\text{(Technical Indicators, Multiples, Volatility, Liquidity, Pre-filters)} \\
\Downarrow \\
\mathbf{Canonical\ Structured\ Prompt\ (Point-in-Time\ Enforced)} \\
\Downarrow \\
\mathbf{LLM\ Reasoning\ Layer\ (Qualitative\ Synthesis\ \&\ Cross-Domain\ Logic)} \\
\Downarrow \\
\mathbf{Structured\ Pydantic\ Validation\ \&\ Numerical\ Guardrails} \\
\Downarrow \\
\mathbf{Adversarial\ Debate\ \to\ Investment\ Committee\ \to\ Execution\ Safety\ Engine}
\end{matrix}$$

---

## 2. Hard Boundaries & Invariants
1. **Zero Numerical Authority:** LLM reasoning interprets pre-calculated numerical evidence; it has zero authority to invent or mutate calculated indicators (e.g. RSI, EMA, P/E).
2. **Deterministic Record & Replay:** Every live query to Groq/LLM generates a deterministic hash in `LLMReplayCache` for bitwise replayability.
3. **Safety Gate Precedence:** Execution safety limits, kill switches, and position sizing caps override any LLM approval or high confidence score.
