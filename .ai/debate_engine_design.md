# Debate Engine Design — Phase 4.2

## Overview

The Adversarial Debate Engine orchestrates an adversarial process to test an investment hypothesis before it reaches the Investment Committee. It enforces a sequence of structured arguments while forbidding LLMs from calculating or inventing deterministic numbers.

## Architecture

The Debate Engine leverages three new specialized agents orchestrated sequentially:

```
UnifiedEvidencePackage
      |
      v
  BullAgent ───> BullCase (Strongest Long Thesis)
                      |
                      v
  BearAgent ───> BearCase (Adversarial Short Attack)
                      |
                      v
  RiskAgent ───> RiskAssessment (Downside & Constraints)
                      |
                      v
  DebateOrchestrator ───> DebateResult
```

### Components

1. **BullAgent**
   - **Role:** Construct the strongest evidence-backed long thesis.
   - **Inputs:** `UnifiedEvidencePackage`.
   - **Outputs:** `BullCase` (Core thesis, supporting evidence, key catalysts, invalidation conditions, confidence, risks).

2. **BearAgent**
   - **Role:** Attack the `BullCase`. Find flaws, contradictions, and data weaknesses.
   - **Inputs:** `UnifiedEvidencePackage`, `BullCase`.
   - **Outputs:** `BearCase` (Attack summary, bull claims challenged, contradictory evidence, key downside risks).

3. **RiskAgent**
   - **Role:** Evaluate downside, uncertainty, and liquidity/concentration risks.
   - **Inputs:** `UnifiedEvidencePackage`, `BullCase`, `BearCase`.
   - **Outputs:** `RiskAssessment` (Risk level, risk score, primary/secondary risks, position constraints, risk veto flag).

4. **DebateOrchestrator**
   - **Role:** Orchestrate the sequence and resolve the debate deterministically.
   - **Sequence:** Bull -> Bear -> Risk -> Deterministic Resolution.
   - **Outputs:** `DebateResult`.

## Evidence Grounding

All agents are instructed to extract evidence directly from the `UnifiedEvidencePackage` and include explicit references in their outputs (`EvidenceReference`).
This enforces traceability and stops LLM hallucination:
- Each claim contains an `evidence_id`, `category`, and `claim` string.
- If evidence is missing, the LLM must explicitly acknowledge it instead of inventing facts.
- **Deterministic Fact Protection:** Any numerical metric output in the debate must trace back to the pre-calculated `UnifiedEvidencePackage`.

## Deterministic Confidence and Scoring

The `DebateOrchestrator` computes the final thesis status and scores using deterministic logic:
- `bull_score` and `bear_score` are weighted combinations of evidence coverage and LLM confidence.
- `risk_score` is directly consumed and combined with coverage.
- If `coverage < 0.2` or an agent fails, the debate resolves to `INSUFFICIENT_EVIDENCE`.
- If `risk_veto` is triggered, the debate resolves to `RISK_VETO`.
- Otherwise, the debate evaluates `bull_score - bear_score` to determine `BULL_FAVORED`, `BEAR_FAVORED`, or `MIXED`.

## Context Integrity & Failure Handling

- All cases (`BullCase`, `BearCase`, `RiskAssessment`) inherit and validate the `context_id` and `symbol` from the `MarketContext`.
- If any agent fails (e.g., `LLMClientError`), the debate fails gracefully, resulting in an `INSUFFICIENT_EVIDENCE` status, allowing the broader pipeline to proceed safely without fabricating a decision.
