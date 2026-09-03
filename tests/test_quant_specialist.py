"""
Tests for Phase 3.4 — QuantSpecialist.

All LLM calls are mocked. No Groq calls. No Yahoo Finance calls.
"""

import math
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
    MomentumStrength,
    QuantMetricRecord,
    QuantPayload,
    QuantRiskCharacterization,
    QuantStatisticalRegime,
    SetupType,
    TrendDirection,
    _MomentumLLMResponse,
    _QuantLLMResponse,
    _TechnicalLLMResponse,
)
from backend.infrastructure.llm import (
    LLMClientError,
    LLMParseError,
    MockLLMClient,
)
from backend.specialists.momentum_specialist import MomentumSpecialist
from backend.specialists.quant_specialist import QuantSpecialist
from backend.specialists.technical_specialist import TechnicalSpecialist


# ─── Test helpers ─────────────────────────────────────────────────────────────

def _make_ohlcv(closes, volumes=None) -> list:
    """Build minimal OHLCV rows."""
    if volumes is None:
        volumes = [2_000_000] * len(closes)
    return [
        {
            "date": f"2024-01-{i + 1:02d}T00:00:00+00:00",
            "open": c,
            "high": c * 1.01,
            "low": c * 0.99,
            "close": c,
            "volume": v,
        }
        for i, (c, v) in enumerate(zip(closes, volumes))
    ]


def _make_context(
    context_id: str = "ctx-quant-001",
    symbol: str = "TCS.NS",
    price: float = 3280.80,
    ohlcv: list | None = None,
    indicators: dict | None = None,
) -> MarketContext:
    if ohlcv is None:
        ohlcv = _make_ohlcv([3180.0, 3200.0, 3220.0, 3250.0, 3280.0])
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
        ohlcv_historical=ohlcv,
        technical_indicators=indicators,
        quality_status=DataQualityStatus.OK,
    )


def _make_llm_response(
    regime: QuantStatisticalRegime = QuantStatisticalRegime.NORMAL_VOLATILITY,
    risk: QuantRiskCharacterization = QuantRiskCharacterization.MODERATE,
    anomaly: bool = False,
    strength: float = 0.65,
    confidence: float = 0.75,
) -> _QuantLLMResponse:
    return _QuantLLMResponse(
        statistical_regime=regime,
        risk_characterization=risk,
        anomaly_detected=anomaly,
        statistical_strength=strength,
        conclusion="Normal volatility regime with moderate upward trend; limited statistical depth due to 5D window.",
        invalidation_conditions=["Volatility spike > 2σ", "RSI drops below 40"],
        risks=["5-day window provides statistically limited evidence"],
        assumptions=["Current volatility persists short-term"],
        confidence=confidence,
    )


def _make_specialist(fixed_response=None, raise_error=None) -> QuantSpecialist:
    mock_llm = MockLLMClient(fixed_response=fixed_response, raise_error=raise_error)
    return QuantSpecialist(llm_client=mock_llm)


# ─── 1. Specialist creation and registry ──────────────────────────────────────

class TestQuantSpecialistCreation(unittest.TestCase):
    def test_1_creation(self):
        spec = _make_specialist(_make_llm_response())
        self.assertEqual(spec.name, "QuantSpecialist")
        self.assertEqual(spec.version, "1.0")

    def test_2_registry_registration(self):
        """Can be registered with AgentRegistry; does not collide."""
        registry = AgentRegistry()
        registry.register(_make_specialist(_make_llm_response()))
        registry.register(TechnicalSpecialist(llm_client=MockLLMClient()))
        registry.register(MomentumSpecialist(llm_client=MockLLMClient()))

        self.assertIn("QuantSpecialist", registry)
        self.assertIn("TechnicalSpecialist", registry)
        self.assertIn("MomentumSpecialist", registry)
        self.assertEqual(len(registry), 3)


# ─── 3. Valid execution ───────────────────────────────────────────────────────

