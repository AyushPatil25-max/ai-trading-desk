"""
Tests for Phase 3.3 — MomentumSpecialist.

All LLM calls are mocked. No Groq calls. No Yahoo Finance calls.
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
    MomentumDirection,
    MomentumPayload,
    MomentumStrength,
    SetupType,
    TrendDirection,
    _MomentumLLMResponse,
    _TechnicalLLMResponse,
)
from backend.infrastructure.llm import (
    LLMClientError,
    LLMParseError,
    MockLLMClient,
)
from backend.specialists.momentum_specialist import MomentumSpecialist
from backend.specialists.technical_specialist import TechnicalSpecialist


# ─── Test helpers ─────────────────────────────────────────────────────────────

def _make_context(
    context_id: str = "ctx-mom-001",
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
    direction: MomentumDirection = MomentumDirection.BULLISH,
    strength: MomentumStrength = MomentumStrength.STRONG,
    confirmation: bool = True,
    confidence: float = 0.88,
) -> _MomentumLLMResponse:
    return _MomentumLLMResponse(
        momentum_direction=direction,
        momentum_strength=strength,
        confirmation=confirmation,
        conclusion="Strong bullish momentum with accelerating price expansion above EMAs.",
        invalidation_conditions=["Price falls below EMA20", "RSI dips below 50"],
        risks=["Overbought RSI territory poses short-term pullback risk"],
        assumptions=["Upward velocity persists across moving averages"],
        confidence=confidence,
    )


def _make_specialist(fixed_response=None, raise_error=None) -> MomentumSpecialist:
    mock_llm = MockLLMClient(fixed_response=fixed_response, raise_error=raise_error)
    return MomentumSpecialist(llm_client=mock_llm)


# ─── 1. Creation and Registry Tests ──────────────────────────────────────────

class TestMomentumSpecialistCreation(unittest.TestCase):
    def test_1_creation(self):
        """MomentumSpecialist can be instantiated."""
        spec = _make_specialist(_make_llm_response())
        self.assertEqual(spec.name, "MomentumSpecialist")
        self.assertEqual(spec.version, "1.0")

    def test_11_registry_registration(self):
        """Can be registered with AgentRegistry alongside other specialists."""
        from backend.adapters.legacy_agents import TechnicalAgentAdapter, RiskAgentAdapter

        registry = AgentRegistry()
        mom_spec = _make_specialist(_make_llm_response())
        tech_spec = TechnicalSpecialist(llm_client=MockLLMClient())
        legacy_tech = TechnicalAgentAdapter()
        legacy_risk = RiskAgentAdapter()

        registry.register(mom_spec)
        registry.register(tech_spec)
        registry.register(legacy_tech)
        registry.register(legacy_risk)

        self.assertIn("MomentumSpecialist", registry)
        self.assertIn("TechnicalSpecialist", registry)
        self.assertIn("TechnicalAgent", registry)
        self.assertIn("RiskAgent", registry)
        self.assertEqual(len(registry), 4)


# ─── 2. Execution and Evidence Tests ─────────────────────────────────────────

class TestMomentumSpecialistExecution(unittest.IsolatedAsyncioTestCase):

    def _input(self, ctx: MarketContext) -> AgentInput:
        return AgentInput(symbol=ctx.symbol, market_context=ctx)

    async def test_2_valid_execution(self):
        """Valid MarketContext produces SUCCESS AgentOutput."""
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(self._input(_make_context()))

        self.assertIsInstance(output, AgentOutput)
        self.assertEqual(output.status, AgentState.SUCCESS)
        self.assertEqual(output.agent_name, "MomentumSpecialist")
        self.assertEqual(output.version, "1.0")
        self.assertGreater(output.confidence, 0.0)

    async def test_3_invalid_market_context_negative_price(self):
        """Negative price triggers INVALID_INPUT failure."""
        ctx = _make_context(price=-50.0)
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(self._input(ctx))

        self.assertEqual(output.status, AgentState.FAILED)
        self.assertIsNotNone(output.error)
        self.assertEqual(output.error.code, "INVALID_INPUT")

    async def test_4_missing_momentum_data_empty_indicators(self):
        """Empty indicators triggers INVALID_INPUT failure gracefully."""
        ctx = _make_context(indicators={})
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(self._input(ctx))

        self.assertEqual(output.status, AgentState.FAILED)
        self.assertEqual(output.error.code, "INVALID_INPUT")

    async def test_5_deterministic_evidence_structure(self):
        """Evidence list includes available indicators and unavailable placeholders."""
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(self._input(_make_context()))

        payload = MomentumPayload.model_validate(output.raw_data)
        ev_dict = {e.name: e for e in payload.evidence}

        self.assertIn("Price_vs_EMA20", ev_dict)
        self.assertIn("Price_vs_EMA50", ev_dict)
        self.assertIn("EMA_Spread_20_50", ev_dict)
        self.assertIn("RSI14", ev_dict)
        self.assertIn("Distance_From_20D_High", ev_dict)
        self.assertIn("MACD_Histogram", ev_dict)

        self.assertTrue(ev_dict["RSI14"].available)
        self.assertFalse(ev_dict["MACD_Histogram"].available)
        self.assertIsNone(ev_dict["MACD_Histogram"].value)


# ─── 3. Numerical Integrity Tests ────────────────────────────────────────────

class TestMomentumNumericalIntegrity(unittest.IsolatedAsyncioTestCase):
    """
    Verify that all numerical momentum metrics are computed deterministically
    from MarketContext without fabrication or alteration by the LLM.
    """

    async def test_6_numerical_integrity_exact_calculations(self):
        price = 100.0
        ema20 = 90.0
        ema50 = 80.0
        rsi = 65.5
        high_20d = 105.0

        ctx = _make_context(
            price=price,
            indicators={
                "ema20": ema20,
                "ema50": ema50,
                "rsi": rsi,
                "20_day_high": high_20d,
            },
        )

        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(AgentInput(symbol="TEST", market_context=ctx))
        payload = MomentumPayload.model_validate(output.raw_data)
        ev_dict = {e.name: e for e in payload.evidence}

        # Price vs EMA20: (100 - 90) / 90 * 100 = +11.11%
        expected_price_ema20 = round(((100.0 - 90.0) / 90.0) * 100.0, 2)
        self.assertAlmostEqual(ev_dict["Price_vs_EMA20"].value, expected_price_ema20, places=2)

        # Price vs EMA50: (100 - 80) / 80 * 100 = +25.00%
        expected_price_ema50 = round(((100.0 - 80.0) / 80.0) * 100.0, 2)
        self.assertAlmostEqual(ev_dict["Price_vs_EMA50"].value, expected_price_ema50, places=2)

        # EMA Spread: (90 - 80) / 80 * 100 = +12.50%
        expected_spread = round(((90.0 - 80.0) / 80.0) * 100.0, 2)
        self.assertAlmostEqual(ev_dict["EMA_Spread_20_50"].value, expected_spread, places=2)

        # RSI: 65.5
        self.assertAlmostEqual(ev_dict["RSI14"].value, 65.5, places=1)

        # Distance from 20D High: (100 - 105) / 105 * 100 = -4.76%
        expected_dist_high = round(((100.0 - 105.0) / 105.0) * 100.0, 2)
        self.assertAlmostEqual(ev_dict["Distance_From_20D_High"].value, expected_dist_high, places=2)

    async def test_partial_indicators_reported_as_unavailable(self):
        """When EMA50 is absent, Price_vs_EMA50 is marked unavailable."""
        ctx = _make_context(
            price=100.0,
            indicators={
                "ema20": 95.0,
                "rsi": 50.0,
            },
        )
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(AgentInput(symbol="TEST", market_context=ctx))
        payload = MomentumPayload.model_validate(output.raw_data)
        ev_dict = {e.name: e for e in payload.evidence}

        self.assertTrue(ev_dict["Price_vs_EMA20"].available)
        self.assertFalse(ev_dict["Price_vs_EMA50"].available)
        self.assertIsNone(ev_dict["Price_vs_EMA50"].value)


# ─── 4. Mock LLM and Failure Handling Tests ─────────────────────────────────

class TestMomentumFailureAndMocking(unittest.IsolatedAsyncioTestCase):

    def _input(self, ctx: MarketContext) -> AgentInput:
        return AgentInput(symbol=ctx.symbol, market_context=ctx)

    async def test_7_mocked_llm_success(self):
        """Mocked LLM returns structured response faithfully mapped to MomentumPayload."""
        resp = _make_llm_response(
            direction=MomentumDirection.BEARISH,
            strength=MomentumStrength.WEAK,
            confirmation=False,
            confidence=0.45,
        )
        spec = _make_specialist(resp)
        output = await spec.execute(self._input(_make_context()))

        self.assertEqual(output.status, AgentState.SUCCESS)
        payload = MomentumPayload.model_validate(output.raw_data)
        self.assertEqual(payload.momentum_direction, MomentumDirection.BEARISH)
        self.assertEqual(payload.momentum_strength, MomentumStrength.WEAK)
        self.assertFalse(payload.confirmation)
        self.assertEqual(output.confidence, 0.45)

    async def test_8_malformed_llm_response(self):
        """LLMParseError turns into structured FAILED AgentOutput."""
        spec = _make_specialist(raise_error=LLMParseError("Unterminated JSON"))
        output = await spec.execute(self._input(_make_context()))

        self.assertEqual(output.status, AgentState.FAILED)
        self.assertIsNotNone(output.error)
        self.assertEqual(output.error.code, "LLM_PARSE_ERROR")

    async def test_9_llm_failure(self):
        """LLMClientError turns into structured FAILED AgentOutput."""
        spec = _make_specialist(raise_error=LLMClientError("Provider Rate Limit Exceeded"))
        output = await spec.execute(self._input(_make_context()))

        self.assertEqual(output.status, AgentState.FAILED)
        self.assertIsNotNone(output.error)
        self.assertEqual(output.error.code, "LLM_CLIENT_ERROR")

    async def test_10_context_id_propagation(self):
        """context_id is propagated correctly in orchestrator run."""
        spec = _make_specialist(_make_llm_response())
        orchestrator = SpecialistOrchestrator(
            max_concurrency=1,
            agent_timeout_seconds=5.0,
            retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0),
        )
        ctx = _make_context(context_id="ctx-mom-trace-42")
        result = await orchestrator.run([spec], ctx)

        self.assertEqual(result.context_id, "ctx-mom-trace-42")
        self.assertEqual(result.records[0].context_id, "ctx-mom-trace-42")


# ─── 5. Orchestrator and Multi-Specialist Parallel Execution ─────────────────

class TestMomentumOrchestratorIntegration(unittest.IsolatedAsyncioTestCase):

    async def test_12_orchestrator_execution(self):
        """MomentumSpecialist runs cleanly through SpecialistOrchestrator."""
        spec = _make_specialist(_make_llm_response())
        orchestrator = SpecialistOrchestrator(
            max_concurrency=2,
            agent_timeout_seconds=10.0,
            retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0),
        )
        result = await orchestrator.run([spec], _make_context())

        self.assertEqual(result.total_agents, 1)
        self.assertEqual(result.successful_agents, 1)
        self.assertEqual(result.records[0].agent_name, "MomentumSpecialist")
        self.assertEqual(result.records[0].output.status, AgentState.SUCCESS)

    async def test_13_parallel_execution_with_technical_specialist(self):
        """
        Both TechnicalSpecialist and MomentumSpecialist run concurrently
        against the SAME shared MarketContext snapshot.
        """
        tech_llm = _TechnicalLLMResponse(
            trend=TrendDirection.BULLISH,
            setup=SetupType.BREAKOUT,
            technical_score=8.5,
            confirmation=True,
            conclusion="Bullish breakout setup.",
            invalidation_conditions=["Close below EMA20"],
            risks=["Near resistance"],
            assumptions=["High volume holds"],
            confidence=0.9,
        )
        mom_llm = _make_llm_response(
            direction=MomentumDirection.BULLISH,
            strength=MomentumStrength.STRONG,
            confirmation=True,
            confidence=0.85,
        )

        tech_specialist = TechnicalSpecialist(llm_client=MockLLMClient(fixed_response=tech_llm))
        mom_specialist = MomentumSpecialist(llm_client=MockLLMClient(fixed_response=mom_llm))

        orchestrator = SpecialistOrchestrator(
            max_concurrency=4,
            agent_timeout_seconds=10.0,
            retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0),
        )
        ctx = _make_context(context_id="ctx-shared-tech-mom")
        result = await orchestrator.run([tech_specialist, mom_specialist], ctx)

        self.assertEqual(result.total_agents, 2)
        self.assertEqual(result.successful_agents, 2)
        self.assertEqual(result.failed_agents, 0)
        self.assertEqual(result.context_id, "ctx-shared-tech-mom")

        # Verify records and outputs
        names = {r.agent_name for r in result.records}
        self.assertEqual(names, {"TechnicalSpecialist", "MomentumSpecialist"})
        for record in result.records:
            self.assertEqual(record.context_id, "ctx-shared-tech-mom")
            self.assertEqual(record.status, AgentState.SUCCESS)

    @patch("backend.agents.technical_agent.run_technical_agent", new_callable=AsyncMock)
    @patch("backend.agents.risk_agent.run_risk_agent", new_callable=AsyncMock)
    async def test_14_legacy_compatibility(self, mock_risk, mock_tech):
        """Legacy Technical and Risk adapters run alongside MomentumSpecialist."""
        from backend.adapters.legacy_agents import TechnicalAgentAdapter, RiskAgentAdapter

        mock_tech.return_value = MagicMock(
            technical_score=7.5,
            trend="BULLISH",
            setup="PULLBACK",
            confirmation=True,
            model_dump=lambda: {"technical_score": 7.5, "trend": "BULLISH", "setup": "PULLBACK", "confirmation": True},
        )
        mock_risk.return_value = MagicMock(
            risk_level="MEDIUM",
            model_dump=lambda: {"risk_level": "MEDIUM", "max_position_size_pct": 5.0, "stop_loss_pct": 2.5, "risk_summary": "Moderate risk."},
        )

        legacy_tech = TechnicalAgentAdapter()
        legacy_risk = RiskAgentAdapter()
        mom_specialist = _make_specialist(_make_llm_response())

        orchestrator = SpecialistOrchestrator(
            max_concurrency=4,
            agent_timeout_seconds=10.0,
            retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0),
        )
        result = await orchestrator.run([legacy_tech, legacy_risk, mom_specialist], _make_context())

        self.assertEqual(result.total_agents, 3)
        self.assertEqual(result.successful_agents, 3)
        names = {r.agent_name for r in result.records}
        self.assertEqual(names, {"TechnicalAgent", "RiskAgent", "MomentumSpecialist"})


if __name__ == "__main__":
    unittest.main()
