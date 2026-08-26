# Development Roadmap

## PHASE 0 — Repository/Security Foundation
- **Objective:** Secure the environment, fix missing dependencies, and unblock concurrency.
- **Inputs:** Current repository.
- **Outputs:** Updated `requirements.txt`, basic async API scaffolding.
- **Dependencies:** None.
- **Acceptance criteria:** `groq` installed, `.env` secured, FastAPI runs asynchronously without blocking.
- **Testing requirements:** Basic unit tests for async API endpoints.
- **Risks:** Breaking existing prototype UI.

## PHASE 1 — Core Architecture
- **Objective:** Separate API, Orchestration, and Domain layers.
- **Inputs:** Refactored Phase 0 code.
- **Outputs:** Clean domain-driven directory structure.
- **Dependencies:** Phase 0.
- **Acceptance criteria:** Business logic removed from FastAPI routes.
- **Testing requirements:** Unit tests for orchestration logic.
- **Risks:** Over-engineering early on.

## PHASE 2 — Data Engine
- **Objective:** Build robust ingestion and Unified Market Context.
- **Inputs:** `market_data.py`, `indicators.py`.
- **Outputs:** Postgres/Redis schemas, unified data fetching layer.
- **Dependencies:** Phase 1.
- **Acceptance criteria:** Historical and live data fetched and cached successfully.
- **Testing requirements:** Integration tests with mock API payloads.
- **Risks:** API rate limits, data inconsistency.

## PHASE 3 — Agent Runtime
- **Objective:** Define and implement the `BaseAgent` class and execution harness.
- **Inputs:** Current agent scripts.
- **Outputs:** Standardized agent framework with schemas, retries, and timeouts.
- **Dependencies:** Phase 1.
- **Acceptance criteria:** Agents can be invoked dynamically and return structured Pydantic models reliably.
- **Testing requirements:** Mocked LLM responses testing timeout and retry logic.
- **Risks:** High latency from LLMs breaking orchestration.

## PHASE 4 — Specialist Agents (✅ 9 Production Specialists Implemented)
- **Objective:** Build the specialized market research agents.
- **Inputs:** Agent Runtime.
- **Outputs:** 9 verified production specialist agent implementations (Technical, Momentum, Quant, Fundamental, Valuation, Sector, Macro, News, Institutional).
- **Dependencies:** Phase 2, Phase 3.
- **Acceptance criteria:** Each agent processes market context and outputs valid schema following the Golden Specialist Pattern.
- **Testing requirements:** Offline unit tests with deterministic calculations and mock LLMs.
- **Risks:** LLM hallucination (mitigated via strict Python calculators and structured response models).

## PHASE 5 — Async Orchestration
- **Objective:** Coordinate concurrent execution of specialist agents.
- **Inputs:** Specialist Agents.
- **Outputs:** Orchestration DAG/Pipeline.
- **Dependencies:** Phase 4.
- **Acceptance criteria:** 5+ agents execute in parallel and results are aggregated.
- **Testing requirements:** Concurrency load testing.
- **Risks:** Event loop blocking, memory leaks.

## PHASE 6 — Evidence Layer
- **Objective:** Normalize agent outputs into a standardized evidence store.
- **Inputs:** Aggregated agent results.
- **Outputs:** Searchable evidence database (JSON/SQL).
- **Dependencies:** Phase 5.
- **Acceptance criteria:** Chain-of-thought is stripped; only concise evidence remains.
- **Testing requirements:** Schema validation tests.
- **Risks:** Data loss from over-summarization.

## PHASE 7 — Debate
- **Objective:** Implement Bull, Bear, and Risk agent adversarial interaction.
- **Inputs:** Evidence Layer.
- **Outputs:** Debate transcript and synthesized arguments.
- **Dependencies:** Phase 6.
- **Acceptance criteria:** Bear successfully challenges Bull's weak points.
- **Testing requirements:** Qualitative review of debate logic.
- **Risks:** Circular arguments, consensus bias.

