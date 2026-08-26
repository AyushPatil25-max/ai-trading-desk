# Institutional Data Matrix

This document tracks the mapping and status of institutional and ownership data feeds within the Data Trust Layer.

| Source | Data Category | Authority | API Available | Authentication | Historical | Point-in-Time | License | Fields | Implementation Status | Fallback |
|---|---|---|---|---|---|---|---|---|---|---|
| **NSE_Official** | Institutional Flow (FII/DII) | Primary | Yes (Private) | Mandatory | Yes | Yes | Yes | buy/sell/net values | Stubbed (Requires Auth) | Degrades cleanly |
| **NSE_Official** | Delivery Data | Primary | Yes (Private) | Mandatory | Yes | Yes | Yes | delivery qty, traded qty | Stubbed (Requires Auth) | Degrades cleanly |
| **NSE_Official** | Deals (Bulk/Block) | Primary | Yes (Private) | Mandatory | Yes | Yes | Yes | deal type, participant, value | Stubbed (Requires Auth) | Degrades cleanly |
| **BSE_Official** | Ownership / Pledges | Primary | Yes (Private) | Mandatory | Yes | Yes | Yes | promoter holding, pledge % | Stubbed (Requires Auth) | Degrades cleanly |
| **YFinance** | Institutional | Secondary | No | No | No | No | N/A | None natively reliable for India | Explicitly disabled | None |

## Capability Mapping
- The orchestrator fetches data by probing `ProviderCapabilities.institutional`, `ownership`, `deals`, and `delivery`.
- Since authentic, robust APIs for these require licenses (e.g. NSE Data Feed), we enforce strict stubs preventing LLM hallucinations or unauthorized web-scraping.

## Deterministic Computations
- `net_flow`: buy - sell
- `ownership_change`: current_percentage - previous_percentage
- `delivery_percentage`: delivery_quantity / traded_quantity * 100
- These calculations execute entirely in pure Python via `backend/specialists/institutional_calculator.py`.
