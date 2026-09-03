"""
Tests for Phase 3.2 — TechnicalSpecialist.

All LLM calls are mocked.  No Groq calls.  No Yahoo Finance calls.
"""

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from backend.application.agent_registry import AgentRegistry
from backend.application.retry_policy import RetryPolicy
from backend.application.specialist_orchestrator import SpecialistOrchestrator
from backend.domain.schemas import (
    AgentInput,
    AgentOutput,
    AgentState,
    DataQualityStatus,
    MarketContext,
    SetupType,
    TechnicalPayload,
    TrendDirection,
    _TechnicalLLMResponse,
)
from backend.infrastructure.llm import (
    LLMClientError,
    LLMParseError,
    MockLLMClient,
)
from backend.specialists.technical_specialist import TechnicalSpecialist


# ─── Test helpers ─────────────────────────────────────────────────────────────

def _make_context(
    context_id: str = "ctx-tech-001",
    symbol: str = "TCS.NS",
    price: float = 3280.80,
    indicators: dict | None = None,
) -> MarketContext:
    if indicators is None:
        indicators = {
            "ema20": 3188.45,
            "ema50": 3133.12,
            "rsi": 73.90,
            "20_day_high": 3271.60,
        }
    return MarketContext(
        context_id=context_id,
        symbol=symbol,
        provider="test",
        data_timestamp=datetime.now(timezone.utc),
        current_price=price,
        technical_indicators=indicators,
        quality_status=DataQualityStatus.OK,
    )


def _make_llm_response(
    trend: TrendDirection = TrendDirection.BULLISH,
    setup: SetupType = SetupType.BREAKOUT,
    score: float = 8.0,
    confirmation: bool = True,
    confidence: float = 0.85,
) -> _TechnicalLLMResponse:
    return _TechnicalLLMResponse(
        trend=trend,
        setup=setup,
        technical_score=score,
        confirmation=confirmation,
        conclusion="Strong bullish breakout confirmed by EMA and RSI alignment.",
        invalidation_conditions=["Close below EMA20", "RSI drops below 50"],
        risks=["Overbought RSI may attract sellers"],
        assumptions=["Current trend continues"],
        confidence=confidence,
    )


def _make_specialist(fixed_response=None, raise_error=None) -> TechnicalSpecialist:
    mock_llm = MockLLMClient(fixed_response=fixed_response, raise_error=raise_error)
    return TechnicalSpecialist(llm_client=mock_llm)


# ─── 1. Specialist construction ───────────────────────────────────────────────

class TestTechnicalSpecialistCreation(unittest.TestCase):
    def test_1_creation(self):
        """TechnicalSpecialist can be instantiated with a MockLLMClient."""
        spec = _make_specialist(_make_llm_response())
        self.assertEqual(spec.name, "TechnicalSpecialist")
        self.assertEqual(spec.version, "1.0")

    def test_13_registry_registration(self):
        """Can be registered in AgentRegistry."""
        spec = _make_specialist(_make_llm_response())
        registry = AgentRegistry()
        registry.register(spec)
        self.assertIn("TechnicalSpecialist", registry)
        retrieved = registry.get("TechnicalSpecialist")
        self.assertIs(retrieved, spec)


# ─── 2-11. Execution tests ────────────────────────────────────────────────────

