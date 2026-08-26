# Point-In-Time Leakage Detection Specification — Phase 5.4

This document defines the automated programmatic checks enforced by `LeakageDetector` to guarantee zero look-ahead bias during strategy validation.

---

## 1. Leakage Categories & Severity Classifications

| Modality | Checked Timestamp | Constraint at Decision Time $T$ | Severity on Breach | Action on Breach |
|---|---|---|---|---|
| **OHLCV Price Action** | `bar.timestamp` | $\le T$ | **CRITICAL** | Invalidate Window & Fail Scorecard |
| **Financial Disclosures** | `publication_time` | $\le T$ | **CRITICAL** | Invalidate Window & Fail Scorecard |
| **Universe Constituents** | `constituent.effective_from` | $\le T$ | **CRITICAL** | Invalidate Window & Fail Scorecard |
| **News Stream** | `article.published_at` | $\le T$ | **HIGH** | Exclude Article & Log Finding |
| **Institutional Flows** | `observation.observed_at` | $\le T$ | **HIGH** | Exclude Flow & Log Finding |
| **Corporate Filings** | `document.publication_time` | $\le T$ | **HIGH** | Exclude Document & Log Finding |
| **Benchmark Bars** | `benchmark_bar.timestamp` | $\le T$ | **HIGH** | Exclude Bar & Log Finding |

---

## 2. Invalidation Protocol

- Any **CRITICAL** leakage finding automatically sets `WalkForwardWindow.is_valid = False` and zeroes the `data_quality_score` on the `ValidationScorecard`.
- The system prevents claiming investment viability on tainted historical datasets.
