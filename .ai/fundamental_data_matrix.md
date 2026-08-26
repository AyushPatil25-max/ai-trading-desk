# Fundamental Data Matrix

This document tracks the explicit deterministic mapping of fundamental data fields from Multi-Source Providers into the Point-in-Time Data Trust Layer.

## Core Schemas

*   **FinancialObservation**: Represents a single point-in-time numerical fact (e.g., Q3 2024 Revenue).
*   **CorporateDocument**: Represents a filing, announcement, or transcript metadata.

### Data Freshness Categories
1.  **FRESH**: Report date is within `max_stale_days` (default 180).
2.  **STALE**: Report date is older than `max_stale_days`.
3.  **UNAVAILABLE**: Data is missing or unparseable.

### Core Metrics Tracked & Normalized

| Metric Name            | Statement       | Origin          | Fallback / Calc. Method           |
|------------------------|-----------------|-----------------|-----------------------------------|
| `revenue`              | Income Stmt     | Provider direct | N/A                               |
| `gross_profit`         | Income Stmt     | Provider direct | N/A                               |
| `operating_profit`     | Income Stmt     | Provider direct | `revenue` * `operatingMargins`    |
| `net_income`           | Income Stmt     | Provider direct | N/A                               |
| `eps`                  | Income Stmt     | Provider direct | N/A                               |
| `cash`                 | Balance Sheet   | Provider direct | N/A                               |
| `total_debt`           | Balance Sheet   | Provider direct | N/A                               |
| `total_equity`         | Balance Sheet   | Provider direct | N/A                               |
| `operating_cash_flow`  | Cash Flow Stmt  | Provider direct | N/A                               |
| `capex`                | Cash Flow Stmt  | Provider direct | N/A                               |
| `free_cash_flow`       | Cash Flow Stmt  | Calc. Formula   | `operating_cash_flow` - `capex`   |
| `shares_outstanding`   | Key Statistics  | Provider direct | N/A                               |

## Guardrails
- **NaN / Inf**: Automatically rejected during calculation (evaluates to unavailable).
- **Negative Base Rules**: Gross Margin or Operating Margin where Revenue <= 0 is rejected as invalid/non-computable.
- **Double Counting Prevention**: If FCF is directly available, it is preserved. Otherwise, standard deterministic formula is applied with proper provenance.

## Provider Support
- **YFinance**: Full TTM fallback support.
- **NSE / BSE**: Stubbed interfaces. Data unavailable without authenticated credentials.
