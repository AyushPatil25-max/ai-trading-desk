# Architecture Specification

## Target Architecture Flow
```
DATA SOURCES
↓
DATA INGESTION
↓
UNIFIED MARKET CONTEXT
↓
AGENT RUNTIME
↓
12 SPECIALIST AGENTS
↓
EVIDENCE NORMALIZATION
↓
BULL / BEAR / RISK
↓
INVESTMENT COMMITTEE
↓
DETERMINISTIC RISK ENGINE
↓
TRADE PLAN
↓
PAPER TRADING
↓
MONITORING
↓
EVALUATION
```

## Layer Responsibilities
1. **API Layer:** Handles HTTP requests and routing only. Absolutely no core business logic.
2. **Orchestration Layer:** Manages state transitions, workflow progression, and async task coordination.
3. **Agent Runtime:** Standardized execution environment for LLM interactions, enforcing schemas, retries, and timeouts.
4. **Specialist Agents:** Specialized LLM wrappers focused on narrow domains (e.g., Technical, News).
5. **Data Ingestion:** Standardized fetching from external APIs (Yahoo, Alpaca, etc.) with rate limiting.
6. **Unified Market Context:** Centralized, normalized state (Redis/Postgres) preventing redundant API calls.
7. **Evidence/Audit Layer:** Stores structured JSON evidence and conclusions instead of hidden chain-of-thought.
8. **Debate Layer:** Adversarial environment where Bull, Bear, and Risk agents clash over evidence.
9. **Investment Committee:** Synthesizes debate into a final, structured decision. Exists purely in the domain layer, uncoupled from API.
10. **Deterministic Risk Engine:** Pure Python mathematical execution for sizing and thresholds. No AI guesses.
11. **Portfolio Engine:** Tracks aggregate portfolio metrics, correlations, and equity curves.
12. **Research/Backtesting Engine:** Vectorized or event-driven simulation for historical evaluation.
13. **Paper Trading:** Simulated live execution matching the trade plan.
14. **Monitoring:** Tracks live positions against invalidation conditions.
15. **Frontend:** React/Tailwind UI to visualize metrics, agent debates, and verdicts.

## Interfaces & Execution Protocols
- **Sync vs Async:** Agent execution, API endpoints, and orchestration *must* be `asyncio` based. Data ingestion network calls must also be async. However, deterministic calculations (e.g., Pandas/Numpy operations for RSI, EMA, Volatility) must remain synchronous as they are CPU-bound. If they become heavily CPU-bound, they should be offloaded to thread/process pools, not masked as async.
- **Failure Handling & Degradation:** 
  - *Agent Failure:* If a single specialist agent fails after retries, the system must degrade gracefully (workflow continues with a warning, committee operates on partial evidence).
  - *Data Failure:* If critical market/price data fetching fails, the entire workflow must abort safely.
  - *LLM Schema Failure:* If an LLM returns invalid JSON, retry up to 3 times with the parser error appended. If still invalid, mark agent status as FAILED.
  - *Infrastructure Failure:* Database/Redis unavailability should trigger an immediate API 503 Service Unavailable error.
- **Timeouts:** 30 seconds for data ingestion. 60 seconds per agent execution. 180 seconds for orchestration workflows.
- **Retries:** Maximum 3 retries for transient network/LLM errors with exponential backoff.
- **Concurrency Limits:** Maximum 5 concurrent LLM calls per orchestration run to respect rate limits.
- **Structured Outputs:** All LLM outputs must be strict JSON validated via Pydantic.
- **Data Freshness:** Live market data cached for 1 minute max. Fundamental data cached for 24 hours.
- **Observability:** Centralized structured logging for all agent inferences, inputs, outputs, and confidence scores.
- **Security Boundaries:** API keys restricted to environment variables. API routes separated from execution engines.

