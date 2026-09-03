"""
Tests for Phase 3.1 — Specialist Agent Runtime + Parallel Orchestration.

All external APIs (Groq, Yahoo Finance) are mocked.
Tests are fully offline and deterministic.
"""

import asyncio
import time
import unittest
from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

from backend.application.agent_registry import (
    AgentRegistry,
    AgentRegistrationError,
    AgentNotFoundError,
)
from backend.application.retry_policy import (
    RetryPolicy,
    RecoverableAgentError,
    NonRecoverableAgentError,
)
from backend.application.specialist_orchestrator import SpecialistOrchestrator
from backend.domain.agents import BaseAgent
from backend.domain.schemas import (
    AgentInput,
    AgentOutput,
    AgentState,
    DataQualityStatus,
    MarketContext,
    SpecialistRunResult,
)


# ─── Shared test helpers ─────────────────────────────────────────────────────

def _make_context(symbol: str = "TEST", context_id: str = "ctx-001") -> MarketContext:
    return MarketContext(
        context_id=context_id,
        symbol=symbol,
        provider="test",
        data_timestamp=datetime.now(timezone.utc),
        current_price=100.0,
        quality_status=DataQualityStatus.OK,
    )


def _make_output(agent_name: str, status: AgentState = AgentState.SUCCESS) -> AgentOutput:
    return AgentOutput(
        agent_name=agent_name,
        version="1.0",
        model="test-model",
        status=status,
        data_timestamp=datetime.now(timezone.utc),
        confidence=0.9,
        conclusion=f"{agent_name} conclusion",
    )


class FakeAgent(BaseAgent):
    """Succeeds immediately."""
    def __init__(self, name: str, delay: float = 0.0) -> None:
        self._name = name
        self._delay = delay

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return "1.0"

    async def execute(self, input_data: AgentInput) -> AgentOutput:
        if self._delay:
            await asyncio.sleep(self._delay)
        return _make_output(self._name)


class FailingAgent(BaseAgent):
    """Always raises a generic exception."""
    def __init__(self, name: str, exc: Exception = None) -> None:
        self._name = name
        self._exc = exc or RuntimeError("Simulated failure")

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return "1.0"

    async def execute(self, input_data: AgentInput) -> AgentOutput:
        raise self._exc


class SlowAgent(BaseAgent):
    """Takes longer than a given timeout — triggers asyncio.TimeoutError."""
    def __init__(self, name: str, sleep_seconds: float = 10.0) -> None:
        self._name = name
        self._sleep = sleep_seconds

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return "1.0"

    async def execute(self, input_data: AgentInput) -> AgentOutput:
        await asyncio.sleep(self._sleep)
        return _make_output(self._name)


class RecoverableFailAgent(BaseAgent):
    """Fails with RecoverableAgentError the first N times, then succeeds."""
    def __init__(self, name: str, fail_times: int = 2) -> None:
        self._name = name
        self._fail_times = fail_times
        self._calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return "1.0"

    async def execute(self, input_data: AgentInput) -> AgentOutput:
        self._calls += 1
        if self._calls <= self._fail_times:
            raise RecoverableAgentError(f"Transient error attempt {self._calls}")
        return _make_output(self._name)


class NonRecoverableFailAgent(BaseAgent):
    """Always raises NonRecoverableAgentError."""
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return "1.0"

    async def execute(self, input_data: AgentInput) -> AgentOutput:
        raise NonRecoverableAgentError("Schema/config error — not retryable")


# ─── 1. AgentRegistry Tests ──────────────────────────────────────────────────

class TestAgentRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = AgentRegistry()

    def test_1_registration(self):
        """Agent can be registered."""
        agent = FakeAgent("Alpha")
        self.registry.register(agent)
        self.assertIn("Alpha", self.registry)

    def test_2_duplicate_registration_rejected(self):
        """Duplicate registration raises AgentRegistrationError."""
        self.registry.register(FakeAgent("Alpha"))
        with self.assertRaises(AgentRegistrationError):
            self.registry.register(FakeAgent("Alpha"))

    def test_3_retrieval(self):
        """Registered agent is retrievable by name."""
        agent = FakeAgent("Beta")
        self.registry.register(agent)
        retrieved = self.registry.get("Beta")
        self.assertIs(retrieved, agent)

    def test_non_base_agent_rejected(self):
        """Non-BaseAgent objects are rejected."""
        with self.assertRaises(AgentRegistrationError):
            self.registry.register(object())  # type: ignore

    def test_get_missing_raises(self):
        """Retrieving unknown agent raises AgentNotFoundError."""
        with self.assertRaises(AgentNotFoundError):
            self.registry.get("Ghost")

    def test_list_agents_sorted(self):
        """list_agents returns sorted names."""
        self.registry.register(FakeAgent("Zebra"))
        self.registry.register(FakeAgent("Apple"))
        self.assertEqual(self.registry.list_agents(), ["Apple", "Zebra"])

    def test_unregister(self):
        """Unregistering removes the agent."""
        self.registry.register(FakeAgent("Gamma"))
        self.registry.unregister("Gamma")
        self.assertNotIn("Gamma", self.registry)

    def test_len(self):
        self.assertEqual(len(self.registry), 0)
        self.registry.register(FakeAgent("X"))
        self.assertEqual(len(self.registry), 1)


# ─── 2. RetryPolicy Tests ────────────────────────────────────────────────────

class TestRetryPolicy(unittest.IsolatedAsyncioTestCase):
    async def test_success_first_try(self):
        policy = RetryPolicy(max_attempts=3, delay_seconds=0)

        async def _ok():
            return "ok"

        result, attempts = await policy.execute(lambda: _ok(), agent_name="X")

    async def _make_coro(self, value):
        return value

    async def test_4_successful_execution(self):
        policy = RetryPolicy(max_attempts=1, delay_seconds=0)
        result, attempts = await policy.execute(
            lambda: self._make_coro("done"), agent_name="A"
        )
        self.assertEqual(result, "done")
        self.assertEqual(attempts, 1)

    async def test_9_recoverable_retry_succeeds(self):
        """Recoverable error retried, succeeds on 3rd attempt."""
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RecoverableAgentError("transient")
            return "success"

        policy = RetryPolicy(max_attempts=3, delay_seconds=0)
        result, attempts = await policy.execute(lambda: flaky(), agent_name="Flaky")
        self.assertEqual(result, "success")
        self.assertEqual(attempts, 3)

    async def test_10_non_recoverable_aborts(self):
        """NonRecoverableAgentError is re-raised immediately, no retries."""
        call_count = 0

        async def bad():
            nonlocal call_count
            call_count += 1
            raise NonRecoverableAgentError("config error")

        policy = RetryPolicy(max_attempts=3, delay_seconds=0)
        with self.assertRaises(NonRecoverableAgentError):
            await policy.execute(lambda: bad(), agent_name="Bad")
        self.assertEqual(call_count, 1)

    async def test_retry_exhausted_raises_last_exc(self):
        """After all retries, last exception is raised."""
        async def always_fails():
            raise RecoverableAgentError("always bad")

        policy = RetryPolicy(max_attempts=2, delay_seconds=0)
        with self.assertRaises(RecoverableAgentError):
            await policy.execute(lambda: always_fails(), agent_name="Bad")


# ─── 3. SpecialistOrchestrator Tests ────────────────────────────────────────