class TestQuantSpecialistExecution(unittest.IsolatedAsyncioTestCase):

    def _input(self, ctx: MarketContext) -> AgentInput:
        return AgentInput(symbol=ctx.symbol, market_context=ctx)

    async def test_3_valid_execution(self):
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(self._input(_make_context()))

        self.assertIsInstance(output, AgentOutput)
        self.assertEqual(output.status, AgentState.SUCCESS)
        self.assertEqual(output.agent_name, "QuantSpecialist")
        self.assertIsNotNone(output.raw_data)

    async def test_4_historical_data_validation(self):
        """No OHLCV + no indicators → INVALID_INPUT."""
        ctx = _make_context(ohlcv=[], indicators={})
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(self._input(ctx))

        self.assertEqual(output.status, AgentState.FAILED)
        self.assertEqual(output.error.code, "INVALID_INPUT")

    async def test_invalid_price(self):
        """Negative price → INVALID_INPUT."""
        ctx = _make_context(price=-1.0)
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(self._input(ctx))

        self.assertEqual(output.status, AgentState.FAILED)
        self.assertEqual(output.error.code, "INVALID_INPUT")

    async def test_indicators_only_no_ohlcv(self):
        """Technical indicators alone (no OHLCV) → at least EMA spread + RSI extremity → SUCCESS."""
        ctx = _make_context(
            ohlcv=[],
            indicators={"ema20": 3200.0, "ema50": 3100.0, "rsi": 65.0},
        )
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(self._input(ctx))
        # 2 available metrics (ema_spread, rsi_extremity) → above MIN_AVAILABLE_METRICS
        self.assertEqual(output.status, AgentState.SUCCESS)


# ─── 5-7. Metric-level tests ─────────────────────────────────────────────────

class TestQuantMetricValues(unittest.IsolatedAsyncioTestCase):

    async def test_5_return_calculation(self):
        """Cumulative return is computed correctly from OHLCV."""
        closes = [100.0, 102.0, 104.0, 106.0, 110.0]
        ctx = _make_context(price=110.0, ohlcv=_make_ohlcv(closes))
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(AgentInput(symbol="TEST", market_context=ctx))

        payload = QuantPayload.model_validate(output.raw_data)
        rec_map = {m.metric_name: m for m in payload.metrics}

        self.assertIn("cumulative_return_5d", rec_map)
        ret_record = rec_map["cumulative_return_5d"]
        self.assertTrue(ret_record.available)
        expected = (110.0 - 100.0) / 100.0 * 100.0
        self.assertAlmostEqual(ret_record.value, expected, places=4)

    async def test_6_volatility_calculation(self):
        """Realized volatility is ≥ 0 and correctly computed."""
        closes = [100.0, 110.0, 99.0, 105.0, 108.0]
        ctx = _make_context(price=108.0, ohlcv=_make_ohlcv(closes))
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(AgentInput(symbol="TEST", market_context=ctx))

        payload = QuantPayload.model_validate(output.raw_data)
        rec_map = {m.metric_name: m for m in payload.metrics}

        vol_record = rec_map.get("realized_volatility_5d")
        self.assertIsNotNone(vol_record)
        if vol_record.available:
            self.assertGreaterEqual(vol_record.value, 0.0)

    async def test_7_drawdown_is_unavailable(self):
        """20-day max drawdown must be explicitly unavailable."""
        ctx = _make_context()
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(AgentInput(symbol="TEST", market_context=ctx))

        payload = QuantPayload.model_validate(output.raw_data)
        rec_map = {m.metric_name: m for m in payload.metrics}

        dd = rec_map.get("max_drawdown_20d")
        self.assertIsNotNone(dd)
        self.assertFalse(dd.available)
        self.assertIsNone(dd.value)
        self.assertTrue(dd.unavailable_reason)

    async def test_8_insufficient_ohlcv_data_single_row(self):
        """Single OHLCV row → return metrics unavailable, but RSI/EMA still available."""
        ctx = _make_context(price=100.0, ohlcv=_make_ohlcv([100.0]))
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(AgentInput(symbol="TEST", market_context=ctx))

        # Should still succeed via indicator-derived metrics
        self.assertEqual(output.status, AgentState.SUCCESS)
        payload = QuantPayload.model_validate(output.raw_data)
        rec_map = {m.metric_name: m for m in payload.metrics}

        # Return from single row → unavailable
        self.assertFalse(rec_map["cumulative_return_5d"].available)

    async def test_9_nan_handling(self):
        """NaN closes are excluded; calculation proceeds with valid data."""
        ohlcv = [
            {"date": "2024-01-01", "open": 100, "high": 101, "low": 99, "close": float("nan"), "volume": 1000},
            {"date": "2024-01-02", "open": 105, "high": 106, "low": 104, "close": 105.0, "volume": 1000},
            {"date": "2024-01-03", "open": 110, "high": 111, "low": 109, "close": 110.0, "volume": 1000},
        ]
        ctx = _make_context(price=110.0, ohlcv=ohlcv)
        spec = _make_specialist(_make_llm_response())
        # Must not raise
        output = await spec.execute(AgentInput(symbol="TEST", market_context=ctx))
        self.assertIn(output.status, [AgentState.SUCCESS, AgentState.FAILED])
        # If failed, must be structured
        if output.status == AgentState.FAILED:
            self.assertIsNotNone(output.error)

    async def test_10_infinity_handling(self):
        """Inf values in indicators are guarded."""
        ctx = _make_context(
            ohlcv=_make_ohlcv([100.0, 110.0, 120.0]),
            indicators={"ema20": float("inf"), "ema50": 100.0, "rsi": 55.0},
        )
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(AgentInput(symbol="TEST", market_context=ctx))
        self.assertIn(output.status, [AgentState.SUCCESS, AgentState.FAILED])

    async def test_11_zero_denominator_handling(self):
        """EMA50=0 → ema_spread_pct unavailable; no exception raised."""
        ctx = _make_context(
            ohlcv=_make_ohlcv([100.0, 110.0, 120.0]),
            indicators={"ema20": 100.0, "ema50": 0.0, "rsi": 55.0},
        )
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(AgentInput(symbol="TEST", market_context=ctx))
        # Must not raise; EMA spread unavailable, but RSI extremity is available
        self.assertEqual(output.status, AgentState.SUCCESS)
        payload = QuantPayload.model_validate(output.raw_data)
        rec_map = {m.metric_name: m for m in payload.metrics}
        self.assertFalse(rec_map["ema_spread_pct"].available)


