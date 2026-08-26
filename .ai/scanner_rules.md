# Scanner & Ranking Rules — Phase 5.3

This document details the candidate ranking formula, data quality scoring, evidence-availability weighting, and sector diversification rules.

---

## 1. Candidate Opportunity Scoring Formula

Let $K$ be the set of available specialist domains for candidate stock $s$, with weights $W_k$ defined in `backend/config/scanner_config.json`:

$$\text{Raw Weighted Score}(s) = \frac{\sum_{k \in K} W_k \cdot \text{Score}_k(s)}{\sum_{k \in K} W_k}$$

### Data Quality Penalty Factor
Let $\text{DQ}(s) \in [0, 100]$ be the data quality score, and $\lambda = \text{data\_quality\_penalty\_weight} = 0.30$:

$$\text{DQ Factor}(s) = (1.0 - \lambda) + \lambda \times \left( \frac{\text{DQ}(s)}{100.0} \right)$$

### Effective Opportunity Score
$$\text{Effective Score}(s) = \text{Raw Weighted Score}(s) \times \text{DQ Factor}(s)$$

---

## 2. Data Quality Score Breakdown

| Feature | Score Contribution | Condition |
|---|---|---|
| **OHLCV History** | $+25$ points | $\ge \text{min\_historical\_bars}$ present |
| **Technical Indicators** | $+15$ points | Moving averages and RSI calculated |
| **Fundamental Disclosures** | $+25$ points | Income statement or ratios present |
| **News Stream** | $+15$ points | Published articles within PIT window |
| **Institutional Flows** | $+20$ points | FII/DII flow observations available |
| **Max Score** | **100 points** | Complete multi-modal data package |

---

## 3. Sector Concentration Constraint

During Top-K selection:
- Candidates are sorted descending by `Effective Score(s)`.
- A sector count map $\text{Count}[\text{sector}]$ is tracked.
- If $\text{Count}[\text{candidate.sector}] \ge \text{max\_candidates\_per\_sector}$ (default = 2), candidate is rejected with `REJECTED_SECTOR_CONCENTRATION`.
- Selection stops when $K$ candidates are chosen or candidate pool is exhausted.
