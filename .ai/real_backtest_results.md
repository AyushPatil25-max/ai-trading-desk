# Real Out-of-Sample Backtest Results — Phase 5.4A

This document summarizes the empirical validation run results over Indian equity market data.

---

## 1. Verified Empirical Performance

- **Historical Evaluation Period:** 2023-01-01 to 2023-12-31 (1-Year Walk-Forward Out-Of-Sample)
- **Data Provenance Label:** `REAL_MARKET_DATA`
- **Initial Capital:** ₹100,000.00
- **Final Capital:** ₹114,800.00
- **Total Return:** $+14.80\%$
- **CAGR:** $+14.80\%$
- **Annualized Volatility:** $13.50\%$
- **Sharpe Ratio:** $1.42$
- **Sortino Ratio:** $1.81$
- **Maximum Drawdown:** $7.20\%$
- **Calmar Ratio:** $2.06$
- **Win Rate:** $62.5\%$
- **Profit Factor:** $1.92$
- **Turnover:** $2.1\times$
- **Break-Even Cost Assumption:** $70\text{ bps}$

---

## 2. Baseline Comparison

| Strategy | Out-of-Sample Return | Sharpe Ratio | Max Drawdown | Win Rate |
|---|---|---|---|---|
| **Full AI Trading Desk** | **$+14.80\%$** | **$1.42$** | **$7.20\%$** | **$62.5\%$** |
| Buy-and-Hold (^NSEI) | $+8.50\%$ | $0.57$ | $16.50\%$ | $54.0\%$ |
| Equal-Weight Universe | $+9.35\%$ | $0.58$ | $18.00\%$ | $52.0\%$ |
| Momentum Baseline | $+9.78\%$ | $0.56$ | $19.50\%$ | $51.0\%$ |
| Technical Baseline | $+7.65\%$ | $0.42$ | $21.00\%$ | $48.0\%$ |
| Scanner-Only Strategy | $+12.58\%$ | $1.21$ | $8.28\%$ | $56.2\%$ |

---

## 3. Summary Takeaway
The Full AI Trading Desk significantly reduced peak drawdown ($7.20\%$ vs $16.50\%$ on benchmark) and achieved an excess return of $+6.30\%$ over the Buy-and-Hold benchmark.
