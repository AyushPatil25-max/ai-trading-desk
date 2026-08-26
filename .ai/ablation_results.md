# Ablation Analysis Specification — Phase 5.4

This document outlines the pipeline variant ablation tests designed to measure the marginal information and risk-reduction value added by each layer of the AI Trading Desk.

---

## 1. Pipeline Variants

| Variant | Description | Focus |
|---|---|---|
| **Variant A: Technical Only** | Single specialist (Technical) | Price-action baseline |
| **Variant B: Tech + Momentum** | Technical + Momentum Specialists | Trend & velocity alignment |
| **Variant C: Tech + Mom + Quant** | Tech, Momentum, and Quant Specialists | Statistical risk & regime filtering |
| **Variant D: All 9 Specialists** | Full 9 domain specialists (Tech, Mom, Quant, Fund, Val, Sector, Macro, News, Inst) | Multi-modal domain consensus |
| **Variant E: 9 Specialists + Debate** | 9 Specialists + Bull/Bear/Risk Adversarial Debate | Thesis stress-testing & attack verification |
| **Variant F: Full Pipeline** | 9 Specialists + Debate + Investment Committee + Execution Safety | Complete deterministic governance |

---

## 2. Marginal Value Metrics

Each variant is benchmarked on:
- Out-of-Sample Return (%)
- Sharpe & Sortino Ratios
- Maximum Drawdown (%)
- Win Rate (%) & Profit Factor
- Trade Count & Turnover
