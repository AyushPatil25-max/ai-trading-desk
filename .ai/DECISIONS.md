# Architectural Decisions

The following initial architectural decisions have been established and must be adhered to:

1. **FastAPI remains the API framework:** It provides robust async support and Pydantic integration natively.
2. **Python remains the backend language:** Essential for data science, Pandas, and LLM orchestration compatibility.
3. **`asyncio` will be used for independent agent execution:** To prevent network I/O from blocking the server and to allow parallel execution of specialist agents.
4. **LLM reasoning and deterministic financial calculations remain separate:** AI agents assess qualitative data and structured reasoning, but exact mathematical calculations (e.g., risk sizing) are done in pure Python.
5. **Investment Committee is separate from API and orchestration:** The decision engine is a pure domain component, entirely decoupled from the HTTP routing layer.
6. **Risk calculations must be deterministic:** Machine learning estimates for risk are insufficient; sizing, exposure, and stop distances must follow strict algorithmic formulas.
7. **Existing useful code should be migrated rather than blindly rewritten:** The current Pydantic schemas, UI, and basic agent flow provide a good foundation and will be adapted.
8. **No live broker execution during early development:** Safety and validity are prioritized.
9. **Paper trading comes before real execution:** The system must prove statistical edge in a simulated environment before any broker integration.
10. **Every major decision must have structured evidence and audit metadata:** Allows retrospective evaluation of why the system entered or exited a trade.
11. **Hidden chain-of-thought is not stored:** Agents must summarize their reasoning into concise, structured conclusions to save storage and improve readability.
12. **Git checkpoints are mandatory before major automated changes:** Ensures recoverability during aggressive refactoring phases.
