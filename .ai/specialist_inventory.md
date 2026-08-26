# Specialist Inventory — Phase 5.1 Audit

**Audit Date:** 2026-08-24  
**Auditor:** Antigravity AI Engine  
**Total Production Specialists:** 9  

---

## 1. Specialist Inventory Table

| Specialist | File | BaseAgent | Registered | Orchestrated | Tests | Status |
|---|---|---|---|---|---|---|
| **TechnicalSpecialist** | `backend/specialists/technical_specialist.py` | Yes | Yes | Yes | `tests/test_technical_specialist.py` | PRODUCTION |
| **MomentumSpecialist** | `backend/specialists/momentum_specialist.py` | Yes | Yes | Yes | `tests/test_momentum_specialist.py` | PRODUCTION |
| **QuantSpecialist** | `backend/specialists/quant_specialist.py` | Yes | Yes | Yes | `tests/test_quant_specialist.py` | PRODUCTION |
| **FundamentalSpecialist** | `backend/specialists/fundamental_specialist.py` | Yes | Yes | Yes | `tests/test_fundamental_specialist.py` | PRODUCTION |
| **ValuationSpecialist** | `backend/specialists/valuation_specialist.py` | Yes | Yes | Yes | `tests/test_valuation_specialist.py` | PRODUCTION |
| **SectorSpecialist** | `backend/specialists/sector_specialist.py` | Yes | Yes | Yes | `tests/test_sector_specialist.py` | PRODUCTION |
| **MacroSpecialist** | `backend/specialists/macro_specialist.py` | Yes | Yes | Yes | `tests/test_macro_specialist.py` | PRODUCTION |
| **NewsSpecialist** | `backend/specialists/news_specialist.py` | Yes | Yes | Yes | `tests/test_news_specialist.py` | PRODUCTION |
| **InstitutionalSpecialist** | `backend/specialists/institutional_specialist.py` | Yes | Yes | Yes | `tests/test_institutional_specialist.py` | PRODUCTION |

---

## 2. Non-Specialist BaseAgent Implementations

The following agents also inherit from `BaseAgent` but represent downstream synthesis, debate, committee, or legacy adapter layers rather than primary market specialists:

| Agent | File | Purpose | Layer |
|---|---|---|---|
| `BullAgent` | `backend/debate/bull_agent.py` | Constructs adversarial long thesis | Debate Layer (Phase 4.2) |
| `BearAgent` | `backend/debate/bear_agent.py` | Challenges and attacks long thesis | Debate Layer (Phase 4.2) |
| `RiskAgent` | `backend/debate/risk_agent.py` | Evaluates downside risk & risk vetoes | Debate Layer (Phase 4.2) |
| `InvestmentCommitteeAgent` | `backend/investment_committee/committee_agent.py` | Synthesizes deterministic investment decisions | Committee Layer (Phase 4.3) |
| `TechnicalAgentAdapter` | `backend/adapters/legacy_agents.py` | Backward compatibility adapter for legacy TechnicalAgent | Legacy Compatibility |
| `RiskAgentAdapter` | `backend/adapters/legacy_agents.py` | Backward compatibility adapter for legacy RiskAgent | Legacy Compatibility |

---

## 3. Findings and Corrections

1. **Documented Count**: Historical roadmap references mentioned 12 hypothetical agents. The actual verified production count is **9 specialists**.
2. **Package Exports**: Added `InstitutionalSpecialist` to `backend/specialists/__init__.__all__`.
3. **Architecture Conformance**: All 9 production specialists strictly follow the Golden Specialist Pattern:
   - Python performs deterministic calculation via associated calculator modules (`*_calculator.py`).
   - LLM provides qualitative interpretation only via structured Pydantic response models.
   - Outputs are standardized `AgentOutput` objects with explicit provenance and PIT guarantees.
