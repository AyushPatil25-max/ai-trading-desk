# Phase 4.1A — Evidence Integrity & Aggregation Hardening Report

**Status:** ✅ COMPLETE
**Date:** 2026-08-24
**Baseline:** 425 / 425 tests
**Final:** 451 / 451 tests (26 new, 0 regressions)

---

## Files Created

| File | Purpose |
|------|---------|
| `backend/config/evidence_metric_config.json` | Central JSON config mapping specialist metrics to categories and evidence types |
| `tests/test_evidence_aggregator_hardening.py` | 26 offline unit tests for Phase 4.1A |
| `.ai/evidence_aggregation_design.md` | Updated design document |
| `.ai/phase_4_1a_report.md` | This report |

## Files Modified

| File | Changes |
|------|---------|
| `backend/application/evidence_aggregator.py` | Complete rewrite: multi-evidence extraction, duplicate detection, metric/domain agreements, typed conflicts, evidence-aware weighting, specialist caps, PIT validation, structured missing data |
| `backend/domain/schemas.py` | Added: `MissingDataCategory`, `ConflictType`, `AgreementLevel`, `PITStatus` enums; `MissingDataRecord` model; extended `NormalizedEvidence` (source_evidence_id, pit_status, duplicate_key), `EvidenceConflict` (conflict_type), `EvidenceAgreement` (level), `UnifiedEvidencePackage` (missing_data_records, duplicates_detected, pit_inconsistent_count, total_evidence_extracted) |
| `tests/test_evidence_aggregator.py` | Updated `test_5_numerical_weighting_test` expected confidence from 0.65714 → 0.58714 (evidence-aware penalty schedule) |

---

## Evidence Extraction Coverage (All 9 Specialists)

| Specialist | Regime Key | Evidence List Key | Metric Name Key | Metrics Discovered |
|-----------|-----------|------------------|-----------------|-------------------|
| Technical | `trend` | `evidence` | `name` | CurrentPrice, EMA20, EMA50, RSI14, 20DayHigh |
| Momentum | `momentum_direction` | `evidence` | `name` | Price_vs_EMA20, Price_vs_EMA50, EMA_Spread_20_50, RSI14, Distance_From_20D_High, MACD_Histogram |
| Quant | `statistical_regime` | `metrics` | `metric_name` | 14 metrics (cumulative_return_5d, realized_volatility_5d, price_range_5d_pct, avg_volume_5d, price_zscore_5d, return_mean_5d, trend_consistency_5d, ema_spread_pct, rsi_extremity, realized_volatility_20d, max_drawdown_20d, sharpe_ratio_annualized, sortino_ratio_annualized, rolling_vol_20d) |
| Fundamental | `fundamental_quality` | `metrics` | `metric_name` | 17 metrics (gross_margin, operating_margin, net_margin, revenue_growth_yoy, eps_growth_yoy, debt_to_equity, current_ratio, return_on_equity, free_cash_flow, pe_ratio, revenue, net_income, eps, operating_cash_flow, total_debt, cash_and_equivalents, total_equity) |
| Valuation | `valuation_status` | `evidence` | `metric_name` | 6 metrics (pe_ratio, ps_ratio, pb_ratio, ev_ebitda, fcf_yield, peg_ratio) |
| Sector | `sector_regime` | `evidence` | `metric_name` | 6 metrics (company_return, sector_return, benchmark_return, relative_to_sector, relative_to_benchmark, sector_to_benchmark_spread) |
| Macro | `macro_regime` | `evidence` | `metric_name` | 7 metrics (policy_rate, inflation_rate, real_rate, treasury_10y, treasury_2y, yield_spread_10y_2y, gdp_growth) |
| News | `news_regime` | `articles` | `headline` | N articles (dynamic, per news feed) |
| Institutional | `institutional_regime` | `evidence` | `metric_name` | N metrics (fii_net_flow, dii_net_flow, combined_net_flow, promoter_ownership, promoter_ownership_change, promoter_pledge_percentage, delivery_percentage, bulk_deal_count, block_deal_count) |

---

## Weighting Formula

```
importance = specialist_weight × confidence × verification_multiplier × source_quality_multiplier
```

- Specialist weights: TECHNICAL=1.0, MOMENTUM=0.9, QUANT=1.0, FUNDAMENTAL=1.2, VALUATION=1.1, SECTOR=0.9, MACRO=0.8, NEWS=0.7, INSTITUTIONAL=1.0
- Verification: VERIFIED=1.0, PROVISIONAL=0.85, UNVERIFIED=0.7, CONFLICTED=0.5
- Source quality: TIER_1=1.0, TIER_2=0.95, TIER_3=0.85, TIER_4=0.75, TIER_5=0.6

## Confidence Formula

