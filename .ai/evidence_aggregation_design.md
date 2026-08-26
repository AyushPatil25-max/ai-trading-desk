# Evidence Aggregation Design — Phase 4.1A

## Overview

The Evidence Aggregation Engine transforms independent specialist outputs into ONE
normalized, auditable evidence package for downstream consumption by Bull/Bear/Risk
agents and the Investment Committee.

## Architecture

```
SpecialistRunResult
  └─ AgentExecutionRecord[] (9 specialists)
       └─ AgentOutput.raw_data (structured payloads)
            │
            ▼
  EvidenceAggregator.aggregate()
            │
            ├── Context Validation
            ├── Multi-Evidence Extraction (per-metric)
            ├── Duplicate Detection (deterministic key)
            ├── PIT Validation (timestamp drift check)
            ├── Agreement Detection (metric + domain level)
            ├── Conflict Detection (DIRECT / DOMAIN / DATA)
            ├── Evidence-Aware Weighting
            ├── Specialist Contribution Caps
            └── Final Confidence & Regime Calculation
            │
            ▼
  UnifiedEvidencePackage
```

## Evidence Taxonomy

| Type | Description | Example |
|------|-------------|---------|
| `DETERMINISTIC_FACT` | Direct extraction from data source | `CurrentPrice`, `revenue`, `policy_rate` |
| `DETERMINISTIC_CALCULATION` | Pure Python formula | `net_margin`, `pe_ratio`, `sharpe_ratio` |
| `LLM_INTERPRETATION` | Qualitative LLM judgment | `trend`, `fundamental_quality`, regime |
| `ASSUMPTION` | Stated analyst assumption | TTM period, sector classification |
| `UNAVAILABLE` | Requested but not available | Missing `sharpe_ratio` (need 61 closes) |

## Multi-Evidence Extraction

Each specialist produces **two types** of evidence:

1. **Regime Evidence** (1 per specialist): The overall directional signal
   (e.g., `TECHNICAL_REGIME = BULLISH`). Always `LLM_INTERPRETATION`.

2. **Metric Evidence** (N per specialist): Individual metric items from the
   specialist's structured `evidence`/`metrics` list. Each carries:
   - `value`, `unit`, `calculation_method`
   - `source`, `source_tier`, `verification_status`
   - `context_id`, `data_timestamp`
   - Classified as FACT, CALCULATION, or UNAVAILABLE

### Specialist Evidence Keys

| Specialist | Evidence List Key | Metric Name Key |
|-----------|------------------|-----------------|
| Technical | `evidence` | `name` |
| Momentum | `evidence` | `name` |
| Quant | `metrics` | `metric_name` |
| Fundamental | `metrics` | `metric_name` |
| Valuation | `evidence` | `metric_name` |
| Sector | `evidence` | `metric_name` |
| Macro | `evidence` | `metric_name` |
| News | `articles` | `headline` |
| Institutional | `evidence` | `metric_name` |

## Duplicate Detection

Deterministic key: `{specialist_name}|{metric_name}|{context_id}|{data_timestamp_iso}`

If a key collision occurs, the duplicate is skipped and `duplicates_detected` counter increments.

## Agreement Detection

### Domain-Level (`DOMAIN_LEVEL`)
- Groups regime evidence items by direction
- Agreement when ≥2 specialists share the same direction

### Metric-Level (`METRIC_LEVEL`)
- Groups per-metric evidence by `metric_name`
- Agreement when ≥2 **different** specialists produce same-direction evidence
  for the same metric

## Conflict Detection

### Taxonomy

| Type | Trigger | Severity |
|------|---------|----------|
| `DIRECT_CONFLICT` | Same category, opposite direction | Based on importance |
| `DOMAIN_TENSION` | Different categories, opposite direction | Based on importance |
| `DATA_CONFLICT` | Same data source, disagreeing values | HIGH |

### Severity Rules
- Both importance > 1.0 → `CRITICAL`
- Either importance ≥ 1.0 → `HIGH`
- Otherwise → `MODERATE`

## Weighting Formula

```
importance = specialist_weight × confidence × verification_multiplier × source_quality_multiplier
```

### Verification Multipliers
| Status | Multiplier |
|--------|-----------|
| VERIFIED | 1.00 |
| PROVISIONAL | 0.85 |
| UNVERIFIED | 0.70 |
| CONFLICTED | 0.50 |

### Source Quality Multipliers
| Tier | Multiplier |
|------|-----------|
| TIER_1_PRIMARY_OFFICIAL | 1.00 |
| TIER_2_REGULATORY | 0.95 |
| TIER_3_LICENSED | 0.85 |
| TIER_4_SECONDARY | 0.75 |
| TIER_5_UNVERIFIED | 0.60 |

## Specialist Contribution Cap

Each specialist's directional contribution (bull or bear score) is capped at
**20% of total weight** to prevent a specialist with many metrics from
dominating the global score.

```
max_contribution = total_weight × 0.20
capped_contribution = min(raw_contribution, max_contribution)
```

## Confidence Calculation

```
base_conf = Σ(confidence × importance) / Σ(importance)

conflict_penalty = Σ penalty_for_severity(conflict)
  LOW      = 0.01
  MODERATE = 0.03
  HIGH     = 0.06
  CRITICAL = 0.10

missing_penalty = (specialists_failed + specialists_timed_out) × 0.10

final_confidence = clamp(base_conf - conflict_penalty - missing_penalty, 0.0, 1.0)
```

## PIT (Point-in-Time) Validation

Evidence timestamps are compared to the `MarketContext.data_timestamp`:
- Drift ≤ 48 hours → `PIT_CONSISTENT`
- Drift > 48 hours → `PIT_INCONSISTENT`
- No timestamp → `PIT_UNKNOWN`

`pit_inconsistent_count` is tracked in the package.

## Missing Data Categories

| Category | Trigger |
|----------|---------|
| `SPECIALIST_FAILED` | Agent state = FAILED |
| `SPECIALIST_TIMEOUT` | Agent state = TIMEOUT |
| `SPECIALIST_DEGRADED` | Agent state = DEGRADED |
| `METRIC_UNAVAILABLE` | Metric `available=False` |
| `PROVIDER_UNAVAILABLE` | Data provider unreachable |
| `DATA_CONFLICT` | Conflicting data sources |

## Configuration

Metric-to-category mapping and regime-to-direction mapping are stored in:
`backend/config/evidence_metric_config.json`

Business logic (formulas, thresholds, penalties) remains in Python code.

## Performance

All operations are O(n) where n = total evidence items:
- Single pass for extraction
- Single pass for PIT validation
- Grouping for agreements/conflicts is O(n) with hash maps
- No nested loops beyond pairwise conflict detection on regime items (bounded by 9 specialists = 81 max pairs)