class TestSpecialistOrchestrator(unittest.IsolatedAsyncioTestCase):

    async def test_4_single_agent_success(self):
        """Single agent executes and returns SUCCESS."""
        orchestrator = SpecialistOrchestrator(max_concurrency=4, agent_timeout_seconds=5.0)
        ctx = _make_context()
        result = await orchestrator.run([FakeAgent("Tech")], ctx)

        self.assertIsInstance(result, SpecialistRunResult)
        self.assertEqual(result.total_agents, 1)
        self.assertEqual(result.successful_agents, 1)
        self.assertEqual(result.failed_agents, 0)
        self.assertEqual(result.timed_out_agents, 0)

    async def test_5_multiple_agents_concurrently(self):
        """3 agents run and all succeed."""
        orchestrator = SpecialistOrchestrator(max_concurrency=4, agent_timeout_seconds=5.0)
        ctx = _make_context()
        agents = [FakeAgent("A"), FakeAgent("B"), FakeAgent("C")]
        result = await orchestrator.run(agents, ctx)

        self.assertEqual(result.total_agents, 3)
        self.assertEqual(result.successful_agents, 3)
        self.assertEqual(len(result.outputs), 3)

    async def test_6_concurrency_limit(self):
        """Concurrency limit is respected — semaphore ensures at most N run at once."""
        max_concurrency = 2
        concurrent_high_watermark = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        class InstrumentedAgent(BaseAgent):
            def __init__(self, agent_name: str):
                self._name = agent_name

            @property
            def name(self) -> str:
                return self._name

            @property
            def version(self) -> str:
                return "1.0"

            async def execute(self, input_data: AgentInput) -> AgentOutput:
                nonlocal concurrent_high_watermark, current_concurrent
                async with lock:
                    current_concurrent += 1
                    concurrent_high_watermark = max(
                        concurrent_high_watermark, current_concurrent
                    )
                await asyncio.sleep(0.05)
                async with lock:
                    current_concurrent -= 1
                return _make_output(self._name)

        orchestrator = SpecialistOrchestrator(
            max_concurrency=max_concurrency, agent_timeout_seconds=10.0
        )
        agents = [InstrumentedAgent(f"Agent{i}") for i in range(6)]
        result = await orchestrator.run(agents, _make_context())

        self.assertEqual(result.total_agents, 6)
        self.assertEqual(result.successful_agents, 6)
        # High-watermark must never exceed configured limit
        self.assertLessEqual(concurrent_high_watermark, max_concurrency)

    async def test_7_timeout_handling(self):
        """Timed-out agent produces TIMEOUT status, run completes normally."""
        orchestrator = SpecialistOrchestrator(
            max_concurrency=4, agent_timeout_seconds=0.1
        )
        ctx = _make_context()
        result = await orchestrator.run([SlowAgent("Slow", sleep_seconds=5.0)], ctx)

        self.assertEqual(result.timed_out_agents, 1)
        self.assertEqual(result.failed_agents, 0)
        timeout_record = result.records[0]
        self.assertEqual(timeout_record.status, AgentState.TIMEOUT)

    async def test_8_failure_isolation(self):
        """
        Agent A succeeds, Agent B fails, Agent C succeeds.
        Run completes; all three outcomes are preserved.
        """
        orchestrator = SpecialistOrchestrator(
            max_concurrency=4, agent_timeout_seconds=5.0
        )
        ctx = _make_context()
        agents = [
            FakeAgent("AgentA"),
            FailingAgent("AgentB"),
            FakeAgent("AgentC"),
        ]
        result = await orchestrator.run(agents, ctx)

        self.assertEqual(result.total_agents, 3)
        self.assertEqual(result.successful_agents, 2)
        self.assertEqual(result.failed_agents, 1)

        statuses = {r.agent_name: r.status for r in result.records}
        self.assertEqual(statuses["AgentA"], AgentState.SUCCESS)
        self.assertEqual(statuses["AgentB"], AgentState.FAILED)
        self.assertEqual(statuses["AgentC"], AgentState.SUCCESS)

    async def test_9_retry_succeeds(self):
        """RecoverableFailAgent fails twice then succeeds; run marks SUCCESS."""
        policy = RetryPolicy(max_attempts=3, delay_seconds=0)
        orchestrator = SpecialistOrchestrator(
            max_concurrency=4,
            agent_timeout_seconds=10.0,
            retry_policy=policy,
        )
        result = await orchestrator.run(
            [RecoverableFailAgent("RetryAgent", fail_times=2)], _make_context()
        )
        self.assertEqual(result.successful_agents, 1)
        self.assertEqual(result.records[0].attempts, 3)

    async def test_10_non_recoverable_fails_without_retry(self):
        """NonRecoverableAgentError leads to FAILED status, retries=1."""
        policy = RetryPolicy(max_attempts=3, delay_seconds=0)
        orchestrator = SpecialistOrchestrator(
            max_concurrency=4,
            agent_timeout_seconds=10.0,
            retry_policy=policy,
        )
        result = await orchestrator.run(
            [NonRecoverableFailAgent("BadAgent")], _make_context()
        )
        self.assertEqual(result.failed_agents, 1)

    async def test_11_aggregate_result_structure(self):
        """SpecialistRunResult has all required fields populated."""
        orchestrator = SpecialistOrchestrator(max_concurrency=4, agent_timeout_seconds=5.0)
        result = await orchestrator.run(
            [FakeAgent("TechAgent"), FakeAgent("MacroAgent")], _make_context()
        )
        self.assertTrue(result.run_id)
        self.assertTrue(result.context_id)
        self.assertTrue(result.symbol)
        self.assertIsNotNone(result.started_at)
        self.assertIsNotNone(result.completed_at)
        self.assertGreater(result.duration_seconds, 0)

    async def test_12_context_id_propagation(self):
        """Every AgentExecutionRecord carries the same context_id as the run."""
        ctx = _make_context(context_id="ctx-xyz-999")
        orchestrator = SpecialistOrchestrator(max_concurrency=4, agent_timeout_seconds=5.0)
        result = await orchestrator.run([FakeAgent("A"), FakeAgent("B")], ctx)

        self.assertEqual(result.context_id, "ctx-xyz-999")
        for record in result.records:
            self.assertEqual(record.context_id, "ctx-xyz-999")

    async def test_13_shared_market_context_identity(self):
        """All agents receive the exact same MarketContext object (same context_id)."""
        received_ids = []

        class InspectingAgent(BaseAgent):
            def __init__(self, agent_name: str):
                self._name = agent_name

            @property
            def name(self) -> str:
                return self._name

            @property
            def version(self) -> str:
                return "1.0"

            async def execute(self, input_data: AgentInput) -> AgentOutput:
                received_ids.append(input_data.market_context.context_id)
                return _make_output(self._name)

        ctx = _make_context(context_id="shared-ctx")
        orchestrator = SpecialistOrchestrator(max_concurrency=4, agent_timeout_seconds=5.0)
        agents = [InspectingAgent(f"Spy{i}") for i in range(4)]
        await orchestrator.run(agents, ctx)

        self.assertEqual(len(set(received_ids)), 1)
        self.assertEqual(received_ids[0], "shared-ctx")

    async def test_14_agent_lifecycle_transitions(self):
        """Successful agent record has status SUCCESS; failed has FAILED."""
        orchestrator = SpecialistOrchestrator(max_concurrency=4, agent_timeout_seconds=5.0)
        result = await orchestrator.run(
            [FakeAgent("Ok"), FailingAgent("Bad")], _make_context()
        )
        records = {r.agent_name: r for r in result.records}
        self.assertEqual(records["Ok"].status, AgentState.SUCCESS)
        self.assertEqual(records["Bad"].status, AgentState.FAILED)

    async def test_context_immutability_during_run(self):
        """Agents cannot mutate MarketContext (frozen Pydantic model)."""
        from pydantic import ValidationError

        ctx = _make_context()
        with self.assertRaises((ValidationError, TypeError)):
            ctx.current_price = 999.0  # type: ignore

    async def test_empty_agent_list(self):
        """Run with no agents returns a valid result with zero counts."""
        orchestrator = SpecialistOrchestrator()
        result = await orchestrator.run([], _make_context())
        self.assertEqual(result.total_agents, 0)
        self.assertEqual(result.successful_agents, 0)


