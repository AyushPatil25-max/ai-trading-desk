# Provider-Neutral Model Architecture — Phase 5.6C

> **ARCHITECTURE: UNIFIED LLM ABSTRACTION LAYER**  
> Enables dynamic provider switching without touching specialist or orchestration code.

---

## 1. Abstraction Hierarchy

$$\begin{matrix}
\mathbf{Specialist\ Agents\ /\ Debate\ /\ Committee} \\
\Downarrow \\
\mathbf{LLMClient\ Abstract\ Interface\ (async\ generate\_structured)} \\
\Downarrow \\
\mathbf{ProviderNeutralLLMClient\ Adapter} \\
\Downarrow \\
\begin{array}{c|c|c|c|c}
\mathbf{Groq} & \mathbf{Gemini} & \mathbf{OpenAI} & \mathbf{ReplayCache} & \mathbf{MockTestDouble} \\
\text{(llama-3.3)} & \text{(gemini-2.5)} & \text{(gpt-4o)} & \text{(SHA-256 DB)} & \text{(Pydantic Model)}
\end{array}
\end{matrix}$$

---

## 2. Standardized Execution Lifecycle

For every model request:
1. **Deterministic Request Hash:** Computes SHA-256 key from `(system_prompt, user_prompt, response_schema, model, temperature)`.
2. **Replay Cache Lookup:** If cache hit exists in `REPLAY` mode, returns recorded response payload instantly.
3. **Async Provider Dispatch:** Dispatches to active provider API with structured JSON output enforcement.
4. **Strict Pydantic Validation:** Model response is validated against schema via `response_model.model_validate_json(raw_text)`.
5. **Execution Statistics Recording:** Latency, input tokens, output tokens, and calculated cost are logged to `LLMExecutionStats`.