# ─── 12. Provenance ───────────────────────────────────────────────────────────

class TestQuantProvenance(unittest.IsolatedAsyncioTestCase):

    async def test_12_provenance_fields_present(self):
        """Every QuantMetricRecord must have required provenance fields populated."""
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(AgentInput(
            symbol="TEST", market_context=_make_context()
        ))
        payload = QuantPayload.model_validate(output.raw_data)

        for rec in payload.metrics:
            self.assertTrue(rec.metric_name, f"metric_name empty: {rec}")
            self.assertTrue(rec.unit, f"unit empty for {rec.metric_name}")
            self.assertTrue(rec.window, f"window empty for {rec.metric_name}")
            self.assertTrue(rec.source, f"source empty for {rec.metric_name}")
            self.assertTrue(rec.calculation_method, f"method empty for {rec.metric_name}")
            self.assertIsNotNone(rec.data_timestamp, f"timestamp None for {rec.metric_name}")
            if not rec.available:
                self.assertTrue(
                    rec.unavailable_reason,
                    f"Missing unavailable_reason for {rec.metric_name}"
                )


# ─── 13-14. Numerical integrity ───────────────────────────────────────────────

class TestQuantNumericalIntegrity(unittest.IsolatedAsyncioTestCase):

    async def test_13_numerical_integrity_return_value(self):
        """
        cumulative_return_5d in QuantPayload must match
        the exact value calc_5d_cumulative_return() produces.
        The LLM never touches this value.
        """
        from backend.specialists.quant_calculator import calc_5d_cumulative_return

        closes = [200.0, 205.0, 210.0, 215.0, 220.0]
        ohlcv = _make_ohlcv(closes)
        expected = calc_5d_cumulative_return(ohlcv)

        ctx = _make_context(price=220.0, ohlcv=ohlcv)
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(AgentInput(symbol="TEST", market_context=ctx))

        payload = QuantPayload.model_validate(output.raw_data)
        rec_map = {m.metric_name: m for m in payload.metrics}

        self.assertEqual(rec_map["cumulative_return_5d"].value, expected.value)

    async def test_14_numerical_integrity_volatility(self):
        """Realized volatility in QuantPayload matches calc_realized_volatility_5d."""
        from backend.specialists.quant_calculator import calc_realized_volatility_5d

        closes = [100.0, 110.0, 99.0, 108.0, 115.0]
        ohlcv = _make_ohlcv(closes)
        expected = calc_realized_volatility_5d(ohlcv)

        ctx = _make_context(price=115.0, ohlcv=ohlcv)
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(AgentInput(symbol="TEST", market_context=ctx))

        payload = QuantPayload.model_validate(output.raw_data)
        rec_map = {m.metric_name: m for m in payload.metrics}
        vol_rec = rec_map["realized_volatility_5d"]

        if expected.available:
            self.assertTrue(vol_rec.available)
            self.assertAlmostEqual(vol_rec.value, expected.value, places=4)
        else:
            self.assertFalse(vol_rec.available)

    async def test_ema_spread_integrity(self):
        """EMA spread in QuantPayload matches direct calc_ema_spread_pct."""
        from backend.specialists.quant_calculator import calc_ema_spread_pct

        indicators = {"ema20": 3200.0, "ema50": 3000.0, "rsi": 65.0}
        expected = calc_ema_spread_pct(indicators)

        ctx = _make_context(
            price=3280.0,
            ohlcv=_make_ohlcv([3100.0, 3150.0, 3200.0, 3250.0, 3280.0]),
            indicators=indicators,
        )
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(AgentInput(symbol="TEST", market_context=ctx))
        payload = QuantPayload.model_validate(output.raw_data)
        rec_map = {m.metric_name: m for m in payload.metrics}

        self.assertAlmostEqual(rec_map["ema_spread_pct"].value, expected.value, places=4)