# ─── 4. Concurrency Verification ─────────────────────────────────────────────

class TestConcurrencyVerification(unittest.IsolatedAsyncioTestCase):

    async def test_16_parallel_is_faster_than_sequential(self):
        """
        5 agents each sleeping 0.2 s.
        Sequential: ~1.0 s. Concurrent (max_concurrency=5): ~0.2 s.
        """
        agents = [FakeAgent(f"Par{i}", delay=0.2) for i in range(5)]
        orchestrator = SpecialistOrchestrator(max_concurrency=5, agent_timeout_seconds=10.0)

        t0 = time.perf_counter()
        result = await orchestrator.run(agents, _make_context())
        elapsed = time.perf_counter() - t0

        self.assertEqual(result.successful_agents, 5)
        # Concurrent run should complete in well under sequential time (1.0 s)
        self.assertLess(elapsed, 0.8, f"Elapsed {elapsed:.2f}s — expected concurrent execution")

    async def test_concurrency_limit_with_events(self):
        """
        max_concurrency=2, 4 agents.
        Prove that at no point do more than 2 execute simultaneously.
        """
        gate = asyncio.Event()
        active = 0
        peak = 0
        lock = asyncio.Lock()

        class GatedAgent(BaseAgent):
            def __init__(self, n):
                self._n = n

            @property
            def name(self) -> str:
                return f"Gated{self._n}"

            @property
            def version(self) -> str:
                return "1.0"

            async def execute(self, input_data: AgentInput) -> AgentOutput:
                nonlocal active, peak
                async with lock:
                    active += 1
                    peak = max(peak, active)
                await asyncio.sleep(0.05)
                async with lock:
                    active -= 1
                return _make_output(self.name)

        agents = [GatedAgent(i) for i in range(4)]
        orchestrator = SpecialistOrchestrator(
            max_concurrency=2, agent_timeout_seconds=10.0
        )
        await orchestrator.run(agents, _make_context())
        self.assertLessEqual(peak, 2)


