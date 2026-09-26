# Post-Roadmap Baseline Validation & Root-Cause Audit

**Date:** 2026-09-24  
**Scope:** Comprehensive read-only audit after completion of canonical roadmap (Phase 24)  
**Files changed during audit:** ZERO (read-only audit)

---

## 1. Executive Summary

The canonical product roadmap (Phases 1–24) is complete. This audit validates the
system's safety posture, correctness, data quality, frontend functionality, and
performance characteristics before beginning the post-roadmap hardening cycle.

**Key Findings:**
- **Safety:** All 8 safety invariants are SAFE. No live execution path is reachable.
- **Tests:** 2341 passed, 1 known failure (Phase 42 StateJournal gap), 25 warnings, 0 skipped.
- **Frontend:** COMPLETELY BROKEN — blank navigation and blank main content. Root cause
  identified precisely: `renderChart` ReferenceError in `app.js` line 22 kills the
  entire ES module, preventing DOM initialization. Additional blocking errors exist in
  `scanner.js`, `news.js`, and `chart.js`.
- **Data Quality:** 35 findings across 8 areas, including fabricated prices, fabricated
  dates, inverted quality metrics on failure, key name mismatches, and silent exception
  swallowing.
- **Analysis Accuracy:** Earnings engine permanently broken by key mismatch. AI quality
  engine inverts failures into 100% quality. Fundamental screening broken by type
  mismatch (`FinancialObservation` vs numeric).

---

## 2. Phase 24 Verification Result

### Files Inspected
| File | Status |
|------|--------|
| `backend/domain/production_intelligence_schemas.py` | Coherent, uses timezone-aware datetimes |
| `backend/application/production_intelligence_service.py` | Functional but has fabricated pipeline statuses |
| `backend/application/production_intelligence_routes.py` | 3 GET-only endpoints, no execution capability |
| `tests/test_production_intelligence_e2e.py` | 4 tests, all pass |
| `frontend/js/views/production_intelligence.js` | Correctly consumes `/api/production-intelligence/readiness` |
| `frontend/js/app.js` | Route registered once, import added |
| `backend/main.py` | Router included once at line 148 |
| `phase24_report.md` | Mostly accurate — see issues below |

### Phase 24 Issues Found

| Issue | Location | Severity |
|-------|----------|----------|
| Pipeline statuses hardcoded as HEALTHY with no actual check | `production_intelligence_service.py` L104-106 | P2 |
| `PipelineStatus.success_rate` defaults to 1.0 (fabricated) | `production_intelligence_schemas.py` L30 | P2 |
| `overall_status` only checks `components`, ignores `providers` | `production_intelligence_service.py` L117 | P2 |
| `/readiness` and `/status` both call `get_readiness()` making real network calls with no caching | `production_intelligence_routes.py` L12-13, L17 | P2 |
| `phase24_report.md` claims "UI verified locally" but UI is completely broken | `phase24_report.md` L38 | P1 |

---

## 3. Safety Verification

> **Overall Safety Posture: SAFE (PASS)**

| Invariant | Source | Default | Assessment |
|-----------|--------|---------|------------|
| `LIVE_EXECUTION_ENABLED` | `backend/config/app_config.py` L9, L45-52 | `False` | **SAFE** — read-only env var, no code path sets it |
| `EXECUTION_FREEZE_ACTIVE` | `production_intelligence_service.py` L110 | `"true"` | **SAFE** — read-only env var |
| `ExecutionGuard` | `backend/application/execution_guard.py` L29-239 | Fail-closed | **SAFE** — blocks live broker, validates all 8 gates |
| Phase 24 routes | `production_intelligence_routes.py` L1-26 | GET-only | **SAFE** — zero order/execution capability |
| Dhan broker isolation | `backend/adapters/dhan_adapter.py` | Isolated | **SAFE** — zero imports from intelligence/analysis layers |
| Upstox scope | `market_data_provider.py`, `broker_interface.py` L222-237 | Data-only | **SAFE** — explicitly blacklisted as trading broker |
| StateJournal integrity | `backend/data/journal/state_journal.jsonl` | Untouched | **SAFE** — `git diff` confirms zero changes |
| Test safety | All test files | Fully mocked | **SAFE** — all broker HTTP calls use `@patch`/`MagicMock` |

---

## 4. Full Regression Result

```
Phase 24 targeted: 4 passed, 0 failed, 1 warning (10.78s)
Full regression:    2341 passed, 1 failed, 25 warnings (316.64s)
Skipped:            0
```

