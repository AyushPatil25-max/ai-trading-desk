"""
RetryPolicy — Phase 3.1

Defines a minimal retry mechanism for recoverable specialist failures.
Distinguishes recoverable vs non-recoverable exceptions.
Retry count is configurable.

Design principles
-----------------
- Non-recoverable errors (programming / schema / config) are re-raised immediately.
- Recoverable errors (transient network / LLM / rate-limit) are retried up to max_attempts.
- Simple linear delay; no exponential backoff complexity at this stage.
"""

import asyncio
import logging
from typing import Callable, Awaitable, Tuple, Type

logger = logging.getLogger(__name__)


# ── Exception classification ──────────────────────────────────────────────────

class RecoverableAgentError(Exception):
    """
    Transient error that a retry may resolve.
    Examples: temporary LLM 503, network timeout, rate-limit.
    """


class NonRecoverableAgentError(Exception):
    """
    Permanent error. Retrying will not help.
    Examples: invalid schema, misconfigured agent, missing required field.
    """


# Default set of exception types considered recoverable.
# Callers may extend this by subclassing RecoverableAgentError.
_DEFAULT_RECOVERABLE: Tuple[Type[Exception], ...] = (
    RecoverableAgentError,
    ConnectionError,
    TimeoutError,
)


class RetryPolicy:
    """
    Configurable retry wrapper for async callables.

    Parameters
    ----------
    max_attempts : int
        Total number of attempts including the first (default 3).
    delay_seconds : float
        Fixed sleep between retries in seconds (default 1.0).
    recoverable_exceptions : tuple
        Exception types that trigger a retry.
    """

    def __init__(
        self,
        max_attempts: int = 3,
        delay_seconds: float = 1.0,
        recoverable_exceptions: Tuple[Type[Exception], ...] = _DEFAULT_RECOVERABLE,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1.")
        self.max_attempts = max_attempts
        self.delay_seconds = delay_seconds
        self.recoverable_exceptions = recoverable_exceptions

    async def execute(
        self,
        coro_factory: Callable[[], Awaitable],
        agent_name: str = "unknown",
    ):
        """
        Execute `coro_factory()` up to `max_attempts` times.

        - Re-raises NonRecoverableAgentError immediately.
        - Retries on recoverable_exceptions.
        - After exhausting retries, raises the last seen exception.

        Returns (result, attempts_used).
        """
        last_exc: Exception = RuntimeError("No attempt made.")
        for attempt in range(1, self.max_attempts + 1):
            try:
                result = await coro_factory()
                if attempt > 1:
                    logger.info(
                        "[RetryPolicy] agent=%s succeeded on attempt %d/%d",
                        agent_name, attempt, self.max_attempts,
                    )
                return result, attempt
            except NonRecoverableAgentError:
                logger.error(
                    "[RetryPolicy] agent=%s non-recoverable failure — aborting immediately.",
                    agent_name,
                )
                raise
            except self.recoverable_exceptions as exc:
                last_exc = exc
                logger.warning(
                    "[RetryPolicy] agent=%s attempt %d/%d failed (%s: %s). %s",
                    agent_name,
                    attempt,
                    self.max_attempts,
                    type(exc).__name__,
                    exc,
                    "Retrying…" if attempt < self.max_attempts else "Exhausted.",
                )
                if attempt < self.max_attempts:
                    await asyncio.sleep(self.delay_seconds)
            except Exception as exc:
                # Unknown exception — treat as non-recoverable.
                logger.error(
                    "[RetryPolicy] agent=%s unknown exception (%s: %s) — not retrying.",
                    agent_name, type(exc).__name__, exc,
                )
                raise

        raise last_exc