# ─── 5. Error Scenario Tests ─────────────────────────────────────────────────

class TestErrorScenarios(unittest.IsolatedAsyncioTestCase):

    async def test_17a_mixed_success_failure(self):
        """A succeeds, B fails, C succeeds — all three outcomes in aggregate."""
        orchestrator = SpecialistOrchestrator(max_concurrency=4, agent_timeout_seconds=5.0)
        agents = [
            FakeAgent("AgentA"),
            FailingAgent("AgentB", RuntimeError("B is broken")),
            FakeAgent("AgentC"),
        ]
        result = await orchestrator.run(agents, _make_context())
        records = {r.agent_name: r for r in result.records}

        self.assertEqual(records["AgentA"].status, AgentState.SUCCESS)
        self.assertEqual(records["AgentB"].status, AgentState.FAILED)
        self.assertEqual(records["AgentC"].status, AgentState.SUCCESS)
        self.assertIsNotNone(records["AgentB"].error_message)

    async def test_17b_timeout_and_success_together(self):
        """One agent times out, another succeeds — both recorded cleanly."""
        orchestrator = SpecialistOrchestrator(
            max_concurrency=4, agent_timeout_seconds=0.1
        )
        agents = [SlowAgent("SlowX", sleep_seconds=5.0), FakeAgent("FastY")]
        result = await orchestrator.run(agents, _make_context())
        statuses = {r.agent_name: r.status for r in result.records}
        self.assertEqual(statuses["SlowX"], AgentState.TIMEOUT)
        self.assertEqual(statuses["FastY"], AgentState.SUCCESS)

    async def test_17c_retry_exhausted(self):
        """Agent always throws RecoverableAgentError → FAILED after exhausting retries."""
        policy = RetryPolicy(max_attempts=2, delay_seconds=0)
        orchestrator = SpecialistOrchestrator(
            max_concurrency=4,
            agent_timeout_seconds=10.0,
            retry_policy=policy,
        )

        class AlwaysFails(BaseAgent):
            @property
            def name(self) -> str:
                return "AlwaysFail"
            @property
            def version(self) -> str:
                return "1.0"
            async def execute(self, _):
                raise RecoverableAgentError("forever failing")

        result = await orchestrator.run([AlwaysFails()], _make_context())
        self.assertEqual(result.failed_agents, 1)
        self.assertEqual(result.records[0].status, AgentState.FAILED)


