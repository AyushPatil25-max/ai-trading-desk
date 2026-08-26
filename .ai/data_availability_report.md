# Data Availability & Provider Audit — Phase 5.4A

This document audits the real historical data availability, source tiers, authentication constraints, and data depths across all 8 market modalities.

---

## 1. Provider Availability Matrix

| Dataset | Provider Name | Source Tier | Auth Required | Historical Depth | PIT Quality | Limitations |
|---|---|---|---|---|---|---|
| **OHLCV Bars & Quotes** | `yfinance` | Tier 4 (Secondary) | No | 10+ years daily | High (Frozen at close) | Secondary aggregator; unadjusted split checks required |
| **Official Bhavcopy & Delivery** | `NSE_Official` | Tier 1 (Official) | Yes | Full Archive | Primary Official | Requires active enterprise data feed credentials |
| **Financial Statements & Ratios** | `yfinance / Disclosures` | Tier 4 (Secondary) | No | 4-5 quarters | Medium (Filing lag enforced) | Requires strict publication-time filtering |
| **Corporate Disclosures & Filings** | `BSE / NSE Corporate` | Tier 1 (Official) | Yes | Multi-year | Primary Official | Exchange feed required for real-time archives |
| **Institutional Flows (FII/DII)** | `SEBI / NSE Reports` | Tier 2 (Regulatory) | No | 2020 to Present | Regulatory Official | Security-specific holdings reported quarterly |
| **Macro Indicators (Repo, CPI)** | `RBI / MoSPI` | Tier 1 (Official) | No | 2015 to Present | Primary Official | Bimonthly MPC and monthly release cycles |
| **News Streams** | `yfinance News / RSS` | Tier 4 (Secondary) | No | 30-90 days rolling | Medium | Deep historical news requires news vendor subscription |
| **Universe Constituents** | `NSE Index Services` | Tier 1 (Official) | No | 2020 to Present | Primary Official | Static lists introduce survivorship bias risk |
