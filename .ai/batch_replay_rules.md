# Batch Replay Rules — Phase 5.3

This document outlines the operational rules and Point-in-Time constraints for executing batch universe replay over historical market dates.

---

## 1. Temporal Integrity & Look-Ahead Isolation

For each simulation timestamp $T$:
1. **Universe Membership:** Only constituents where $\text{effective\_from} \le T$ and ($\text{effective\_to}$ is null or $\ge T$) are included in the universe snapshot.
2. **Data Slicing:** All OHLCV bars, financial statements, news items, and institutional flows with timestamp $> T$ are strictly stripped before running Stage A pre-filtering or Stage B specialists.
3. **Price Discovery:** Current asset price is evaluated from the closing price of the latest bar $\le T$.

---

## 2. Two-Stage Execution Flow

1. **Stage A (Scan & Screen):**
   - The scanner filters the entire universe at timestamp $T$.
   - Computes candidate scores and selects Top-K eligible candidates.
   - **Zero LLM invocations occur during Stage A.**
2. **Stage B (Deep Pipeline):**
   - Only the Top-K selected candidates are forwarded to Stage B.
   - 9 Specialist Agents, Evidence Aggregator, Debate Engine, and Investment Committee are executed on the Top-K candidates.
   - Approved decisions generate orders executed through the Paper Broker with slippage and commission.
   - Open position values and portfolio equity are updated at each timestamp.
