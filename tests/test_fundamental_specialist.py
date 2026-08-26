"""
Tests for Phase 3.5 — FundamentalSpecialist.

All LLM calls are mocked. No Groq calls. No Yahoo Finance calls.
Uses deterministic fixtures and validates complete specialist lifecycle.
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
    BalanceSheetAssessment,
    DataQualityStatus,
    FundamentalMetricRecord,
    FundamentalPayload,
    FundamentalQuality,
    GrowthAssessment,
    MarketContext,
    MomentumDirection,
    MomentumStrength,
    ProfitabilityAssessment,
    QuantRiskCharacterization,
    QuantStatisticalRegime,
    SetupType,
    TrendDirection,
    _FundamentalLLMResponse,
    _MomentumLLMResponse,
    _QuantLLMResponse,
    _TechnicalLLMResponse,
)
from backend.infrastructure.llm import (
    LLMClientError,
    LLMParseError,
    MockLLMClient,
)
from backend.specialists.fundamental_specialist import FundamentalSpecialist
from backend.specialists.momentum_specialist import MomentumSpecialist
from backend.specialists.quant_specialist import QuantSpecialist
from backend.specialists.technical_specialist import TechnicalSpecialist


# ─── Fixtures & Helpers ───────────────────────────────────────────────────────

def _make_fundamental_fixture() -> dict:
    """Standard verified fundamental financial statement data."""
    return {
        "period": "FY2023",
        "report_date": "2024-01-15",
        "revenue": 10000.0,
        "prior_revenue": 8000.0,
        "gross_profit": 4000.0,
        "operating_profit": 2500.0,
        "net_income": 1800.0,
        "eps": 18.0,
        "prior_eps": 15.0,
        "total_debt": 1500.0,
        "total_equity": 6000.0,
        "current_assets": 4500.0,
        "current_liabilities": 1500.0,
        "operating_cash_flow": 2200.0,
        "capex": 600.0,
        "cash": 1800.0,
    }


def _make_context(
    context_id: str = "ctx-fund-001",
    symbol: str = "TCS.NS",
    price: float = 360.0,
    fundamental_data: dict | None = None,
) -> MarketContext:
    return MarketContext(
        context_id=context_id,
        symbol=symbol,
        provider="test",
        data_timestamp=datetime(2024, 2, 1, tzinfo=timezone.utc),
        current_price=price,
        ohlcv_historical=[],
        technical_indicators={"ema20": 350.0, "ema50": 340.0, "rsi": 60.0},
        fundamental_data=fundamental_data if fundamental_data is not None else _make_fundamental_fixture(),
        quality_status=DataQualityStatus.OK,
    )


def _make_llm_response(
    quality: FundamentalQuality = FundamentalQuality.STRONG,
    growth: GrowthAssessment = GrowthAssessment.HIGH_GROWTH,
    profitability: ProfitabilityAssessment = ProfitabilityAssessment.HIGHLY_PROFITABLE,
    balance_sheet: BalanceSheetAssessment = BalanceSheetAssessment.HEALTHY,
    strength: float = 0.88,
    confidence: float = 0.85,
) -> _FundamentalLLMResponse:
    return _FundamentalLLMResponse(
        fundamental_quality=quality,
        growth_assessment=growth,
        profitability_assessment=profitability,
        balance_sheet_assessment=balance_sheet,
        financial_strength=strength,
        conclusion="Robust fundamentals driven by 25% YoY revenue growth and pristine balance sheet.",
        invalidation_conditions=["Operating margin falls below 15%", "Debt-to-equity exceeds 1.0"],
        risks=["Input cost inflation could compress gross margins"],
        assumptions=["Demand environment remains stable over next 4 quarters"],
        confidence=confidence,
    )


def _make_specialist(fixed_response=None, raise_error=None) -> FundamentalSpecialist:
    mock_llm = MockLLMClient(fixed_response=fixed_response, raise_error=raise_error)
    return FundamentalSpecialist(llm_client=mock_llm)


# ─── 1. Creation and Registry ─────────────────────────────────────────────────

class TestFundamentalSpecialistCreation(unittest.TestCase):
    def test_1_creation(self):
        spec = _make_specialist(_make_llm_response())
        self.assertEqual(spec.name, "FundamentalSpecialist")
        self.assertEqual(spec.version, "1.0")

    def test_2_registry_registration(self):
        """Can be registered with AgentRegistry without collision with other specialists."""
        registry = AgentRegistry()
        registry.register(_make_specialist(_make_llm_response()))
        registry.register(TechnicalSpecialist(llm_client=MockLLMClient()))
        registry.register(MomentumSpecialist(llm_client=MockLLMClient()))
        registry.register(QuantSpecialist(llm_client=MockLLMClient()))

        self.assertIn("FundamentalSpecialist", registry)
        self.assertIn("TechnicalSpecialist", registry)
        self.assertIn("MomentumSpecialist", registry)
        self.assertIn("QuantSpecialist", registry)
        self.assertEqual(len(registry), 4)


# ─── 2. Execution and Degraded Handling ───────────────────────────────────────

class TestFundamentalSpecialistExecution(unittest.IsolatedAsyncioTestCase):

    def _input(self, ctx: MarketContext) -> AgentInput:
        return AgentInput(symbol=ctx.symbol, market_context=ctx)

    async def test_3_valid_execution(self):
        """Valid fundamental data produces SUCCESS AgentOutput."""
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(self._input(_make_context()))

        self.assertIsInstance(output, AgentOutput)
        self.assertEqual(output.status, AgentState.SUCCESS)
        self.assertEqual(output.agent_name, "FundamentalSpecialist")
        self.assertIsNotNone(output.raw_data)

        payload = FundamentalPayload.model_validate(output.raw_data)
        self.assertEqual(payload.fundamental_quality, FundamentalQuality.STRONG)
        self.assertEqual(payload.growth_assessment, GrowthAssessment.HIGH_GROWTH)
        self.assertEqual(payload.reporting_period, "FY2023")

    async def test_4_missing_fundamental_data_degraded(self):
        """When fundamental data is completely absent in MarketContext, returns DEGRADED."""
        ctx = _make_context(fundamental_data={})
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(self._input(ctx))

        self.assertEqual(output.status, AgentState.DEGRADED)
        self.assertIn("Fundamental data is unavailable", output.conclusion)
        self.assertIsNotNone(output.raw_data)

        payload = FundamentalPayload.model_validate(output.raw_data)
        self.assertEqual(payload.fundamental_quality, FundamentalQuality.INDETERMINATE)
        self.assertEqual(payload.data_freshness_status, "UNAVAILABLE")

        # Metrics are populated with available=False and explicit reasons
        self.assertGreater(len(payload.metrics), 5)
        for m in payload.metrics:
            self.assertFalse(m.available)
            self.assertTrue(m.unavailable_reason)

    async def test_5_invalid_price(self):
        """Negative price produces INVALID_INPUT failure."""
        ctx = _make_context(price=-10.0)
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(self._input(ctx))

        self.assertEqual(output.status, AgentState.FAILED)
        self.assertEqual(output.error.code, "INVALID_INPUT")


# ─── 3. Numerical Integrity & Provenance ──────────────────────────────────────

class TestFundamentalNumericalIntegrity(unittest.IsolatedAsyncioTestCase):

    async def test_6_numerical_integrity_margins(self):
        """
        Gross, operating, and net margins in output payload match Python calculations exactly.
        The LLM never calculates or modifies these numbers.
        """
        data = _make_fundamental_fixture()
        ctx = _make_context(fundamental_data=data)
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(AgentInput(symbol="TCS.NS", market_context=ctx))

        payload = FundamentalPayload.model_validate(output.raw_data)
        rec_map = {m.metric_name: m for m in payload.metrics}

        # gross_profit (4000) / revenue (10000) = 40.0%
        self.assertEqual(rec_map["gross_margin"].value, 40.0)
        # operating_profit (2500) / revenue (10000) = 25.0%
        self.assertEqual(rec_map["operating_margin"].value, 25.0)
        # net_income (1800) / revenue (10000) = 18.0%
        self.assertEqual(rec_map["net_margin"].value, 18.0)

    async def test_7_provenance_fields_present(self):
        """Every FundamentalMetricRecord has required provenance fields populated."""
        ctx = _make_context()
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(AgentInput(symbol="TCS.NS", market_context=ctx))
        payload = FundamentalPayload.model_validate(output.raw_data)

        for rec in payload.metrics:
            self.assertTrue(rec.metric_name)
            self.assertTrue(rec.unit)
            self.assertTrue(rec.period)
            self.assertTrue(rec.source)
            self.assertTrue(rec.calculation_method)
            self.assertIsNotNone(rec.data_timestamp)
            if not rec.available:
                self.assertTrue(rec.unavailable_reason)

    async def test_8_reporting_period_preserved(self):
        """Reporting period and filing date are preserved in evidence and payload."""
        data = _make_fundamental_fixture()
        data["period"] = "Q3-2024"
        data["report_date"] = "2024-10-30"

        ctx = _make_context(fundamental_data=data)
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(AgentInput(symbol="TCS.NS", market_context=ctx))
        payload = FundamentalPayload.model_validate(output.raw_data)

        self.assertEqual(payload.reporting_period, "Q3-2024")
        rec_map = {m.metric_name: m for m in payload.metrics}
        self.assertEqual(rec_map["gross_margin"].period, "Q3-2024")
        self.assertEqual(rec_map["gross_margin"].report_date, "2024-10-30")


# ─── 4. Failure and Stale Data Handling ───────────────────────────────────────

class TestFundamentalFailureHandling(unittest.IsolatedAsyncioTestCase):

    def _input(self, ctx: MarketContext) -> AgentInput:
        return AgentInput(symbol=ctx.symbol, market_context=ctx)

    async def test_9_malformed_llm_response(self):
        spec = _make_specialist(raise_error=LLMParseError("Malformed JSON"))
        output = await spec.execute(self._input(_make_context()))

        self.assertEqual(output.status, AgentState.FAILED)
        self.assertEqual(output.error.code, "LLM_PARSE_ERROR")

    async def test_10_llm_client_error(self):
        spec = _make_specialist(raise_error=LLMClientError("500 Server Error"))
        output = await spec.execute(self._input(_make_context()))

        self.assertEqual(output.status, AgentState.FAILED)
        self.assertEqual(output.error.code, "LLM_CLIENT_ERROR")

    async def test_11_stale_data_flag(self):
        """Filing date > 180 days old marks data_freshness_status as STALE."""
        data = _make_fundamental_fixture()
        data["report_date"] = "2022-01-01"  # Old report date

        ctx = _make_context(
            fundamental_data=data,
        )
        spec = _make_specialist(_make_llm_response())
        output = await spec.execute(self._input(ctx))

        self.assertEqual(output.status, AgentState.SUCCESS)
        payload = FundamentalPayload.model_validate(output.raw_data)
        self.assertEqual(payload.data_freshness_status, "STALE")


# ─── 5. Orchestrator & Parallel Execution ─────────────────────────────────────

class TestFundamentalOrchestratorIntegration(unittest.IsolatedAsyncioTestCase):

    async def test_12_single_orchestrator_run(self):
        spec = _make_specialist(_make_llm_response())
        orchestrator = SpecialistOrchestrator(
            max_concurrency=2,
            agent_timeout_seconds=5.0,
            retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0),
        )
        result = await orchestrator.run([spec], _make_context(context_id="ctx-fund-orch-1"))

        self.assertEqual(result.total_agents, 1)
        self.assertEqual(result.successful_agents, 1)
        self.assertEqual(result.context_id, "ctx-fund-orch-1")
        self.assertEqual(result.records[0].agent_name, "FundamentalSpecialist")
        self.assertEqual(result.records[0].status, AgentState.SUCCESS)

    async def test_13_parallel_four_specialists(self):
        """
        TechnicalSpecialist, MomentumSpecialist, QuantSpecialist, and FundamentalSpecialist
        all execute concurrently through SpecialistOrchestrator sharing ONE MarketContext.
        """
        tech_resp = _TechnicalLLMResponse(
            trend=TrendDirection.BULLISH, setup=SetupType.BREAKOUT,
            technical_score=8.5, confirmation=True,
            conclusion="Bullish breakout setup.", invalidation_conditions=["Break below EMA20"],
            risks=[], assumptions=[], confidence=0.85,
        )
        mom_resp = _MomentumLLMResponse(
            momentum_direction=MomentumDirection.BULLISH,
            momentum_strength=MomentumStrength.STRONG,
            confirmation=True,
            conclusion="Strong momentum continuation.", invalidation_conditions=["RSI < 50"],
            risks=[], assumptions=[], confidence=0.80,
        )
        quant_resp = _QuantLLMResponse(
            statistical_regime=QuantStatisticalRegime.NORMAL_VOLATILITY,
            risk_characterization=QuantRiskCharacterization.MODERATE,
            anomaly_detected=False,
            statistical_strength=0.70,
            conclusion="Normal volatility regime.",
            invalidation_conditions=["Volatility surge"],
            risks=[], assumptions=[], confidence=0.75,
        )
        fund_resp = _make_llm_response()

        tech = TechnicalSpecialist(llm_client=MockLLMClient(fixed_response=tech_resp))
        mom = MomentumSpecialist(llm_client=MockLLMClient(fixed_response=mom_resp))
        quant = QuantSpecialist(llm_client=MockLLMClient(fixed_response=quant_resp))
        fund = FundamentalSpecialist(llm_client=MockLLMClient(fixed_response=fund_resp))

        orchestrator = SpecialistOrchestrator(
            max_concurrency=5,
            agent_timeout_seconds=10.0,
            retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0),
        )

        ctx = _make_context(
            context_id="ctx-quad-run-444",
            fundamental_data=_make_fundamental_fixture(),
        )

        result = await orchestrator.run([tech, mom, quant, fund], ctx)

        self.assertEqual(result.total_agents, 4)
        self.assertEqual(result.successful_agents, 4)
        self.assertEqual(result.failed_agents, 0)
        self.assertEqual(result.context_id, "ctx-quad-run-444")

        names = {r.agent_name for r in result.records}
        self.assertEqual(
            names,
            {"TechnicalSpecialist", "MomentumSpecialist", "QuantSpecialist", "FundamentalSpecialist"}
        )

        for record in result.records:
            self.assertEqual(record.context_id, "ctx-quad-run-444")
            self.assertEqual(record.status, AgentState.SUCCESS)

    async def test_14_four_specialists_degraded_when_fundamental_empty(self):
        """
        When MarketContext has no fundamental_data:
        Tech, Mom, Quant succeed; Fundamental is DEGRADED; total run completes gracefully.
        """
        tech_resp = _TechnicalLLMResponse(
            trend=TrendDirection.NEUTRAL, setup=SetupType.NONE,
            technical_score=5.0, confirmation=False,
            conclusion="Neutral.", invalidation_conditions=[],
            risks=[], assumptions=[], confidence=0.5,
        )
        mom_resp = _MomentumLLMResponse(
            momentum_direction=MomentumDirection.NEUTRAL,
            momentum_strength=MomentumStrength.WEAK,
            confirmation=False,
            conclusion="Neutral.", invalidation_conditions=[],
            risks=[], assumptions=[], confidence=0.5,
        )
        quant_resp = _QuantLLMResponse(
            statistical_regime=QuantStatisticalRegime.NORMAL_VOLATILITY,
            risk_characterization=QuantRiskCharacterization.MODERATE,
            anomaly_detected=False,
            statistical_strength=0.6,
            conclusion="Normal.", invalidation_conditions=[],
            risks=[], assumptions=[], confidence=0.6,
        )

        tech = TechnicalSpecialist(llm_client=MockLLMClient(fixed_response=tech_resp))
        mom = MomentumSpecialist(llm_client=MockLLMClient(fixed_response=mom_resp))
        quant = QuantSpecialist(llm_client=MockLLMClient(fixed_response=quant_resp))
        fund = FundamentalSpecialist(llm_client=MockLLMClient())

        orchestrator = SpecialistOrchestrator(
            max_concurrency=4,
            agent_timeout_seconds=5.0,
            retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0),
        )

        ctx = _make_context(
            context_id="ctx-quad-empty-fund",
            fundamental_data={},  # Empty fundamental data
        )

        result = await orchestrator.run([tech, mom, quant, fund], ctx)

        self.assertEqual(result.total_agents, 4)
        self.assertEqual(result.successful_agents, 3)
        self.assertEqual(result.degraded_agents, 1)
        self.assertEqual(result.failed_agents, 0)


# ─── 6. Backward Compatibility ───────────────────────────────────────────────

class TestFundamentalCompatibility(unittest.IsolatedAsyncioTestCase):

    @patch("backend.agents.technical_agent.run_technical_agent", new_callable=AsyncMock)
    async def test_15_legacy_technical_agent_still_works(self, mock_tech):
        from backend.adapters.legacy_agents import TechnicalAgentAdapter

        mock_tech.return_value = MagicMock(
            technical_score=8.0, trend="BULLISH", setup="BREAKOUT", confirmation=True,
            model_dump=lambda: {"technical_score": 8.0, "trend": "BULLISH", "setup": "BREAKOUT", "confirmation": True},
        )
        adapter = TechnicalAgentAdapter()
        output = await adapter.execute(AgentInput(symbol="TCS.NS", market_context=_make_context()))
        self.assertEqual(output.status, AgentState.SUCCESS)


if __name__ == "__main__":
    unittest.main()
