# Point-In-Time (PIT) Replay Rules — Phase 5.2

This document defines the strict Point-In-Time guarantees enforced during historical paper trading simulations to eliminate look-ahead bias.

---

## 1. Modality Filtering Rules

At simulation timestamp $T$:

| Modality | Timestamp Field | Rule | Violation Behavior |
|---|---|---|---|
| **OHLCV Price Action** | `bar.timestamp` / `bar.date` | $\text{timestamp} \le T$ | Excluded from context |
| **Financial Statements** | `publication_time` / `filing_date` / `effective_time` | $\text{publication\_time} \le T$ | Excluded from fundamental payload |
| **Corporate Disclosures**| `doc.publication_time` | $\text{publication\_time} \le T$ | Excluded from documents list |
| **News Articles** | `article.published_at` / `timestamp` | $\text{published\_at} \le T$ | Excluded from news payload |
| **Institutional Flows** | `flow.observed_at` | $\text{observed\_at} \le T$ | Excluded from institutional payload |
| **Shareholding Patterns**| `pattern.observed_at` | $\text{observed\_at} \le T$ | Excluded from ownership payload |
| **Bulk/Block Deals** | `deal.execution_time` | $\text{execution\_time} \le T$ | Excluded from deals payload |
| **Delivery Data** | `delivery.observed_at` | $\text{observed\_at} \le T$ | Excluded from delivery payload |

---

## 2. Missing Timestamp Guarantees

If an observation has a missing or unparseable timestamp:
- The observation is marked unavailable and excluded from the slice.
- It is **never** assumed to be available at $T$.

---

## 3. Current Price Determination

- `MarketContext.current_price` is determined by the `close` price of the latest filtered OHLCV bar where $\text{bar\_timestamp} \le T$.
- `MarketContext.data_timestamp` is set explicitly to $T$.
