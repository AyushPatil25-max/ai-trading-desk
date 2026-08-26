"""
SpecialistOrchestrator — Phase 3.1

Executes a set of specialist agents against ONE shared immutable MarketContext.

Responsibilities
----------------
- Accept MarketContext from the caller (does NOT fetch market data itself).
- Execute agents concurrently, bounded by max_concurrency.
- Apply per-agent timeout.
- Isolate failures: one failing agent must not crash the run.
- Apply RetryPolicy for recoverable failures.
- Produce a structured SpecialistRunResult.
- Log structured observability events.

NOT responsible for
-------------------
- Deciding buy/sell.
- Calculating position size.
- Approving trades.
- Fetching market data.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import List, Optional

from backend.domain.agents import BaseAgent
from backend.domain.schemas import (
    AgentInput,
    AgentOutput,
    AgentState,
    AgentExecutionRecord,
    MarketContext,
    SpecialistRunResult,
)
from backend.application.retry_policy import RetryPolicy, NonRecoverableAgentError

logger = logging.getLogger(__name__)


class SpecialistOrchestrator:
    """
    Parallel execution engine for specialist agents.

    Parameters
    ----------
    max_concurrency : int
        Maximum number of agents running simultaneously (default 5).
    agent_timeout_seconds : float
        Per-agent wall-clock limit (default 60 s as per ARCHITECTURE.md).
    retry_policy : RetryPolicy | None
        Override the default retry behaviour.
    """

    DEFAULT_CONCURRENCY = 5
    DEFAULT_TIMEOUT = 60.0

    def __init__(
        self,
        max_concurrency: int = DEFAULT_CONCURRENCY,
        agent_timeout_seconds: float = DEFAULT_TIMEOUT,
        retry_policy: Optional[RetryPolicy] = None,
    ) -> None:
        self.max_concurrency = max_concurrency
        self.agent_timeout_seconds = agent_timeout_seconds
        self.retry_policy = retry_policy or RetryPolicy(
            max_attempts=3,
            delay_seconds=1.0,
        )

    async def run(
        self,
        agents: List[BaseAgent],
        market_context: MarketContext,
        additional_data: Optional[dict] = None,
    ) -> SpecialistRunResult:
        """
        Execute all agents concurrently against the shared market_context.

        Parameters
        ----------
        agents :
            List of fully-configured specialist agents.
        market_context :
            Shared immutable snapshot. All agents receive the same object.
        additional_data :
            Optional metadata passed into every AgentInput.

        Returns
        -------
        SpecialistRunResult — structured aggregate, always returned even if all agents fail.
        """
        run_id = str(uuid.uuid4())
        started_at = datetime.utcnow()

        logger.info(
            "[Orchestrator] run_id=%s context_id=%s symbol=%s agents=%d concurrency=%d timeout=%.1fs",
            run_id,
            market_context.context_id,
            market_context.symbol,
            len(agents),
            self.max_concurrency,
            self.agent_timeout_seconds,
        )

        semaphore = asyncio.Semaphore(self.max_concurrency)
        tasks = [
            self._execute_agent_guarded(
                agent=agent,
                market_context=market_context,
                additional_data=additional_data or {},
                semaphore=semaphore,
            )
            for agent in agents
        ]

        records: List[AgentExecutionRecord] = await asyncio.gather(*tasks)
        completed_at = datetime.utcnow()

        # Aggregate counters
        successful = sum(1 for r in records if r.status == AgentState.SUCCESS)
        failed = sum(1 for r in records if r.status == AgentState.FAILED)
        timed_out = sum(1 for r in records if r.status == AgentState.TIMEOUT)
        degraded = sum(1 for r in records if r.status == AgentState.DEGRADED)

        outputs = [r.output for r in records if r.output is not None]

        duration = (completed_at - started_at).total_seconds()

        logger.info(
            "[Orchestrator] run_id=%s COMPLETE duration=%.2fs "
            "success=%d failed=%d timeout=%d degraded=%d",
            run_id, duration, successful, failed, timed_out, degraded,
        )

        return SpecialistRunResult(
            run_id=run_id,
            context_id=market_context.context_id,
            symbol=market_context.symbol,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration,
            total_agents=len(agents),
            successful_agents=successful,
            failed_agents=failed,
            timed_out_agents=timed_out,
            degraded_agents=degraded,
            records=records,
            outputs=outputs,
        )

    # ── Internal helpers ─────────────────────────────────────────────────────

    async def _execute_agent_guarded(
        self,
        agent: BaseAgent,
        market_context: MarketContext,
        additional_data: dict,
        semaphore: asyncio.Semaphore,
    ) -> AgentExecutionRecord:
        """
        Acquire semaphore slot → execute with timeout → isolate failures.

        Never raises. Always returns a populated AgentExecutionRecord.
        """
        async with semaphore:
            return await self._execute_with_timeout(agent, market_context, additional_data)

    async def _execute_with_timeout(
        self,
        agent: BaseAgent,
        market_context: MarketContext,
        additional_data: dict,
    ) -> AgentExecutionRecord:
        started_at = datetime.utcnow()
        logger.info(
            "[Orchestrator] START agent=%s version=%s context_id=%s",
            agent.name, agent.version, market_context.context_id,
        )

        agent_input = AgentInput(
            symbol=market_context.symbol,
            market_context=market_context,
            additional_data=additional_data,
        )

        try:
            output, attempts = await asyncio.wait_for(
                self.retry_policy.execute(
                    coro_factory=lambda: agent.execute(agent_input),
                    agent_name=agent.name,
                ),
                timeout=self.agent_timeout_seconds,
            )
            completed_at = datetime.utcnow()
            duration = (completed_at - started_at).total_seconds()

            logger.info(
                "[Orchestrator] SUCCESS agent=%s duration=%.2fs attempts=%d",
                agent.name, duration, attempts,
            )

            return AgentExecutionRecord(
                agent_name=agent.name,
                agent_version=agent.version,
                context_id=market_context.context_id,
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=duration,
                status=output.status,
                attempts=attempts,
                output=output,
            )

        except asyncio.TimeoutError:
            completed_at = datetime.utcnow()
            duration = (completed_at - started_at).total_seconds()
            logger.warning(
                "[Orchestrator] TIMEOUT agent=%s after %.1fs",
                agent.name, duration,
            )
            # Build a structured timeout output
            timeout_output = AgentOutput(
                agent_name=agent.name,
                version=agent.version,
                model="unknown",
                status=AgentState.TIMEOUT,
                data_timestamp=market_context.data_timestamp,
                confidence=0.0,
                conclusion="Agent timed out.",
                error={"code": "TIMEOUT", "message": f"Exceeded {self.agent_timeout_seconds}s"},
            )
            return AgentExecutionRecord(
                agent_name=agent.name,
                agent_version=agent.version,
                context_id=market_context.context_id,
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=duration,
                status=AgentState.TIMEOUT,
                attempts=1,
                output=timeout_output,
                error_message=f"Timed out after {self.agent_timeout_seconds}s",
            )

        except NonRecoverableAgentError as exc:
            completed_at = datetime.utcnow()
            duration = (completed_at - started_at).total_seconds()
            logger.error(
                "[Orchestrator] NON-RECOVERABLE agent=%s error=%s",
                agent.name, exc,
            )
            failed_output = AgentOutput(
                agent_name=agent.name,
                version=agent.version,
                model="unknown",
                status=AgentState.FAILED,
                data_timestamp=market_context.data_timestamp,
                confidence=0.0,
                conclusion="Non-recoverable failure.",
                error={"code": "NON_RECOVERABLE", "message": str(exc)},
            )
            return AgentExecutionRecord(
                agent_name=agent.name,
                agent_version=agent.version,
                context_id=market_context.context_id,
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=duration,
                status=AgentState.FAILED,
                output=failed_output,
                error_message=str(exc),
            )

        except Exception as exc:
            completed_at = datetime.utcnow()
            duration = (completed_at - started_at).total_seconds()
            logger.error(
                "[Orchestrator] FAILED agent=%s error=%s: %s",
                agent.name, type(exc).__name__, exc,
            )
            failed_output = AgentOutput(
                agent_name=agent.name,
                version=agent.version,
                model="unknown",
                status=AgentState.FAILED,
                data_timestamp=market_context.data_timestamp,
                confidence=0.0,
                conclusion="Agent execution failed.",
                error={"code": "EXEC_ERROR", "message": str(exc)},
            )
            return AgentExecutionRecord(
                agent_name=agent.name,
                agent_version=agent.version,
                context_id=market_context.context_id,
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=duration,
                status=AgentState.FAILED,
                output=failed_output,
                error_message=str(exc),
            )