### Warnings (25 total)
- `StarletteDeprecationWarning`: Using `httpx` with `starlette.testclient` (1x)
- `PydanticDeprecatedSince20`: `.dict()` → `.model_dump()` (12x across certification_routes, research_chat_service, research_workspace_service)
- `DeprecationWarning`: `datetime.utcnow()` deprecated (12x across research_chat_service, research_workspace_service)

---

## 5. Exact Known Phase 42 Failure

```
FAILED tests/test_phase42_production_activation.py::TestPhase42ProductionActivation::test_production_certification_engine_development_ready
```

**Known Issue:** Journal sequence gap at index 533: expected 533, got 529.

This is a pre-existing StateJournal integrity issue. Per instructions, the StateJournal
was NOT modified to make this test pass. No certification logic was altered.

---

## 6. Additional Failures

**NONE.** The only failure is the known Phase 42 test above.

---

## 7. Website/UI Runtime Result

> **STATUS: COMPLETELY BROKEN — Blank navigation and blank main content**

### Root Cause Chain (Precise)

```
1. Browser GETs http://127.0.0.1:8000/
   └── FastAPI returns frontend/index.html (200 OK)

2. Browser parses HTML, renders static shell
   ├── <nav id="mainNav"><!-- EMPTY --></nav>
   └── <div id="viewContainer"><!-- EMPTY --></div>

3. Browser loads <script type="module" src="/static/js/app.js">
   └── FastAPI /static mount → frontend/ directory
       └── /static/js/app.js → frontend/js/app.js ✓

4. ES Module Graph Resolution Phase
   ├── [BLOCKER 1] scanner.js exports class ScannerView, NOT renderScanner
   │   └── SyntaxError: module does not provide export named 'renderScanner'
   ├── [BLOCKER 2] news.js has missing template backticks on HTML
   │   └── SyntaxError: Unexpected token '<'
   └── [BLOCKER 3] chart.js has broken syntax (bare backslash + raw HTML)

5. IF module linking somehow proceeded to execution...
   ├── Line 6: // import { renderChart } from './views/chart.js';  ← commented out
   └── Line 22: { ..., render: renderChart }  ← UNDEFINED identifier
       └── ReferenceError: renderChart is not defined
           └── KILLS entire module execution at line 22

6. Consequences
   ├── initNav() NEVER defined
   ├── window.navigateTo() NEVER defined
   ├── DOMContentLoaded listener NEVER registered
   ├── #mainNav remains EMPTY
   └── #viewContainer remains EMPTY
```

### Duplicate Frontend Trees
- `frontend/js/` — exists (sole frontend tree)
- `frontend/static/js/` — does NOT exist
- No duplication issue

### Static Mount Path
- `app.mount("/static", StaticFiles(directory="frontend/"))` at `backend/main.py` L51
- `/static/js/app.js` correctly resolves to `frontend/js/app.js`
- Path resolution is correct; the issue is purely JavaScript errors

---

## 8. Frontend Root Cause

**Primary:** `renderChart` is referenced on `app.js` line 22 but its import is commented
out on line 6. This is a `ReferenceError` that kills module-level execution.

**Secondary (would block even if primary were fixed):**
- `scanner.js` exports `class ScannerView` but `app.js` imports `renderScanner` (named
  export mismatch)
- `news.js` has missing template literal backticks around raw HTML
- `chart.js` has a bare backslash and raw HTML without backticks (original reason
  the import was commented out)

**Fix requires:** At minimum, fixing the `renderChart` reference (uncomment import or
remove from routes) AND fixing `scanner.js` export name AND fixing `news.js` template
syntax.

---

## 9. Data Quality Findings

### Critical (HIGH Risk)

