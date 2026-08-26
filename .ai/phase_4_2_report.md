# Phase 4.2 — Adversarial Debate Engine Report

**Status:** ✅ COMPLETE
**Date:** 2026-08-24
**Baseline:** 451 / 451 tests
**Final:** 491 / 491 tests (40 new, 0 regressions)

---

## Files Created

| File | Purpose |
|------|---------|
| `backend/domain/debate_schemas.py` | Pydantic schemas for `BullCase`, `BearCase`, `RiskAssessment`, `DebateResult`, and debate enums. |
| `backend/debate/bull_agent.py` | Implementation of `BullAgent` which constructs the initial thesis. |
| `backend/debate/bear_agent.py` | Implementation of `BearAgent` which attacks the Bull thesis. |
| `backend/debate/risk_agent.py` | Implementation of `RiskAgent` which evaluates downside and constraints. |
| `backend/debate/debate_orchestrator.py` | Orchestrates the debate and scores it deterministically. |
| `tests/test_debate_engine.py` | 40 unit tests covering edge cases, failure states, and successful execution. |
| `.ai/debate_engine_design.md` | Architectural documentation. |
| `.ai/phase_4_2_report.md` | This report. |

## Architecture & Workflow

The Debate Engine uses an asynchronous sequential workflow pattern:
1. `BullAgent` ingests the `UnifiedEvidencePackage` and produces a structured `BullCase`.
2. `BearAgent` ingests the `UnifiedEvidencePackage` + `BullCase` and produces a structured `BearCase`.
3. `RiskAgent` ingests the `UnifiedEvidencePackage` + `BullCase` + `BearCase` and produces a `RiskAssessment`.
4. `DebateOrchestrator` applies deterministic scoring based on evidence coverage and LLM confidence to yield a `DebateResult`.

## Evidence-Grounding Mechanism

All debate agents return a list of `EvidenceReference` objects within their schemas (`evidence_references`).
- The user prompt forces the LLMs to strictly tie every major claim to a supplied `evidence_id` from the `UnifiedEvidencePackage`.
- No numerical data is generated; the LLMs act solely as qualitative interpreters and debaters of the facts.

## Deterministic Scoring

The `DebateOrchestrator._resolve_debate` method implements the deterministic logic:
- Evaluates the number of `EvidenceReference` objects.
- Normalizes coverage against the `total_evidence_extracted`.
- Uses fixed weights (`0.1` for coverage, `0.5` for LLM confidence) to derive `bull_score`, `bear_score`, and `risk_score`.
- Enforces a hard `RISK_VETO` or `INSUFFICIENT_EVIDENCE` fallback.

## Testing Overview

- **New Tests:** 40 tests were added to `tests/test_debate_engine.py`.
- **Coverage:** Tests validate `SUCCESS`, `DEGRADED`, `LLMParseError`, and `LLMClientError` states for all three agents. The orchestrator is tested for successful pipelines, missing evidence, risk vetos, and early bull failure.
- **Results:** 491/491 passing, zero failures.

## Recommended Next Phase

**Phase 4.3: Investment Committee**
- Consume the `DebateResult` and generate a final verdict (`PASS`, `WATCH`, `CONDITIONAL`, `APPROVE`).
- Establish entry/exit condition templates.