```
base_conf = Σ(confidence × importance) / Σ(importance)
conflict_penalty = Σ per_severity_penalty  (LOW=0.01, MODERATE=0.03, HIGH=0.06, CRITICAL=0.10)
missing_penalty = (failed + timed_out) × 0.10
final = clamp(base_conf - conflict_penalty - missing_penalty, 0, 1)
```

## Conflict Logic

| Type | Trigger | Default Severity |
|------|---------|-----------------|
| DIRECT_CONFLICT | Same category, opposite direction | Based on importance |
| DOMAIN_TENSION | Different categories, opposite direction | Based on importance |
| DATA_CONFLICT | Same data source disagrees | HIGH |

Severity rules: both importance > 1.0 → CRITICAL; either ≥ 1.0 → HIGH; else MODERATE.

## PIT Validation

- Tolerance: ±48 hours from MarketContext.data_timestamp
- Within tolerance → `PIT_CONSISTENT`
- Outside tolerance → `PIT_INCONSISTENT` (flagged, not dropped)
- No timestamp → `PIT_UNKNOWN`

## Provenance Traceability

Each `NormalizedEvidence` item preserves:
- `source` (data provider name)
- `source_tier` (TIER_1..TIER_5)
- `verification_status` (VERIFIED/PROVISIONAL/UNVERIFIED/CONFLICTED)
- `context_id` (MarketContext trace)
- `data_timestamp` (observation time)
- `calculation_method` (formula used)
- `source_evidence_id` (optional link to parent evidence)
- `pit_status` (PIT validation result)

Values are **never overwritten** when the specialist already provides them.

---

## Tests

| Category | Count | Status |
|----------|-------|--------|
| Original tests (Phase 4.1) | 425 | ✅ All passing |
| New hardening tests | 26 | ✅ All passing |
| **Total** | **451** | ✅ **All passing** |

### Fixes Performed
1. `test_5_numerical_weighting_test`: Updated expected confidence from `0.65714` → `0.58714` to reflect evidence-aware penalty schedule (HIGH=0.06, CRITICAL=0.10 vs old flat 0.05)

### New Test Coverage

| Test | Coverage Area |
|------|--------------|
| test_01 | Multi-metric extraction (Quant, 3 metrics) |
| test_02 | Multi-metric extraction (Technical, 3 indicators) |
| test_03 | Duplicate detection |
| test_04 | Domain-level agreement |
| test_05 | Metric-level agreement |
| test_06 | DIRECT_CONFLICT taxonomy |
| test_07 | DOMAIN_TENSION vs DIRECT_CONFLICT |
| test_08 | Evidence-aware weighting formula |
| test_09 | Specialist contribution cap |
| test_10 | PIT consistency (valid) |
| test_11 | PIT inconsistency detection |
| test_12 | Missing data — SPECIALIST_FAILED |
| test_13 | Missing data — SPECIALIST_TIMEOUT |
| test_14 | Missing data — SPECIALIST_DEGRADED |
| test_15 | Missing data — METRIC_UNAVAILABLE |
| test_16 | Evidence type — DETERMINISTIC_FACT |
| test_17 | Evidence type — DETERMINISTIC_CALCULATION |
| test_18 | Provenance preservation (source_tier, verification) |
| test_19 | Confidence penalty (HIGH severity) |
| test_20 | Determinism (identical input → identical output) |
| test_21 | Backward compatibility (all 9 unanimous) |
| test_22 | Full integration (rich multi-specialist evidence) |
| test_23 | Empty run result |
| test_24 | Context ID mismatch |
| test_25 | Valuation metrics extraction |
| test_26 | total_evidence_extracted field |

---

## Performance

- All operations O(n) where n = evidence items
- Pairwise conflict detection bounded by 9 specialists (max 81 regime-level pairs)
- Metric-level grouping uses hash maps
- No network calls, no LLM calls

## Backward Compatibility

- All existing `NormalizedEvidence`, `EvidenceConflict`, `EvidenceAgreement`, and `UnifiedEvidencePackage` fields retained
- New fields have backward-compatible defaults
- Existing bull/bear/neutral signal lists still populated
- Existing confidence/regime calculation logic preserved (with improved penalty schedule)

---

## Remaining Limitations

1. **News articles** are treated as individual evidence items (by headline) — no semantic deduplication across providers
2. **DATA_CONFLICT** type is defined but not yet triggered (requires multi-source data comparison)
3. **Metric-level direction inference** uses simple keyword matching on `interpretation` field — could be enhanced with more nuanced rules
4. **Specialist contribution cap** is a fixed 20% — could be made configurable
5. **PIT drift tolerance** is fixed at 48 hours — could vary by data type

## Next Phase Recommendation

**Phase 4.2: Bull/Bear/Risk Agent Layer**
- Consume `UnifiedEvidencePackage` to build bullish/bearish/risk arguments
- Use evidence taxonomy to weight deterministic vs interpretive signals
- Leverage provenance chain for credibility assessment
