# Agent Rules

The coding agent executing tasks within this repository MUST strictly adhere to the following rules:

1. **Inspect before modifying:** Always review the target file's current state and dependencies before proposing or applying changes.
2. **Never rewrite working code unnecessarily:** Preserve existing logic that functions correctly, especially when integrating it into the new architecture.
3. **Follow architecture:** Strictly adhere to the separation of concerns defined in `ARCHITECTURE.md`. Do not bypass the orchestration layer or inject business logic into API endpoints.
4. **Never expose secrets:** Do not log, print, or commit API keys, database passwords, or `.env` file contents.
5. **Never modify .env secrets:** Do not attempt to alter existing credentials in the environment.
6. **No live trading without explicit approval:** Never write code that executes trades with real capital unless explicitly authorized by the user.
7. **Never delete working code without approval:** Classify old code as deprecated or migrate it carefully. Deletion requires direct confirmation.
8. **Write tests:** Every new module, logic branch, or agent wrapper must include corresponding automated tests.
9. **Validate external data:** Always validate inputs from external sources (APIs, LLMs, user input) using Pydantic or similar frameworks.
10. **Use type hints:** All Python functions and methods must have complete type signatures.
11. **Use structured errors:** Raise specific domain errors (e.g., `AgentExecutionError`) rather than generic `Exception`.
12. **Run tests:** Verify that all tests pass locally before marking a task as complete.
13. **Report changed files:** Clearly summarize exactly which files were modified, created, or deleted upon task completion.
14. **Report test results:** Include a summary of the test execution outcomes.
15. **Stop when acceptance criteria are satisfied:** Do not engage in scope creep. Implement exactly what is requested and halt execution.