| # | Finding | Location | Risk |
|---|---------|----------|------|
| 1 | **RBI Provider hardcodes static macro data** (2023-24 rates) but marks as `TIER_1_PRIMARY_OFFICIAL`, `VERIFIED`, with fresh `publication_time=now` | `rbi_provider.py` L22-104 | HIGH |
| 2 | **AI Quality Engine inverts failure into 100% quality**: LLM crash → empty claims → `HIGH_QUALITY` + `coverage=100.0%` | `ai_quality_engine.py` L46-48, L124 | HIGH |
| 3 | **Opportunity Scanner fabricates prices**: Missing data → synthetic `current_price=1560.0`, `RSI=58.0`, 30 fake bars | `opportunity_scanner.py` L491-516 | HIGH |
| 4 | **Execution routes fabricate prices and ticks**: `entry_price = limit_price or 1000.0`, injects `last_traded_price: 100.0` | `execution_routes.py` L107-132 | HIGH |
| 5 | **Historical research has lookahead bias**: Fetches live TTM fundamentals for historical `as_of` date; defaults `current_price=1.0` | `historical_research_service.py` L54-61 | HIGH |
| 6 | **YFinance fabricates filing/announcement dates**: Uses arbitrary offsets (`+45d`, `-15d`, `-60d`) for dates Yahoo doesn't provide | `yfinance_provider.py` L313-478 | HIGH |
| 7 | **OHLCV replaces missing prices with 0.0**: `_safe_float(row.get("Open")) or 0.0` converts NaN to zero | `orchestrator.py` L273-277 | HIGH |
| 8 | **Orchestrator marks quality OK despite component failures**: Status is OK if `consensus_price > 0`, even with all other data missing | `orchestrator.py` L152-156 | HIGH |
| 9 | **Research synthesis does NOT validate LLM evidence IDs**: Prompt says "don't fabricate" but zero post-validation | `research_synthesis_engine.py` L51-61 | HIGH |
| 10 | **Chat service returns unvalidated LLM evidence_refs** directly to user | `research_chat_service.py` L121-158 | HIGH |
| 11 | **Bull/bear engine fabricates TIER_1 authority** for derived calculations and reports `LOW` risk when evidence is empty | `bull_bear_engine.py` L95-102, L177-183 | HIGH |
| 12 | **Silent exception swallowing** in orchestrator (10+ bare `except Exception: continue` without logging), Dhan audit chain, earnings engine (`except: pass`) | Multiple files | HIGH |
| 13 | **BSE symbol suffix `.BO` never appended** — BSE queries resolve wrong securities | `market_data_provider.py` L42-44 | HIGH |

### Medium Risk

| # | Finding | Location | Risk |
|---|---------|----------|------|
| 14 | NSE/BSE/SEBI/CompanyFilings providers are non-functional stubs returning ERROR | 4 provider files | MEDIUM |
| 15 | `datetime.utcnow()` deprecated; creates naive timestamps vs. aware timestamps elsewhere | `research_chat_service.py`, `research_workspace_service.py` (12x) | MEDIUM |
| 16 | `datetime.now()` without timezone in market_data_provider, ipo_engine | Multiple files | MEDIUM |
| 17 | Hardcoded naive fallback dates `datetime(2023,1,1)` in validation engines | `walk_forward.py`, `empirical_runner.py` | MEDIUM |
| 18 | Public shareholding derived as `100 - (promoter + institutional)` ignoring other categories | `yfinance_provider.py` L514-530 | MEDIUM |
| 19 | SecurityMaster synthesizes fake definitions for unknown tickers | `security_master.py` L203-215 | MEDIUM |
| 20 | Market data provider masks fundamental failures with SecurityMaster metadata | `market_data_provider.py` L83-92 | MEDIUM |

---

## 10. Analysis Accuracy Findings

| # | Finding | Impact |
|---|---------|--------|
| 1 | **Earnings engine key mismatch** — queries `res.data.get("statements")` but provider stores as `"quarterly_statements"`. Earnings always returns UNAVAILABLE. | Earnings analysis completely non-functional |
| 2 | **Fundamental screening type mismatch** — screener compares `FinancialObservation` objects against numeric thresholds. `TypeError` caught silently, criterion marked "failed". | Fundamental screening via intelligent screener is broken |
| 3 | **Stock comparison same type mismatch** — `isinstance(v[1], (int, float))` fails for `FinancialObservation`, all fundamentals discarded as non-numeric | Fundamental comparison always reports "Incomparable" |
| 4 | **Stock comparison inverted winner logic** — unconditionally assigns `winner_symbol = max`. For debt/PE/volatility, labels worst as "winner" | Misleading comparison results |
| 5 | **AI quality claim validation overly permissive** — 50% word overlap (>4 chars) marks non-numeric claims as SUPPORTED regardless of negation/context | False positive claim validation |
| 6 | **Portfolio engine fabricates equity=1.0** when equity is missing/zero, then computes percentages relative to ₹1 | Meaningless percentage calculations |
| 7 | **Portfolio diversification defaults to 0.50** when correlation data is missing | Fabricated diversification score |
| 8 | **Research synthesis accepts hallucinated evidence IDs** from LLM without post-validation | Users see non-existent evidence references |

---

## 11. Performance Findings

