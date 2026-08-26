# Multi-Dimensional Model Selection Rules — Phase 5.6C

> **MULTI-DIMENSIONAL MODEL SELECTION RULES**  
> Formally specifies composite scoring weights and production promotion criteria.

---

## 1. Multi-Dimensional Composite Formula

$$\begin{aligned}
\text{Composite Score} = &\ 0.25 \times \text{Reasoning Quality Score} \\
&+ 0.20 \times \text{Evidence Grounding Score} \\
&+ 0.20 \times \text{Risk Recognition Score} \\
&+ 0.15 \times \text{Decision Stability Score} \\
&+ 0.10 \times \text{Schema Reliability Score} \\
&+ 0.05 \times \text{Cost Efficiency Score} \\
&+ 0.05 \times \text{Latency Efficiency Score}
\end{aligned}$$

---

## 2. Hard Disqualification Criteria

A candidate model is strictly **DISQUALIFIED** from production deployment if:
1. **Numerical Mutation Rate > 0%:** Hallucinates or mutates pre-calculated Python indicators.
2. **Schema Failure Rate > 0.5%:** Fails structured Pydantic output parsing.
3. **Risk Recognition Rate < 90.0%:** Fails to flag overbought conditions, unsustainable leverage, or macro contagion.
4. **Latency (p95) > 2,000 ms:** Exceeds acceptable real-time orchestration latency budget.
5. **Cost Per 100 Contexts > \$1.00 USD:** Exceeds economic viability threshold.