# ─── LLM failure handling ────────────────────────────────────────────────────

class TestQuantFailureHandling(unittest.IsolatedAsyncioTestCase):

    def _input(self, ctx: MarketContext) -> AgentInput:
        return AgentInput(symbol=ctx.symbol, market_context=ctx)

    async def test_15_malformed_llm_output(self):
        spec = _make_specialist(raise_error=LLMParseError("Truncated JSON"))
        output = await spec.execute(self._input(_make_context()))

        self.assertEqual(output.status, AgentState.FAILED)
        self.assertEqual(output.error.code, "LLM_PARSE_ERROR")

    async def test_16_llm_failure(self):
        spec = _make_specialist(raise_error=LLMClientError("503 Unavailable"))
        output = await spec.execute(self._input(_make_context()))

        self.assertEqual(output.status, AgentState.FAILED)
        self.assertEqual(output.error.code, "LLM_CLIENT_ERROR")

    async def test_mocked_llm_success_payload(self):
        resp = _make_llm_response(
            regime=QuantStatisticalRegime.HIGH_VOLATILITY,
            risk=QuantRiskCharacterization.ELEVATED,
            anomaly=True,
            strength=0.82,
        )
        spec = _make_specialist(resp)
        output = await spec.execute(self._input(_make_context()))

        self.assertEqual(output.status, AgentState.SUCCESS)
        payload = QuantPayload.model_validate(output.raw_data)
        self.assertEqual(payload.statistical_regime, QuantStatisticalRegime.HIGH_VOLATILITY)
        self.assertEqual(payload.risk_characterization, QuantRiskCharacterization.ELEVATED)
        self.assertTrue(payload.anomaly_detected)
        self.assertAlmostEqual(payload.statistical_strength, 0.82)


# ─── 17-19. Orchestrator and multi-specialist parallel execution ───────────────

class TestQuantOrchestratorIntegration(unittest.IsolatedAsyncioTestCase):

    async def test_17_orchestrator_integration(self):
        spec = _make_specialist(_make_llm_response())
        orchestrator = SpecialistOrchestrator(
            max_concurrency=2,
            agent_timeout_seconds=10.0,
            retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0),
        )
        result = await orchestrator.run([spec], _make_context())

        self.assertEqual(result.total_agents, 1)
        self.assertEqual(result.successful_agents, 1)
        self.assertEqual(result.records[0].agent_name, "QuantSpecialist")
        self.assertEqual(result.records[0].output.status, AgentState.SUCCESS)

    async def test_18_parallel_three_specialists(self):
        """
        TechnicalSpecialist, MomentumSpecialist, QuantSpecialist all run
        concurrently with the SAME context_id, data_timestamp, and MarketContext.
        """
        tech_resp = _TechnicalLLMResponse(
            trend=TrendDirection.BULLISH, setup=SetupType.BREAKOUT,
            technical_score=8.0, confirmation=True,
            conclusion="Bullish breakout.", invalidation_conditions=["Below EMA20"],
            risks=[], assumptions=[], confidence=0.85,
        )
        mom_resp = _MomentumLLMResponse(
            momentum_direction=MomentumDirection.BULLISH,
            momentum_strength=MomentumStrength.STRONG,
            confirmation=True,
            conclusion="Strong momentum.", invalidation_conditions=["RSI < 50"],
            risks=[], assumptions=[], confidence=0.80,
        )
        quant_resp = _make_llm_response()

        tech = TechnicalSpecialist(llm_client=MockLLMClient(fixed_response=tech_resp))
        mom = MomentumSpecialist(llm_client=MockLLMClient(fixed_response=mom_resp))
        quant = QuantSpecialist(llm_client=MockLLMClient(fixed_response=quant_resp))

        orchestrator = SpecialistOrchestrator(
            max_concurrency=5,
            agent_timeout_seconds=10.0,
            retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0),
        )
        ctx = _make_context(context_id="ctx-three-way-123")
        result = await orchestrator.run([tech, mom, quant], ctx)

        self.assertEqual(result.total_agents, 3)
        self.assertEqual(result.successful_agents, 3)
        self.assertEqual(result.failed_agents, 0)
        self.assertEqual(result.context_id, "ctx-three-way-123")

        for record in result.records:
            self.assertEqual(record.context_id, "ctx-three-way-123")
            self.assertEqual(record.status, AgentState.SUCCESS)

        names = {r.agent_name for r in result.records}
        self.assertEqual(names, {"TechnicalSpecialist", "MomentumSpecialist", "QuantSpecialist"})

    async def test_19_context_id_propagation(self):
        """context_id flows through orchestrator to execution record."""
        spec = _make_specialist(_make_llm_response())
        orchestrator = SpecialistOrchestrator(
            max_concurrency=1, agent_timeout_seconds=5.0,
            retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0),
        )
        ctx = _make_context(context_id="ctx-quant-trace-99")
        result = await orchestrator.run([spec], ctx)

        self.assertEqual(result.context_id, "ctx-quant-trace-99")
        self.assertEqual(result.records[0].context_id, "ctx-quant-trace-99")

    async def test_timeout_handled_gracefully(self):
        """Timeout produces TIMEOUT record, not an exception."""
        class SlowLLM(MockLLMClient):
            async def generate_structured(self, *a, **kw):
                import asyncio
                await asyncio.sleep(10.0)

        spec = QuantSpecialist(llm_client=SlowLLM())
        orchestrator = SpecialistOrchestrator(
            max_concurrency=1,
            agent_timeout_seconds=0.05,
            retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0),
        )
        result = await orchestrator.run([spec], _make_context())
        self.assertEqual(result.timed_out_agents, 1)
        self.assertEqual(result.records[0].status, AgentState.TIMEOUT)


