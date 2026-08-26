# Implementation Plan

## Goal
Expand historical market-data foundation to support configurable historical depth (5D, 20D, 60D, 252D) without bloating the LLM prompt. Updates include `MarketContext`, `ContextService`, `YFinanceProvider`, and `QuantSpecialist`/calculator to utilize the expanded data for proper quant metrics (20D volatility, drawdown, Sharpe, etc.).

## Open Questions
- None.

## Proposed Changes

### `backend/domain/schemas.py`
- Add `HistoricalWindow(str, Enum)` with `RECENT="5D"`, `SHORT="20D"`, `MEDIUM="60D"`, `LONG="252D"`.
- Update `MarketContext`: add `historical_window: HistoricalWindow`. Keep `ohlcv_historical` as the full requested dataset.

### `backend/infrastructure/data_providers.py`
- Update `MarketDataProvider.get_market_context` signature to `get_market_context(self, symbol: str, window: HistoricalWindow = HistoricalWindow.RECENT)`.
- `YFinanceProvider` maps windows to yfinance periods (e.g. 252D -> "1y", 60D -> "3mo", 20D -> "1mo", 5D -> "1mo" to allow technical indicators like EMA50 which needs 50 days). Actually, just fetch "1y" if they ask for LONG, "3mo" for MEDIUM, "1mo" for SHORT/RECENT (wait, EMA50 needs 50 days. So we always need to fetch at least 60 days to calculate EMA50).
- After technicals, slice the dataframe to return the requested number of days in `MarketContext.ohlcv_historical` (5, 20, 60, or 252).

### `backend/application/context_service.py`
- Update `get_market_context` to accept `window: HistoricalWindow = HistoricalWindow.RECENT`.
- Cache key should be `f"{symbol}:{window.value}:{provider.name}"`.
- If a smaller window is requested, we could check if a larger window is in cache and derive it. Wait, the prompt says "Avoid fetching the same historical dataset repeatedly. For example, if a 252D request can satisfy: 5D, 20D, 60D, 252D, fetch once and derive smaller windows locally. Add tests proving this behavior where practical."
- So `ContextService.get_market_context` will first check cache for the requested window. If not found, it checks if a *larger* window is cached. If a larger window is found, it can copy it, slice `ohlcv_historical` to the requested size, and return it (maybe even cache the smaller one to speed up future lookups).

### `backend/specialists/quant_calculator.py`
- Add calculations for `realized_volatility_20d`, `max_drawdown_20d`, `rolling_vol_20d`, `sharpe_ratio_annualized`, `sortino_ratio_annualized` based on the data available. 
- Adjust minimum observation requirements.
- Add provenance (`data_timestamp`, `window`, etc.) properly.

### Tests
- Add tests in `test_context_service.py`, `test_data_providers.py`, `test_quant_calculator.py`.

## Verification Plan
### Automated Tests
- `python -m unittest discover tests`

### Manual Verification
- N/A