| # | Finding | Location | Severity |
|---|---------|----------|----------|
| 1 | `ProductionIntelligenceService.get_readiness()` makes real YFinance + LLM calls on EVERY request with no caching or TTL | `production_intelligence_service.py` L46-100 | P2 |
| 2 | `/api/production-intelligence/status` redundantly calls `get_readiness()` which duplicates the `/readiness` endpoint work | `production_intelligence_routes.py` L15-25 | P3 |
| 3 | `IntelligentScreenerEngine` calls `get_market_context()` per-symbol sequentially in a loop (N+1 pattern) | `intelligent_screener_engine.py` L149 | P2 |
| 4 | `StockComparisonEngine` same N+1 pattern per-symbol | `stock_comparison_engine.py` L84 | P2 |
| 5 | `OpportunityScanner` constructs full MarketContext per candidate without batching | `opportunity_scanner.py` L489 | P2 |
| 6 | Duplicate `YFinanceProvider` class exists in legacy `data_providers.py` (unused but confusing) | `backend/infrastructure/data_providers.py` L41 | P3 |
| 7 | Duplicate `MarketDataProvider` ABC in `data_providers.py` vs `IMarketDataProvider` in `market_data_provider.py` | Two files | P3 |

---

## 12. Duplicate/Dead Implementation Findings

| Item | Location | Status |
|------|----------|--------|
| Legacy `YFinanceProvider` class | `backend/infrastructure/data_providers.py` L41 | Dead code — newer one in `providers/yfinance_provider.py` |
| Legacy `MarketDataProvider` ABC | `backend/infrastructure/data_providers.py` L10 | Dead code — newer `IMarketDataProvider` in `providers/market_data_provider.py` |
| NSEProvider stub | `backend/infrastructure/providers/nse_provider.py` | Non-functional, always returns ERROR |
| BSEProvider stub | `backend/infrastructure/providers/bse_provider.py` | Non-functional, always returns ERROR |
| SEBIProvider stub | `backend/infrastructure/providers/sebi_provider.py` | Non-functional, always returns ERROR |
| CompanyFilingsProvider stub | `backend/infrastructure/providers/company_filings_provider.py` | Non-functional, always returns ERROR |
| Duplicate `GET /api/system/health/readiness` routes | `certification_routes.py` L61 and L77 | Registered twice with different function names |
| Unused views: `dashboard.js`, `opportunities.js`, `risk.js`, `system.js` | `frontend/js/views/` | Not imported in `app.js`, unreachable |
| Deleted test file | `tests/test_phase48_news.py` | Marked `D` in git — intentional deletion |

---

## 13. Prioritized Defects

### P0 — Safety/Correctness Blockers

| ID | Defect | Impact |
|----|--------|--------|
| P0-1 | **Frontend completely broken** — `renderChart` ReferenceError + `scanner.js` export mismatch + `news.js`/`chart.js` syntax errors kill entire app.js module | Website is non-functional: blank nav, blank content |
| P0-2 | **AI quality engine inverts failures into 100% quality** — LLM crash → `HIGH_QUALITY` + `coverage=100.0%` | Users trust fabricated quality assessments |

### P1 — Major Functional/Data-Quality Issues

| ID | Defect | Impact |
|----|--------|--------|
| P1-1 | **Earnings engine key mismatch** (`"statements"` vs `"quarterly_statements"`) | Earnings analysis permanently UNAVAILABLE |
| P1-2 | **Fundamental screening type mismatch** — `FinancialObservation` vs numeric comparison | Fundamental screener filters never match |
| P1-3 | **Stock comparison type mismatch + inverted winner** | Comparison results misleading/empty |
| P1-4 | **Research synthesis accepts hallucinated evidence IDs** from LLM | Users see fabricated evidence references |
| P1-5 | **Chat service returns unvalidated evidence_refs** | Same hallucination risk exposed to users |
| P1-6 | **Opportunity scanner fabricates synthetic MarketContext** (price=1560, RSI=58, 30 fake bars) | Scanner produces fabricated analysis |
| P1-7 | **Historical research has lookahead bias** — fetches live fundamentals for past dates, defaults price=1.0 | Backtest results are invalid |
| P1-8 | **RBI provider hardcodes stale data as TIER_1 VERIFIED with fresh timestamps** | Misleading macro data provenance |
| P1-9 | **Bull/bear engine reports LOW risk when evidence is empty** instead of UNKNOWN | Silence misinterpreted as safety |
| P1-10 | **BSE symbol suffix `.BO` never appended** | BSE queries resolve wrong securities |
| P1-11 | **phase24_report.md claims UI verified but UI is completely broken** | Incorrect documentation |