# ─── 6. Legacy Adapter Compatibility ─────────────────────────────────────────

class TestLegacyAdapterCompat(unittest.IsolatedAsyncioTestCase):

    def _make_legacy_context(self) -> MarketContext:
        return MarketContext(
            context_id="legacy-001",
            symbol="TCS.NS",
            provider="test",
            data_timestamp=datetime.now(timezone.utc),
            current_price=3280.80,
            technical_indicators={
                "20_day_high": 3310.0,
                "ema20": 3200.0,
                "ema50": 3150.0,
                "rsi": 65.0,
            },
            quality_status=DataQualityStatus.OK,
        )

    @patch(
        "backend.agents.technical_agent.run_technical_agent",
        new_callable=AsyncMock,
    )
    async def test_15_legacy_technical_agent_in_orchestrator(self, mock_tech):
        """TechnicalAgentAdapter participates in orchestrator run."""
        from backend.adapters.legacy_agents import TechnicalAgentAdapter

        mock_tech.return_value = MagicMock(
            technical_score=8.0,
            trend="BULLISH",
            setup="BREAKOUT",
            confirmation=True,
            model_dump=lambda: {
                "technical_score": 8.0,
                "trend": "BULLISH",
                "setup": "BREAKOUT",
                "confirmation": True,
            },
        )

        orchestrator = SpecialistOrchestrator(
            max_concurrency=4, agent_timeout_seconds=10.0,
            retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0),
        )
        result = await orchestrator.run([TechnicalAgentAdapter()], self._make_legacy_context())
        self.assertEqual(result.successful_agents, 1)
        self.assertEqual(result.records[0].agent_name, "TechnicalAgent")

    @patch(
        "backend.agents.risk_agent.run_risk_agent",
        new_callable=AsyncMock,
    )
    async def test_16_legacy_risk_agent_in_orchestrator(self, mock_risk):
        """RiskAgentAdapter participates in orchestrator run."""
        from backend.adapters.legacy_agents import RiskAgentAdapter

        mock_risk.return_value = MagicMock(
            risk_level="LOW",
            model_dump=lambda: {
                "risk_level": "LOW",
                "max_position_size_pct": 5.0,
                "stop_loss_pct": 2.0,
                "risk_summary": "Low risk.",
            },
        )

        orchestrator = SpecialistOrchestrator(
            max_concurrency=4, agent_timeout_seconds=10.0,
            retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0),
        )
        result = await orchestrator.run([RiskAgentAdapter()], self._make_legacy_context())
        self.assertEqual(result.successful_agents, 1)
        self.assertEqual(result.records[0].agent_name, "RiskAgent")

    async def test_17_no_external_api_calls(self):
        """Ensure orchestrator does NOT call Yahoo Finance or Groq in offline mode."""
        import backend.infrastructure.data_providers as dp
        original = dp.YFinanceProvider.get_market_context

        called = []

        def spy(*args, **kwargs):
            called.append(args)
            return original(*args, **kwargs)

        dp.YFinanceProvider.get_market_context = spy
        orchestrator = SpecialistOrchestrator(max_concurrency=2, agent_timeout_seconds=5.0)
        await orchestrator.run([FakeAgent("Offline")], _make_context())
        dp.YFinanceProvider.get_market_context = original
        self.assertEqual(called, [], "Provider was called — orchestrator must not fetch market data")


if __name__ == "__main__":
    unittest.main()
