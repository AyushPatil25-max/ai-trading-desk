# Survivorship Bias Audit Report — Phase 5.4A

This document details the survivorship bias risks, constituent membership rules, and mitigation strategies for Indian equity backtests.

---

## 1. Survivorship Risk Finding

$$\textbf{SURVIVORSHIP\_BIAS\_RISK} = \textbf{TRUE}$$

### Root Cause
Without active automated ingestion of NSE semiannual index reconstitution circulars (e.g. historical additions like Adani Enterprises, LTIMindtree, Tata Consumer and deletions like GAIL, Vedanta, Yes Bank), evaluating Nifty 50 over historical years using today's active constituents introduces survivorship bias.

---

## 2. Mitigation Protocol

1. **Explicit Labeling:** All backtests run without point-in-time constituent reconstitution feeds are flagged with `SURVIVORSHIP_BIAS_RISK = TRUE`.
2. **Strategy Classification Impact:** Any backtest carrying survivorship bias is capped at `MIXED_INCONCLUSIVE` regardless of raw return metrics.
3. **Custom Universe Validation:** For clean survivorship-free testing, users must supply an explicit `UniverseConstituent` array with verified `effective_from` and `effective_to` dates.
