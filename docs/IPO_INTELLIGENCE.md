# IPO Intelligence Subsystem

## Overview
The IPO Intelligence Subsystem introduces structural tracking and fundamental analysis capabilities for Upcoming, Open, and Listed IPOs to the AI Trading Desk OS.

## Core Capabilities
- Discovery of upcoming, open, and listed IPOs.
- Clear demarcation between Mainboard and SME IPO types.
- Complete structural analysis: Fresh Issue vs Offer For Sale (OFS), issue sizes, dates, and pricing.
- Unofficial Grey Market Premium (GMP) tracking, ensuring explicit separation from official exchange data.
- Subscription tracking.
- AI-driven fundamental analysis that yields a calibrated score and verdict, evaluating multiple dimensions (GMP, Subscription, Issue Structure, Valuation).

## Safety & Boundaries
- **No Execution Authority:** This subsystem is strictly observational. It has zero capability to place real money orders or interact with a live broker for IPO applications.
- **Fail-closed Integrity:** Real-money trading and production environments remain fully locked (Tier 4).
- **Data Integrity:** Missing or non-available data results in an `INSUFFICIENT_DATA` verdict rather than fabrication. GMP and Subscription values are not assumed or extrapolated. 
- **Sentiment vs Fundamental Separation:** A high GMP does not automatically result in a `STRONG` verdict if fundamental structures (e.g., heavily skewed to OFS) remain weak.

## Technical Architecture
- `backend/domain/ipo_schemas.py`: Strongly typed Pydantic models for IPO Data, GMP Observations, Subscription Observations, and Analysis Outcomes.
- `backend/application/ipo_engine.py`: Encapsulates business logic, derived calculations (e.g. estimated listing price, issue size calculations), and the deterministic analysis engine.
- `backend/application/ipo_routes.py`: REST APIs connecting the domain engine to the frontend UI and orchestrating audit event emission.
- `backend/infrastructure/providers`: Standard interfaces (`IPODataProvider`, `GMPDataProvider`, `SubscriptionDataProvider`) separating internal data models from external data retrieval mechanisms.

## API Endpoints
- `GET /api/ipo/list`: List all IPOs (with optional status filtering).
- `GET /api/ipo/{ipo_id}`: Fetch complete details of a specific IPO.
- `GET /api/ipo/{ipo_id}/gmp`: Fetch GMP history.
- `GET /api/ipo/{ipo_id}/subscription`: Fetch latest subscription data.
- `GET /api/ipo/{ipo_id}/analysis`: Run deterministic AI analysis and return scored verdicts.
- `POST /api/ipo/{ipo_id}/refresh`: Trigger a fresh pull from data providers.

## Observability
All key lifecycle events such as data refreshes and analysis completions are securely appended to the `TamperEvidentAuditChain` to maintain an immutable log.
