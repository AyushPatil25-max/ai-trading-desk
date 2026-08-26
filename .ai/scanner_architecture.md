# Scanner & Batch Replay Architecture — Phase 5.3

> **CRITICAL NOTICE: PAPER HISTORICAL SIMULATION ONLY — NO LIVE TRADING**  
> This two-stage architecture performs high-throughput screening and availability-aware ranking across Indian stock universes (Nifty 50, Nifty 500, Custom) without calling LLMs during initial filtering.

---

## 1. Two-Stage Pipeline Architecture

```
+--------------------------------------------------------------------------------+
|                        Stock Universe (Nifty 50 / 500)                         |
+---------------------------------------+----------------------------------------+
                                        |
                                        v
+---------------------------------------+----------------------------------------+
|                          Point-in-Time Universe Filter                         |
|           (Constituents effective_from <= T and effective_to >= T)              |
+---------------------------------------+----------------------------------------+
                                        |
                                        v
+=======================================+========================================+
|                     STAGE A: Cheap Deterministic Scanner                       |
+=======================================+========================================+
|  1. Inexpensive Data Retrieval (OHLCV, Indicators, Summary Filings)            |
|  2. Deterministic Prefilter (Price Bounds, Minimum Bars, Sanity Checks)        |
|  3. Multi-Domain Scoring (Tech, Momentum, Quant, Fund, Val, Inst, News)         |
|  4. Evidence-Availability Aware Weighting                                      |
|  5. Data Quality Penalty Factor                                                |
|  6. Sector Concentration Limiter (max_candidates_per_sector)                   |
|  7. Top-K Candidate Selection                                                  |
|  * ZERO LLM CALLS MADE IN STAGE A *                                            |
+=======================================+========================================+
                                        |
                   Qualified Top-K Candidates Only (e.g. 5 of 50)
                                        |
                                        v
+=======================================+========================================+
|                  STAGE B: Full AI Trading Desk Analysis                        |
+=======================================+========================================+
|  1. Construct Sliced Point-in-Time MarketContext                              |
|  2. Execute 9 Specialist Agents in Parallel                                    |
|  3. Evidence Aggregation & Deterministic Normalization                         |
|  4. Adversarial Debate (BullAgent vs BearAgent vs RiskAgent)                   |
|  5. Investment Committee Decision Gates (APPROVE / HOLD / REJECT / VETO)       |
|  6. Execution Safety Engine (Kill Switch, Freshness, Risk Limits)              |
|  7. Paper Broker (Slippage + Commission Execution)                             |
|  8. Paper Portfolio Update & Performance Logging                               |
+=======================================+========================================+
                                        |
                                        v
+---------------------------------------+----------------------------------------+
|                     Batch Replay & Efficiency Report                           |
|       (Tracks LLM calls saved, specialist executions avoided, latency)         |
+--------------------------------------------------------------------------------+
```

---

## 2. Core Modules in `backend/scanner/`

1. **`universe.py`**:
   - `StockUniverse`, `UniverseConstituent`, `UniverseSnapshot`.
   - Point-in-Time constituent filtering: guarantees no future IPO or constituent changes leak into historical replay.
2. **`scanner_config.py`**:
   - `ScannerConfig`, `ScannerWeights`: externalized configurable weights, thresholds, and sector limits.
3. **`prefilter.py`**:
   - `DeterministicPrefilter`: fast validation of price bounds, historical bar sufficiency, and non-empty indicators.
4. **`ranking.py`**:
   - `CandidateRankingEngine`: scores each candidate across available domains, applies evidence-availability weighting and data-quality penalties, and enforces sector concentration caps.
5. **`opportunity_scanner.py`**:
   - `OpportunityScanner`: runs Stage A on universe constituents and computes compute efficiency metrics (`ScannerEfficiencyReport`).
6. **`batch_replay.py`**:
   - `BatchReplayEngine`: coordinates multi-timestamp historical replay over large universes.
7. **`routes.py`**:
   - FastAPI endpoints (`POST /api/scanner/run`, `GET /api/scanner/{run_id}`, `GET /api/scanner/{run_id}/candidates`, `POST /api/scanner/batch-replay`, `GET /api/scanner/{run_id}/efficiency`).