class TestTechnicalSpecialistExecution(unittest.IsolatedAsyncioTestCase):

    def _input(self, ctx: MarketContext) -> AgentInput:
        return AgentInput(symbol=ctx.symbol, market_context=ctx)

    async def test_2_valid_context_execution(self):
        """Valid MarketContext produces AgentOutput with SUCCESS status."""
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(self._input(_make_context()))

        self.assertIsInstance(output, AgentOutput)
        self.assertEqual(output.status, AgentState.SUCCESS)
        self.assertEqual(output.agent_name, "TechnicalSpecialist")

    async def test_3_agent_output_schema(self):
        """AgentOutput has all required fields populated."""
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(self._input(_make_context()))

        self.assertTrue(output.agent_name)
        self.assertTrue(output.version)
        self.assertTrue(output.model)
        self.assertIsNotNone(output.data_timestamp)
        self.assertGreater(output.confidence, 0.0)
        self.assertTrue(output.conclusion)
        self.assertIsNotNone(output.raw_data)

    async def test_4_evidence_generation(self):
        """raw_data.evidence contains at least one TechnicalIndicatorEvidence."""
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(self._input(_make_context()))

        payload = TechnicalPayload.model_validate(output.raw_data)
        self.assertGreater(len(payload.evidence), 0)

    async def test_5_numerical_values_originate_from_market_context(self):
        """
        CRITICAL: indicator values in evidence MUST match MarketContext exactly.
        The LLM interprets; it does not replace numeric truth.
        """
        ctx = _make_context(indicators={
            "ema20": 1234.56,
            "ema50": 2345.67,
            "rsi": 44.1,
            "20_day_high": 9999.0,
        }, price=1300.0)
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(self._input(ctx))

        payload = TechnicalPayload.model_validate(output.raw_data)
        ev_map = {e.name: e.value for e in payload.evidence}

        self.assertAlmostEqual(ev_map["EMA20"], 1234.56, places=2)
        self.assertAlmostEqual(ev_map["EMA50"], 2345.67, places=2)
        self.assertAlmostEqual(ev_map["RSI14"], 44.1, places=1)
        self.assertAlmostEqual(ev_map["20DayHigh"], 9999.0, places=1)
        self.assertAlmostEqual(ev_map["CurrentPrice"], 1300.0, places=1)

    async def test_6_missing_technical_data(self):
        """Empty indicators dict returns FAILED output, not an exception."""
        ctx = _make_context(indicators={})
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(self._input(ctx))

        self.assertEqual(output.status, AgentState.FAILED)
        self.assertIsNotNone(output.error)
        self.assertEqual(output.error.code, "INVALID_INPUT")

    async def test_7_invalid_input_negative_price(self):
        """Non-positive price triggers INVALID_INPUT failure."""
        ctx = _make_context(price=-1.0)
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(self._input(ctx))

        self.assertEqual(output.status, AgentState.FAILED)
        self.assertEqual(output.error.code, "INVALID_INPUT")

    async def test_8_mocked_llm_success(self):
        """MockLLMClient returning a valid response → SUCCESS."""
        llm_resp = _make_llm_response(
            trend=TrendDirection.BEARISH,
            setup=SetupType.REVERSAL,
            score=3.5,
            confirmation=False,
            confidence=0.4,
        )
        spec = _make_specialist(llm_resp)
        output = await spec.execute(self._input(_make_context()))

        self.assertEqual(output.status, AgentState.SUCCESS)
        payload = TechnicalPayload.model_validate(output.raw_data)
        self.assertEqual(payload.trend, TrendDirection.BEARISH)
        self.assertEqual(payload.setup, SetupType.REVERSAL)
        self.assertAlmostEqual(payload.technical_score, 3.5)
        self.assertFalse(payload.confirmation)

    async def test_9_mocked_llm_parse_error(self):
        """LLMParseError from client → FAILED with LLM_PARSE_ERROR code."""
        spec = _make_specialist(
            raise_error=LLMParseError("Response JSON was truncated")
        )
        output = await spec.execute(self._input(_make_context()))

        self.assertEqual(output.status, AgentState.FAILED)
        self.assertEqual(output.error.code, "LLM_PARSE_ERROR")

    async def test_10_llm_client_error(self):
        """LLMClientError → FAILED with LLM_CLIENT_ERROR code."""
        spec = _make_specialist(
            raise_error=LLMClientError("Groq 503 Service Unavailable")
        )
        output = await spec.execute(self._input(_make_context()))

        self.assertEqual(output.status, AgentState.FAILED)
        self.assertEqual(output.error.code, "LLM_CLIENT_ERROR")

    async def test_11_timeout_via_orchestrator(self):
        """
        Simulates timeout by running with a very short timeout via orchestrator.
        The record should carry TIMEOUT status.
        """
        class SlowLLMClient(MockLLMClient):
            async def generate_structured(self, *args, **kwargs):
                import asyncio
                await asyncio.sleep(10.0)

        spec = TechnicalSpecialist(llm_client=SlowLLMClient())
        orchestrator = SpecialistOrchestrator(
            max_concurrency=1,
            agent_timeout_seconds=0.05,
            retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0),
        )
        result = await orchestrator.run([spec], _make_context())

        self.assertEqual(result.timed_out_agents, 1)
        self.assertEqual(result.records[0].status, AgentState.TIMEOUT)

    async def test_14_context_id_propagation(self):
        """context_id from MarketContext appears in the orchestrator execution record."""
        spec = _make_specialist(_make_llm_response())
        orchestrator = SpecialistOrchestrator(
            max_concurrency=1, agent_timeout_seconds=10.0,
            retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0),
        )
        ctx = _make_context(context_id="ctx-trace-abc")
        result = await orchestrator.run([spec], ctx)

        self.assertEqual(result.context_id, "ctx-trace-abc")
        self.assertEqual(result.records[0].context_id, "ctx-trace-abc")


# ─── Numerical integrity tests ────────────────────────────────────────────────

