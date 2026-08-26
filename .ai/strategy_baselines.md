# Strategy Baselines Specification — Phase 5.4

This document defines the 6 deterministic strategy baselines evaluated under identical historical dates, transaction costs, and slippage assumptions.

---

## 1. Baseline Definitions

1. **Buy-and-Hold Benchmark (^NSEI):**
   - Holds the market benchmark index from window start to window end.
2. **Equal-Weight Universe:**
   - Allocates $1/N$ capital across all active universe constituents with periodic rebalancing.
3. **Technical Baseline (EMA Crossover):**
   - Trades EMA20 / EMA50 moving average crossovers on price action alone.
4. **Momentum Baseline (20D Momentum):**
   - Trades top 10% 20-day momentum leaders with trailing stop loss.
5. **Scanner-Only Baseline (Stage A):**
   - Takes trades directly on Stage-A pre-filtered and ranked candidates without specialist analysis, adversarial debate, or Investment Committee vetoes.
6. **Full AI Trading Desk (Stage A + B):**
   - Full production pipeline: Stage-A Scanner -> 9 Specialists -> Evidence Aggregator -> Bull/Bear/Risk Debate -> Investment Committee -> Execution Safety Engine -> Paper Broker.
