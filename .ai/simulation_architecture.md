# Simulation Architecture — Phase 5.2

> **CRITICAL NOTICE: PAPER HISTORICAL SIMULATION ONLY — NO LIVE TRADING**  
> This framework provides deterministic point-in-time historical replay, realistic paper execution modeling (slippage and commission), risk metrics calculation, and audit reporting.

---

## 1. End-to-End Replay Pipeline

```
+-------------------------------------------------------------------------+
|                        Historical Market Data                           |
|       (OHLCV, Fundamentals, News, Corporate Disclosures, Flows)          |
+------------------------------------+------------------------------------+
                                     |
                                     v
+------------------------------------+------------------------------------+
|                      Point-in-Time Data Filter                          |
|         (Strictly enforces: observation_timestamp <= simulation_time)    |
+------------------------------------+------------------------------------+
                                     |
                                     v
+------------------------------------+------------------------------------+
|                       PIT MarketContext Slice                           |
|                  (Fresh context with PIT price & data)                  |
+------------------------------------+------------------------------------+
                                     |
                                     v
+------------------------------------+------------------------------------+
|                         9 Specialist Agents                             |
|          (Technical, Momentum, Quant, Fundamental, Valuation,          |
|                 Sector, Macro, News, Institutional)                     |
+------------------------------------+------------------------------------+
                                     |
                                     v
+------------------------------------+------------------------------------+
|                     Evidence Aggregation Engine                         |
|     (Normalizes evidence, resolves conflicts, enforces PIT consistency) |
+------------------------------------+------------------------------------+
                                     |
                                     v
+------------------------------------+------------------------------------+
|                      Adversarial Debate Engine                          |
|                   (BullAgent vs BearAgent vs RiskAgent)                 |
+------------------------------------+------------------------------------+
                                     |
                                     v
+------------------------------------+------------------------------------+
|                     Investment Committee Engine                         |
|         (Deterministic Decision Gates: APPROVE / HOLD / REJECT)         |
+------------------------------------+------------------------------------+
                                     |
                                     v
+------------------------------------+------------------------------------+
|                       Execution Safety Engine                           |
|   (Kill Switch, Duplicates, Freshness, Risk Limits, Integer Sizing)     |
+------------------------------------+------------------------------------+
                                     |
                                     v
+------------------------------------+------------------------------------+
|                         Paper Broker Engine                             |
|            (Deterministic Fill + Slippage + Commission Model)           |
+------------------+------------------------------------+-----------------+
                   |                                    |
                   v                                    v
+------------------+-----------------+  +---------------+-----------------+
|             Paper Portfolio        |  |          Execution Audit        |
|  (Cash, Positions, P&L, Exposure)  |  |    (Immutable Journal & Logs)   |
+------------------+-----------------+  +---------------+-----------------+
                   |                                    |
                   +-----------------+------------------+
                                     |
                                     v
+------------------------------------+------------------------------------+
|                    Portfolio Performance Engine                         |
|    (Equity Curve, Drawdown, Sharpe, Sortino, Win Rate, Profit Factor)   |
+------------------------------------+------------------------------------+
                                     |
                                     v
+------------------------------------+------------------------------------+
|                      Simulation Report & API                            |
|             (Markdown summary, JSON export, FastAPI routes)             |
+-------------------------------------------------------------------------+
```

---

## 2. Core Modules in `backend/simulation/`

1. **`simulation_config.py`**:
   - `SimulationConfig`: Strongly typed configuration specifying start/end dates, symbols, timeframe, initial cash, slippage rate (e.g. 0.05%), commission rate (0.03%), and benchmark symbol.
2. **`pit_filter.py` (`PointInTimeFilter`)**:
   - Strips all data occurring after simulation timestamp $T$.
   - Handles OHLCV bars, financial disclosures, news articles, and institutional flow observations.
3. **`performance.py` (`PerformanceEngine`)**:
   - Mathematically robust calculations for Sharpe Ratio, Sortino Ratio, Max Drawdown, Win Rate, Profit Factor, and Turnover.
   - Comprehensive guards against zero-variance, zero-downside deviation, and zero-trade edge cases.
4. **`replay_engine.py` (`HistoricalReplayEngine`)**:
   - Sequences chronological timestamps.
   - Updates open position valuations at each timestamp.
   - Routes context through specialists -> evidence -> debate -> committee -> safety -> broker -> portfolio.
   - Records detailed `EquityCurvePoint`, `TradeJournalEntry`, and `DecisionJournalEntry`.
5. **`report.py` (`SimulationReportBuilder`)**:
   - Synthesizes `SimulationReport` and formats Markdown performance summaries with data quality audit tables.
6. **`routes.py`**:
   - FastAPI endpoints (`POST /api/simulation/run`, `GET /api/simulation/{id}`, `GET /api/simulation/{id}/equity`, `GET /api/simulation/{id}/trades`, `GET /api/simulation/{id}/decisions`).