class TestNumericalIntegrity(unittest.IsolatedAsyncioTestCase):
    """
    Prove that TechnicalSpecialist does NOT silently recalculate or substitute
    MarketContext indicator values. The LLM is the interpreter, not the source.
    """

    async def test_ema20_value_unchanged(self):
        """EMA20 in evidence equals MarketContext value exactly."""
        ctx = _make_context(indicators={"ema20": 5555.55, "rsi": 50.0})
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(AgentInput(symbol="TEST", market_context=ctx))
        payload = TechnicalPayload.model_validate(output.raw_data)
        ev_map = {e.name: e.value for e in payload.evidence}
        self.assertAlmostEqual(ev_map["EMA20"], 5555.55, places=2)

    async def test_rsi_value_unchanged(self):
        """RSI14 in evidence equals MarketContext RSI exactly."""
        ctx = _make_context(indicators={"ema20": 100.0, "rsi": 29.3})
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(AgentInput(symbol="TEST", market_context=ctx))
        payload = TechnicalPayload.model_validate(output.raw_data)
        ev_map = {e.name: e.value for e in payload.evidence}
        self.assertAlmostEqual(ev_map["RSI14"], 29.3, places=1)

    async def test_missing_indicator_absent_from_evidence(self):
        """If an indicator is absent from MarketContext it should not appear in evidence."""
        ctx = _make_context(indicators={"rsi": 55.0})  # no EMA
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(AgentInput(symbol="TEST", market_context=ctx))
        payload = TechnicalPayload.model_validate(output.raw_data)
        ev_names = {e.name for e in payload.evidence}
        self.assertNotIn("EMA20", ev_names)
        self.assertNotIn("EMA50", ev_names)


# ─── Orchestrator integration ────────────────────────────────────────────────

class TestOrchestratorIntegration(unittest.IsolatedAsyncioTestCase):

    async def test_12_orchestrator_integration(self):
        """TechnicalSpecialist executes through SpecialistOrchestrator."""
        spec = _make_specialist(_make_llm_response())
        orchestrator = SpecialistOrchestrator(
            max_concurrency=2,
            agent_timeout_seconds=10.0,
            retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0),
        )
        result = await orchestrator.run([spec], _make_context())

        self.assertEqual(result.total_agents, 1)
        self.assertEqual(result.successful_agents, 1)
        record = result.records[0]
        self.assertEqual(record.agent_name, "TechnicalSpecialist")
        self.assertIsNotNone(record.output)
        self.assertEqual(record.output.status, AgentState.SUCCESS)

    async def test_parallel_alongside_other_agents(self):
        """TechnicalSpecialist runs concurrently with other specialists."""
        from tests.test_specialist_runtime import FakeAgent

        tech = _make_specialist(_make_llm_response())
        fake_a = FakeAgent("MacroStub")
        fake_b = FakeAgent("MomentumStub")

        orchestrator = SpecialistOrchestrator(
            max_concurrency=3,
            agent_timeout_seconds=10.0,
            retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0),
        )
        result = await orchestrator.run([tech, fake_a, fake_b], _make_context())

        self.assertEqual(result.total_agents, 3)
        self.assertEqual(result.successful_agents, 3)
        names = {r.agent_name for r in result.records}
        self.assertIn("TechnicalSpecialist", names)


# ─── Legacy compatibility ─────────────────────────────────────────────────────

class TestLegacyCompatibility(unittest.IsolatedAsyncioTestCase):

    @patch(
        "backend.agents.technical_agent.run_technical_agent",
        new_callable=AsyncMock,
    )
    async def test_15_legacy_technical_agent_still_works(self, mock_tech):
        """TechnicalAgentAdapter (legacy) remains functional alongside new specialist."""
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
        adapter = TechnicalAgentAdapter()
        ctx = _make_context()
        output = await adapter.execute(AgentInput(symbol="TCS.NS", market_context=ctx))

        self.assertEqual(output.status, AgentState.SUCCESS)
        self.assertEqual(output.agent_name, "TechnicalAgent")  # legacy name preserved

    async def test_both_can_coexist_in_registry(self):
        """New TechnicalSpecialist and legacy TechnicalAgentAdapter have different names."""
        from backend.adapters.legacy_agents import TechnicalAgentAdapter

        registry = AgentRegistry()
        registry.register(TechnicalAgentAdapter())          # name = "TechnicalAgent"
        registry.register(_make_specialist(_make_llm_response()))  # name = "TechnicalSpecialist"

        self.assertIn("TechnicalAgent", registry)
        self.assertIn("TechnicalSpecialist", registry)
        self.assertEqual(len(registry), 2)

    async def test_no_external_api_calls(self):
        """Orchestrator + TechnicalSpecialist do NOT call Yahoo Finance."""
        called = []
        import backend.infrastructure.data_providers as dp
        original = dp.YFinanceProvider.get_market_context

        def spy(*args, **kwargs):
            called.append(args)
            return original(*args, **kwargs)

        dp.YFinanceProvider.get_market_context = spy
        spec = _make_specialist(_make_llm_response())
        orchestrator = SpecialistOrchestrator(max_concurrency=1, agent_timeout_seconds=5.0)
        await orchestrator.run([spec], _make_context())
        dp.YFinanceProvider.get_market_context = original

        self.assertEqual(called, [], "YFinanceProvider was unexpectedly called")


if __name__ == "__main__":
    unittest.main()
