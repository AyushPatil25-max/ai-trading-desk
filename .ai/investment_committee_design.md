# Investment Committee Engine Design — Phase 4.3

## Overview

The Investment Committee Engine acts as the final decision layer in the AI Trading Desk pipeline. It consumes the `DebateResult` from the Adversarial Debate Engine and synthesizes a final deterministic capital allocation decision (`InvestmentDecision`). 

Crucially, the decision-making logic is purely deterministic. The LLM operates strictly at the qualitative synthesis boundary and cannot invent decisions, overwrite vetos, or determine position sizes.

## Architecture

The Investment Committee operates sequentially through deterministic gates before invoking the LLM for reasoning generation.

```
UnifiedEvidencePackage + DebateResult
                  |
         [Validate Inputs]
                  |
    [Run Deterministic Decision Gates]
                  |
       [Calculate Position Sizing]
                  |
       [Build Execution Plan]
                  |
           [LLM Synthesis] -> (Produces qualitative thesis)
                  |
    [Assemble InvestmentDecision]
```

### Schemas (`backend/domain/investment_committee_schemas.py`)
- `InvestmentDecisionState`: `APPROVE`, `HOLD`, `REJECT`, `INSUFFICIENT_EVIDENCE`, `RISK_VETO`, `DATA_QUALITY_VETO`.
- `ExecutionPlan`: Action, Horizon, Entry conditions, and Position Sizing details.
- `DecisionGate`: Records which thresholds were tested and the explicit outcome.
- `DecisionAudit`: A structured timeline explaining exactly why the final state was reached without relying on LLM explanations.

### Configuration (`backend/config/investment_committee_config.json`)
Deterministic thresholds are centralized here for easy tuning and audibility without touching Python code.
1. `evidence_sufficiency`: Minimum proxy for required evidence count.
2. `data_quality`: Based on the volume of missing critical metrics.
3. `bull_bear_spread`: Difference between Bull and Bear strengths.
4. `risk_tolerance`: Absolute cap on risk scores.
5. `confidence_min`: Systemic confidence floor.

## Deterministic Rule Set

### Hard Risk Veto
If `RiskAssessment.risk_veto` is `True`, the engine explicitly forces the `RISK_VETO` state. Even if the LLM attempts to generate a "Buy" recommendation, the backend explicitly preserves `RISK_VETO` in the final object.

### Critical Conflicts
If `UnifiedEvidencePackage` contains unresolved critical conflicts, the state degrades to `HOLD` or `INSUFFICIENT_EVIDENCE` depending on severity, blocking approval.

### Position Sizing
Calculated using base percentages, penalizing for risk score and adjusting for systemic confidence. If data is missing or the state is unapproved, sizing falls back to `is_available: False`.

## Provenance and Lineage

Every `InvestmentDecision` natively records:
- `context_id` and `symbol`
- `run_id` 
- Aggregated `evidence_references` inherited from the Debate Result. 

This ensures that the decision can be fully traced back to raw data without missing links.
