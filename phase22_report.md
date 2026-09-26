# Phase 22 — Historical Research & Backtesting

## Objective
Build the project's Historical Research & Backtesting capability for deterministic, point-in-time evaluation of historical market setups without using future information.

## Infrastructure Reused
- **`BacktestEngine`**: We completely reused the existing deterministic historical backtesting service in `backend/application/backtest_engine.py` rather than building a redundant backtesting engine.
- **`YFinanceProvider`**: Used for fetching extended historical OHLCV data and TTM fundamentals.
- **`MarketContext`**: Point-in-time filtering is applied via `PointInTimeFilter` in the backtest engine itself.
- **Frontend Architecture**: Integrated into the existing SPA without redesigning the dashboard or introducing new frameworks.

## Files Created/Modified
- `backend/data/historical_research/` (Directory)
- `backend/application/historical_research_service.py` (Created)
- `backend/application/historical_research_routes.py` (Created)
- `tests/test_historical_research_e2e.py` (Created)
- `frontend/js/views/historical_research.js` (Created)
- `backend/main.py` (Modified to register new routes)
- `frontend/js/app.js` (Modified to link the new frontend view)

## Historical Data Approach & Look-Ahead Protection
- **Data Source**: Uses YFinance historical data to build the context.
- **Point-In-Time Evaluation**: `BacktestEngine.run_single_backtest` strictly separates data available up to `as_of` from future data. Future bars (`> as_of`) are extracted explicitly for outcome measurement and are completely invisible during decision-making and sizing.
- **Unavailable Data Handling**: If no historical OHLCV is available before the timestamp, `BacktestDataQuality.UNAVAILABLE` is raised. 

## Strategy / Backtest Architecture
- We utilize the deterministic `BacktestConfig` allowing customizable execution rules (`CLOSE_AT_SIGNAL`, `NEXT_OPEN`), holding periods, and explicitly documented transactional friction (brokerage, slippage, STT).
- Follows the existing API schemas defined in `backend/domain/backtest_schemas.py`.

## Performance Metrics
- Net Return %
- Max Drawdown %
- Maximum Favorable Excursion (MFE) %
- Maximum Adverse Excursion (MAE) %
- Total Cost
- Gross PnL
- Decision Quality Score
- Win/Loss/Scratch Outcome Status Classification

## API
Exposed endpoints under `/api/historical-research`:
- `POST /api/historical-research/run`
- `GET /api/historical-research/results`
- `GET /api/historical-research/results/{backtest_id}`

## Frontend
Added `Historical Research` view to the navigation sidebar. Supports configuring symbol, as-of date, and holding period. Features live results parsing including Entry/Exit Prices, net returns, drawdown, execution costs, and a running list of past historical simulations.

## Safety Measures
- Does NOT interact with the broker API.
- Fully offline simulation, deterministic execution.
- Retains `LIVE_EXECUTION_ENABLED=false` and `EXECUTION_FREEZE_ACTIVE=true` safety invariants.
- No modifications were made to `StateJournal`.

## Test Results
- Targeted E2E test `tests/test_historical_research_e2e.py` executed successfully.
- Full regression completed with the known pre-existing unrelated Phase 42 failure (`test_phase42_production_activation.py`) explicitly left unaddressed, per instructions.

## Known Limitations
- Quarter-by-quarter PIT fundamental snapshots are limited by YFinance’s free data tier capabilities (which typically only provide TTM fundamentals accurately without expensive mapping). We use the available TTM fundamentals but explicitly categorize data freshness for simulation transparency.

## StateJournal Status
- Untouched. No historical fabrication was performed.