# ─── 20. Existing specialists remain functional ───────────────────────────────

class TestExistingSpecialistsUnchanged(unittest.IsolatedAsyncioTestCase):

    async def test_20_technical_specialist_still_works(self):
        """TechnicalSpecialist remains fully functional after QuantSpecialist introduction."""
        tech_resp = _TechnicalLLMResponse(
            trend=TrendDirection.NEUTRAL, setup=SetupType.CONSOLIDATION,
            technical_score=5.0, confirmation=False,
            conclusion="No clear setup.", invalidation_conditions=["Price breaks above EMA20"],
            risks=[], assumptions=[], confidence=0.6,
        )
        tech = TechnicalSpecialist(llm_client=MockLLMClient(fixed_response=tech_resp))
        ctx = _make_context()
        output = await tech.execute(AgentInput(symbol="TCS.NS", market_context=ctx))
        self.assertEqual(output.status, AgentState.SUCCESS)
        self.assertEqual(output.agent_name, "TechnicalSpecialist")

    async def test_momentum_specialist_still_works(self):
        mom_resp = _MomentumLLMResponse(
            momentum_direction=MomentumDirection.NEUTRAL,
            momentum_strength=MomentumStrength.WEAK,
            confirmation=False,
            conclusion="Weak directionless momentum.",
            invalidation_conditions=["RSI > 60"],
            risks=[], assumptions=[], confidence=0.5,
        )
        mom = MomentumSpecialist(llm_client=MockLLMClient(fixed_response=mom_resp))
        ctx = _make_context()
        output = await mom.execute(AgentInput(symbol="TCS.NS", market_context=ctx))
        self.assertEqual(output.status, AgentState.SUCCESS)
        self.assertEqual(output.agent_name, "MomentumSpecialist")

    @patch("backend.agents.technical_agent.run_technical_agent", new_callable=AsyncMock)
    async def test_legacy_technical_agent_still_works(self, mock_tech):
        """Legacy TechnicalAgentAdapter is unaffected."""
        from backend.adapters.legacy_agents import TechnicalAgentAdapter

        mock_tech.return_value = MagicMock(
            technical_score=7.0, trend="BULLISH", setup="BREAKOUT", confirmation=True,
            model_dump=lambda: {"technical_score": 7.0, "trend": "BULLISH", "setup": "BREAKOUT", "confirmation": True},
        )
        adapter = TechnicalAgentAdapter()
        output = await adapter.execute(AgentInput(symbol="TCS.NS", market_context=_make_context()))
        self.assertEqual(output.status, AgentState.SUCCESS)


if __name__ == "__main__":
    unittest.main()