## Agent Architecture
### BaseAgent Interface
Every agent implements a BaseAgent class with:
- `name`: string
- `version`: string
- `model`: string
- `input_schema`: Pydantic model
- `output_schema`: Pydantic model
- `execute()`: async method
- `timeout`: int (seconds)
- `retry_policy`: dict
- `confidence`: float (0.0 to 1.0)
- `evidence`: list[str]
- `assumptions`: list[str]
- `risks`: list[str]
- `invalidation_conditions`: list[str]
- `timestamp`: ISO8601
- `data_timestamp`: ISO8601
- `status`: string (e.g., SUCCESS, DEGRADED, FAILED)
- `error_state`: Optional[str]

### Hidden Chain-of-Thought
Hidden chain-of-thought is strictly **forbidden** for storage. Agents must summarize reasoning into concise, structured `evidence` and `conclusions`.

## Specialists Contracts
1. **Fundamental:** Analyzes balance sheets, income statements, and cash flows.
2. **Quant:** Evaluates statistical anomalies, mean reversion, and correlations.
3. **Technical:** Analyzes price action, volume profiles, and chart patterns.
4. **Valuation:** Computes DCF, multiples, and relative valuation metrics.
5. **Sector:** Evaluates industry-specific headwinds and tailwinds.
6. **Institutional:** Tracks 13F filings, insider buying, and dark pool prints.
7. **News:** Performs sentiment analysis on breaking news.
8. **Filing:** Parses 10-K, 10-Q, and 8-K regulatory filings.
9. **Concall:** Analyzes earnings call transcripts for tone and guidance changes.
10. **Earnings:** Evaluates EPS/Revenue beats, misses, and historical reactions.
11. **Macro:** Analyzes interest rates, inflation, and global liquidity.
12. **Momentum:** Tracks short-to-medium term relative strength and trend velocity.

## Debate Protocol
- **Bull Agent:** Constructs the strongest evidence-based long thesis.
- **Bear Agent:** Actively attempts to invalidate the Bull thesis using opposing evidence.
- **Risk Agent:** Evaluates volatility, stop distance, position sizing, portfolio exposure, downside, liquidity, correlation, and scenario risk.

## Investment Committee
**Final Decision Contract Output:**
- `recommendation`: PASS | WATCH | CONDITIONAL | APPROVE
- `confidence`: float
- `thesis`: string
- `supporting_evidence`: list[str]
- `opposing_evidence`: list[str]
- `key_catalysts`: list[str]
- `key_risks`: list[str]
- `invalidation_conditions`: list[str]
- `entry_conditions`: dict
- `exit_conditions`: dict
- `time_horizon`: string
- `risk_reward`: float
- `decision_status`: string
*(Note: The committee does not place trades directly).*

## Deterministic Risk Engine
Strict deterministic Python logic executing final validation. **Crucially, the Risk Engine possesses veto authority and will reject a trade—even if approved by the Investment Committee—if hard quantitative constraints are violated.**
It strictly evaluates:
- Account equity
- Maximum risk per trade
- Stop distance
- Position size
- Maximum exposure
- Portfolio exposure
- Correlation
- Liquidity constraints
- Maximum drawdown rules

## Current → Future Mapping
| Current Component | Future Component | Classification |
| :--- | :--- | :--- |
| `backend/main.py` (FastAPI) | API Layer | **MODIFY** (Strip logic, keep routing) |
| `backend/main.py` (Logic) | Orchestration Layer | **NEW** (Separate module) |
| `backend/agents/technical_agent.py` | Technical Specialist Agent | **MODIFY** |
| `backend/agents/risk_agent.py` | Risk Agent | **MODIFY** |
| `backend/market_data.py` | Data Ingestion | **REPLACE** |
| `backend/indicators.py` | Quant Domain Services | **MODIFY** |
| `backend/strategies/breakout.py` | Opportunity Scanner | **REPLACE** |
| `backend/backtesting/engine.py` | Research/Backtesting Engine | **REPLACE** |
| `backend/backtesting/metrics.py` | Evaluation Layer | **MODIFY** |
| `frontend/index.html` | Frontend Dashboard | **KEEP** (For now, upgrade later) |
| `requirements.txt` | Dependency Manager | **MODIFY** (Add groq, async libs) |