## PHASE 8 — Investment Committee
- **Objective:** Final decision-making agent mapping debate to a strict output contract.
- **Inputs:** Debate outputs.
- **Outputs:** Final `APPROVE`/`PASS` verdict with entry/exit plans.
- **Dependencies:** Phase 7.
- **Acceptance criteria:** Committee outputs match the defined JSON contract 100% of the time.
- **Testing requirements:** Edge-case testing for conflicting evidence.
- **Risks:** Indecision, overly conservative bias.

## PHASE 9 — Risk Engine
- **Objective:** Pure Python deterministic position sizing and constraint checking.
- **Inputs:** Investment Committee trade plan, account equity.
- **Outputs:** Exact share quantity, stop price, and portfolio exposure delta.
- **Dependencies:** Phase 8.
- **Acceptance criteria:** Mathematical proofs of maximum risk thresholds.
- **Testing requirements:** Extensive parameterized unit tests for all mathematical bounds.
- **Risks:** Floating point errors, logical flaws in drawdown logic.

## PHASE 10 — Opportunity Scanner
- **Objective:** Continuous background scanning to discover setups automatically.
- **Inputs:** Universe of tickers, Data Engine.
- **Outputs:** Triggered orchestration workflows.
- **Dependencies:** Phase 2, Phase 9.
- **Acceptance criteria:** System scans 500+ stocks daily and flags top candidates.
- **Testing requirements:** Performance profiling.
- **Risks:** API cost spikes.

## PHASE 11 — Backtesting
- **Objective:** Historically evaluate the entire system and rule-based strategies.
- **Inputs:** Old `engine.py`, historical data.
- **Outputs:** High-fidelity event-driven backtesting engine.
- **Dependencies:** Phase 2, Phase 9.
- **Acceptance criteria:** Slippage and fees are calculated; position sizing is mathematically accurate.
- **Testing requirements:** Verification against known historical trades.
- **Risks:** Look-ahead bias, survivorship bias.

## PHASE 12 — Paper Trading
- **Objective:** Simulate live execution of approved trade plans.
- **Inputs:** Trade plans, Live Data Engine.
- **Outputs:** Virtual portfolio state.
- **Dependencies:** Phase 9.
- **Acceptance criteria:** Virtual equity curve updates accurately based on real-time price action.
- **Testing requirements:** End-to-end integration tests.
- **Risks:** Divergence between paper and live liquidity.

## PHASE 13 — Monitoring
- **Objective:** Track open positions against their invalidation conditions.
- **Inputs:** Paper portfolio, Live Data.
- **Outputs:** Alerts and automated exit triggers.
- **Dependencies:** Phase 12.
- **Acceptance criteria:** System detects invalidation conditions and flags exits.
- **Testing requirements:** Simulated market crashes.
- **Risks:** Latency in alert triggering.

## PHASE 14 — Dashboard
- **Objective:** Upgrade the frontend to visualize the complex multi-agent process.
- **Inputs:** Existing `index.html`.
- **Outputs:** React/Next.js modern web application.
- **Dependencies:** Phase 8.
- **Acceptance criteria:** Users can view the Debate, Committee decision, and Paper Portfolio.
- **Testing requirements:** UI/UX testing.
- **Risks:** Frontend scope creep.

## PHASE 15 — Evaluation
- **Objective:** Automated learning loops evaluating past agent predictions.
- **Inputs:** Historical paper trades, Agent logs.
- **Outputs:** Performance matrix per agent.
- **Dependencies:** Phase 13.
- **Acceptance criteria:** System automatically grades the Bull and Bear agents based on outcome.
- **Testing requirements:** Data pipeline integrity tests.
- **Risks:** Misattribution of success/failure.

## PHASE 16 — Broker Integration
- **Objective:** Connect to live brokerage APIs (Alpaca/IBKR) for real execution.
- **Inputs:** Tested paper trading module.
- **Outputs:** Live trade execution.
- **Dependencies:** Phases 0-15 completely validated.
- **Acceptance criteria:** Trades execute seamlessly with accurate reconciliation.
- **Testing requirements:** Live testing with minimal capital.
- **Risks:** Severe financial loss, API glitches.