### P2 — Meaningful Quality/Performance/UI Issues

| ID | Defect | Impact |
|----|--------|--------|
| P2-1 | Pipeline statuses hardcoded HEALTHY with fabricated success_rate=1.0 | Misleading health dashboard |
| P2-2 | `overall_status` ignores provider failures | Incomplete health assessment |
| P2-3 | Production intelligence readiness makes uncached real API calls per request | Performance on every page load |
| P2-4 | AI quality claim validation overly permissive (50% word overlap) | False positive claim support |
| P2-5 | Portfolio equity defaults to 1.0, diversification to 0.50 when data missing | Fabricated portfolio metrics |
| P2-6 | N+1 pattern in screener/comparison/scanner (sequential per-symbol) | Slow for multi-symbol operations |
| P2-7 | OHLCV replaces NaN with 0.0 instead of filtering/marking | Corrupts technical indicators |
| P2-8 | Orchestrator marks OK if price > 0 regardless of other failures | Over-optimistic quality reporting |
| P2-9 | YFinance fabricates filing/announcement dates with arbitrary offsets | Misleading financial event dates |
| P2-10 | Execution routes fabricate prices (1000.0) and inject fake ticks (100.0) | Pre-flight validation bypass |
| P2-11 | SecurityMaster synthesizes fake definitions for unknown tickers | Invalid tickers pass validation |
| P2-12 | Market data provider masks fundamental failures with SecurityMaster metadata | Indistinguishable failures |
| P2-13 | `datetime.utcnow()` deprecated, creates naive timestamps (12 instances) | Timezone comparison crashes |

### P3 — Minor Cleanup

| ID | Defect | Impact |
|----|--------|--------|
| P3-1 | Pydantic `.dict()` deprecated → `.model_dump()` (12 instances) | Will break in Pydantic v3 |
| P3-2 | Duplicate `YFinanceProvider` and `MarketDataProvider` in legacy `data_providers.py` | Confusion, maintenance burden |
| P3-3 | Non-functional provider stubs (NSE, BSE, SEBI, CompanyFilings) | Dead code |
| P3-4 | Duplicate `GET /api/system/health/readiness` in certification_routes | Route collision |
| P3-5 | Unused frontend views (dashboard.js, opportunities.js, risk.js, system.js) | Dead code |
| P3-6 | Silent `except: pass` in earnings_engine, chart_service, news_engine | Impossible to debug |
| P3-7 | Silent `except Exception: continue` in orchestrator (10+ instances) | Provider errors invisible |
| P3-8 | `/status` redundantly duplicates `/readiness` computation | Unnecessary API cost |
| P3-9 | Hardcoded naive fallback dates in validation engines | Timezone crash risk |

---

## 14. Recommended Fix Order

1. **P0-1 (Frontend):** Fix the 4 blocking JS errors to restore the website to a functional state
2. **P0-2 (AI Quality Inversion):** Fix empty-claims-path to report UNAVAILABLE instead of HIGH_QUALITY
3. **P1-1 (Earnings Key Mismatch):** Single-line fix: `"statements"` → `"quarterly_statements"`
4. **P1-2, P1-3 (Type Mismatch):** Extract `.value` from `FinancialObservation` before numeric comparison
5. **P1-4, P1-5 (Evidence Hallucination):** Add post-validation of LLM evidence IDs against actual evidence pool
6. **P1-6 (Scanner Fabrication):** Replace fabricated MarketContext with explicit UNAVAILABLE status
7. **P1-7 (Lookahead Bias):** Use point-in-time fundamentals or mark as unavailable for historical research
8. **P1-9 (Bull/Bear Empty Data):** Return UNKNOWN/INSUFFICIENT_DATA instead of LOW risk
9. **P2-1 through P2-13:** Address in priority order during hardening cycle
10. **P3-x:** Address during cleanup pass

---

## Verification Metadata

```
Full regression run:     2341 passed, 1 failed, 0 skipped, 25 warnings
Known failure:           test_phase42...test_production_certification_engine_development_ready
                         (Journal sequence gap at index 533: expected 533, got 529)
Phase 24 targeted:       4 passed, 0 failed
StateJournal:            UNMODIFIED (git diff confirms)
Files changed by audit:  ZERO
Website status:          BROKEN (blank nav + blank content)
Frontend root cause:     renderChart ReferenceError + scanner.js/news.js/chart.js syntax errors
```

---

**BASELINE AUDIT COMPLETE**
