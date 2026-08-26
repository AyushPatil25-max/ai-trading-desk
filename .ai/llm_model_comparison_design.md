# Multi-Model LLM Comparison Design — Phase 5.6B

> **PAIRED-MODEL COMPARISON EXPERIMENT DESIGN**  
> Evaluates candidate reasoning models on identical canonical market snapshots without altering trading logic or deterministic risk gates.

---

## 1. Candidate Model Portfolio

| Model Identifier | Provider / Engine | Target Role | Estimated Cost / 1M Tokens |
|---|---|---|---|
| **`llama-3.3-70b-versatile`** | Groq API | Baseline Open-Weights Champion | \$0.59 / M tokens |
| **`gemini-2.5-flash`** | Google GenAI | High-Speed / High-Throughput Reasoning | \$0.15 / M tokens |
| **`gemini-2.5-pro`** | Google GenAI | Deep Qualitative & Cross-Domain Synthesis | \$1.25 / M tokens |
| **`gpt-4o-mini`** | OpenAI API | Lightweight Proprietary Reasoning | \$0.15 / M tokens |

---

## 2. Experimental Workflow Architecture

$$\begin{matrix}
\mathbf{Canonical\ Historical\ Contexts\ (N = 120)} \\
\Downarrow \\
\mathbf{Deterministic\ Python\ Calculators} \\
\Downarrow \\
\begin{array}{c|c|c|c}
\mathbf{Model\ A:\ Llama\ 3.3} & \mathbf{Model\ B:\ Gemini\ Flash} & \mathbf{Model\ C:\ Gemini\ Pro} & \mathbf{Model\ D:\ GPT-4o\ Mini} \\
\Downarrow & \Downarrow & \Downarrow & \Downarrow \\
\text{Record to Cache} & \text{Record to Cache} & \text{Record to Cache} & \text{Record to Cache}
\end{array} \\
\Downarrow \\
\mathbf{Unified\ Evidence\ Aggregator\ \&\ Debate\ Engine} \\
\Downarrow \\
\mathbf{Investment\ Committee\ (Deterministic\ Voting)} \\
\Downarrow \\
\mathbf{Execution\ Safety\ Engine\ (Deterministic\ Risk\ Gates)} \\
\Downarrow \\
\mathbf{Comparative\ Evaluation\ Matrix\ (Agreement,\ Flips,\ Latency,\ Sharpe,\ Drawdown)}
\end{matrix}$$

---

## 3. Strict Pre-Conditions Before Production Migration
1. **No Logic Changes:** The trading strategy, consensus thresholds, indicators, and risk gates remain 100% frozen.
2. **Empirical Evidence Required:** A candidate model will only replace the baseline if it achieves equal or higher risk-adjusted Sharpe, zero numerical violations, and meets latency/cost constraints on the $N=120$ stratified benchmark.
