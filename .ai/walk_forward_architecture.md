# Walk-Forward Validation Architecture — Phase 5.4

> **CRITICAL NOTICE: HISTORICAL SIMULATION ONLY — NO LIVE TRADING**  
> This engine implements rigorous out-of-sample walk-forward backtesting, zero-lookahead Point-in-Time leakage detection, ablation analysis, baseline comparisons, and deterministic validation scorecards.

---

## 1. Walk-Forward Windowing Architecture

```
Timeline: [2018] ------------------------------------------------------> [2025]

Window 0: |<--- Train (3y) --->|<- Val (1y) ->|<- Test Out-Of-Sample (1y) ->|
          [   2018 - 2020     ][    2021     ][          2022               ]

Window 1:        |<--- Train (3y) --->|<- Val (1y) ->|<- Test Out-Of-Sample (1y) ->|
                 [   2019 - 2021     ][    2022     ][          2023               ]

Window 2:               |<--- Train (3y) --->|<- Val (1y) ->|<- Test Out-Of-Sample (1y) ->|
                        [   2020 - 2022     ][    2023     ][          2024               ]

* STRICT RULE: Optimization occurs only in Train/Val windows. Test windows are strictly Out-Of-Sample. *
```

---

## 2. Validation Pipeline Flow

```
+-------------------------------------------------------------------------------+
|                      Walk-Forward Rolling Windows                             |
+--------------------------------------+----------------------------------------+
                                       |
                                       v
+--------------------------------------+----------------------------------------+
|                     Point-in-Time Leakage Detector                            |
|        (Scans OHLCV, fundamentals, news, corporate filings, universe)         |
+--------------------------------------+----------------------------------------+
                                       |
                                       v
+--------------------------------------+----------------------------------------+
|                 Out-of-Sample Batch Replay Execution                          |
|         (Stage A Scanner -> Top-K -> Stage B Specialists -> Safety)           |
+--------------------------------------+----------------------------------------+
                                       |
                                       v
+--------------------------------------+----------------------------------------+
|                      Multi-Dimensional Validation                             |
|  1. Baseline Comparisons (Buy & Hold, Equal Weight, Tech, Momentum, Scanner)  |
|  2. Market Regime Breakdown (Bull, Bear, Sideways, High/Low Volatility)       |
|  3. Ablation Experiments (Variant A through Variant F)                        |
|  4. Specialist & Sector Attributions                                          |
|  5. Transaction Cost & Slippage Sensitivity Matrix                            |
|  6. Perturbation Robustness Tests                                             |
+--------------------------------------+----------------------------------------+
                                       |
                                       v
+--------------------------------------+----------------------------------------+
|                      Validation Scorecard & Report                            |
|       (Predictive Quality, Risk-Adjusted, Drawdown, Consistency, Integrity)   |
+-------------------------------------------------------------------------------+
```

---

## 3. Core Modules in `backend/validation/`

1. **`validation_config.py`**:
   - `WalkForwardConfig`: train/val/test spans, step size, costs, slippage, and sensitivity lists.
2. **`validation_state.py`**:
   - Schemas for `WalkForwardWindow`, `LeakageFinding`, `RegimePerformance`, `AblationResult`, `SpecialistAttribution`, `ValidationScorecard`, `WalkForwardResult`.
3. **`leakage_detector.py`**:
   - `LeakageDetector`: identifies future OHLCV, filings, news, institutional data, or constituent dates relative to decision timestamp $T$.
4. **`robustness.py`**:
   - `RobustnessEngine`: computes baseline strategies, market regime metrics, ablation studies, specialist attributions, cost sensitivity, and validation scorecards.
5. **`walk_forward.py`**:
   - `WalkForwardEngine`: partitions timeline and coordinates out-of-sample walk-forward executions.
6. **`validation_report.py`**:
   - `ValidationReportBuilder`: formats Markdown strategy validation scorecards and reports.
7. **`routes.py`**:
   - FastAPI endpoints (`/api/validation/*`).
