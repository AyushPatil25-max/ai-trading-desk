# Coding Rules

## Python Standards
- Python 3.10+ syntax and features.
- Strict type hinting is mandatory for all functions, methods, and classes.
- Use `isinstance()` over `type() ==`.
- Use f-strings for string formatting.
- Maximum line length of 100 characters.

## FastAPI Standards
- API routes must be purely declarative and handle request/response routing only.
- Business logic must reside in `services/` or `domain/` modules.
- Use dependency injection (`Depends()`) for database sessions, API clients, and configuration.
- Return appropriate HTTP status codes (200, 201, 400, 404, 500).

## Pydantic Standards
- Use Pydantic v2 syntax (`model_dump()`, `model_validate()`).
- All inputs from users and LLMs must be validated via Pydantic schemas.
- Use `Field(description="...")` heavily to guide LLM JSON generation.

## Async Standards
- `asyncio` is the standard for all network I/O, file I/O, and LLM API calls.
- Use `async def` and `await`.
- Do not use blocking functions (e.g., `time.sleep()`, `requests.get()`) inside an async event loop. Use `asyncio.sleep()` and `httpx.AsyncClient` or `AsyncGroq`.

## Logging
- Use Python's built-in `logging` module with structured JSON output capabilities.
- Log levels: `DEBUG` (agent tracing), `INFO` (workflow steps), `WARNING` (retries), `ERROR` (failures).
- Never log raw PII or API secrets.

## Error Handling
- Define custom exception classes inheriting from `Exception` (e.g., `class TradingSystemError(Exception): pass`).
- Handle exceptions at the lowest appropriate level; bubble up domain errors to the API layer to be translated into HTTP responses.
- Never use bare `except:` blocks; always catch `Exception` or specific subtypes.

## Testing
- Use `pytest` and `pytest-asyncio`.
- All domain logic requires unit tests.
- External API calls (Yahoo Finance, Groq) must be mocked using `unittest.mock` or `pytest-httpx`.
- Maintain test files in a dedicated `tests/` directory matching the source tree structure.

## Naming
- **Variables/Functions/Methods:** `snake_case`
- **Classes:** `PascalCase`
- **Constants:** `UPPER_SNAKE_CASE`
- **Files/Modules:** `snake_case.py`

## Project Structure
- Group by domain/feature, enforcing strict separation of concerns.
- `api/`: FastAPI routes.
- `core/`: Config, logging, exceptions.
- `domain/`: Business logic, orchestrators, models.
- `agents/`: LLM integrations and specialist logic.
- `services/`: Data ingestion, external APIs.

## Dependency Management
- Use `requirements.txt` strictly.
- Pin dependency versions (e.g., `fastapi==0.100.0`).
- No unused or unimported dependencies should remain in the file.

## Security
- Always load credentials via `.env` files using `python-dotenv`.
- Ensure CORS in FastAPI is restricted in production (no `*`).
- Sanitize inputs to prevent injection attacks.

## Git Practices
- Commit messages must be descriptive: `[Type] Subject`.
- Create a Git checkpoint/commit before initiating major automated refactoring.
- Do not commit `.env`, `__pycache__`, or raw data files.
