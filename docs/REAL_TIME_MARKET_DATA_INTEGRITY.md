# Phase 38: Real-Time Market Data & Signal Integrity

## Architecture Overview
The Market Data Integrity layer acts as an absolute, deterministic barrier between external data providers and the internal Execution Preflight boundaries. 
This ensures that downstream systems only consume strongly-validated, monotonic, and fresh market ticks, preventing stale signals or manipulated payloads from authorizing executions.

### Key Components
1. **Market Data Schemas** (`market_data_schemas.py`)
   Strongly-typed Pydantic models for `MarketTick`, `MarketQuote`, and `OHLCCandle` featuring rigorous `model_validator`s enforcing:
   - Positive quantities and prices (no negative, NaN, or Infinity values).
   - Strict past/present boundaries (reject future-dated timestamps).
   - Valid spread relationships (bid must be strictly less than ask).
   - Strict OHLC relationships (High is highest, Low is lowest).

2. **Market Data Integrity Engine** (`market_data_integrity_engine.py`)
   A deterministic, stateful evaluator handling sequence regressions, duplicate occurrences, out-of-order deliveries, and data aging.
   Tracks source health dynamically to flag degraded or unavailable providers based on validation failures or data discontinuity.

3. **Tamper-Evident Auditing**
   Injects fine-grained observability via the `global_audit_chain` on states like `MARKET_DATA_STALE`, `MARKET_DATA_OUT_OF_ORDER`, and `MARKET_DATA_CROSSED_QUOTE`.

## Fail-Closed Strategy Boundary
The engine integrates with the Execution Preflight logic via the `fail_closed_check(symbol)` endpoint. 
It strictly requires data to be in the `FRESH` state and `VALID` integrity state before downstream checks are allowed to proceed.
The freshness boundary defaults to a strictly configured age limit of 5.0 seconds.

## AI Security Boundary
AI inferences or generated signals remain entirely advisory. The AI cannot mutate the `MarketDataIntegrityState`, inject raw ticks, bypass sequence regressions, or force a `fail_closed_check` to return True. The market data integrity engine relies exclusively on deterministic schema parsing.

## Performance Metrics
- **Throughput Capability**: Supports high-burst concurrent ingestion.
- **Latency Impact**: Validation processing scales uniformly via O(1) checks against the latest symbol snapshot map without lock contention overhead across instruments.

## Future Phases
As part of Phase 42 (Final Launch Sequence), the Live Readiness module will consume the aggregate provider health map to prevent any arming if primary data feeds exhibit systemic degradation.
