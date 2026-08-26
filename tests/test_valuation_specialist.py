"""
Tests for Phase 3.6 — ValuationSpecialist.

All LLM calls are mocked. No Groq calls. No Yahoo Finance calls.
Tests validate the complete specialist lifecycle including:
- Creation and registry registration
- Valid execution → SUCCESS + ValuationPayload
- DEGRADED when fundamental_data is empty
- Error paths: LLM parse error, LLM client error, invalid price
- Numerical integrity (values from calculator not LLM)
- Provenance (context_id in records)
- 5-way parallel orchestration
"""

import asyncio
import unittest
from datetime import datetime, timezone

from backend.application.agent_registry import AgentRegistry, AgentRegistrationError
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
    QuantRiskCharacterization,
    QuantStatisticalRegime,
    SetupType,
    TrendDirection,
    ValuationPayload,
    ValuationPremiumDiscount,
    ValuationStatus,
    _FundamentalLLMResponse,
    _MomentumLLMResponse,
    _QuantLLMResponse,
    _TechnicalLLMResponse,
    _ValuationLLMResponse,
    BalanceSheetAssessment,
    FundamentalQuality,
    GrowthAssessment,
    ProfitabilityAssessment,
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
from backend.specialists.valuation_specialist import ValuationSpecialist


# ─── Fixtures ────────────────────────────────────────────────────────────────

def _make_fundamental_data() -> dict:
    """Standard fundamental financial statement fixture with full valuation data."""
    return {
        "period": "FY2023",
        "report_date": "2024-01-15",
        "eps": 18.0,
        "prior_eps": 15.0,
        "revenue": 10000.0,
        "shares_outstanding": 100.0,
        "total_equity": 6000.0,
        "total_debt": 1500.0,
        "cash": 1800.0,
        "ebitda": 3000.0,
        "operating_cash_flow": 2200.0,
        "capex": 600.0,
        "gross_profit": 4000.0,
        "operating_profit": 2500.0,
        "net_income": 1800.0,
    }


def _make_context(
    context_id: str = "ctx-val-001",
    symbol: str = "RELIANCE.NS",
    price: float = 360.0,
    fundamental_data: dict | None = None,
) -> MarketContext:
    return MarketContext(
        context_id=context_id,
        symbol=symbol,
        provider="test",
        data_timestamp=datetime(2024, 3, 15, tzinfo=timezone.utc),
        current_price=price,
        ohlcv_historical=[],
        technical_indicators={"ema20": 350.0, "ema50": 340.0, "rsi": 60.0},
        fundamental_data=fundamental_data if fundamental_data is not None else _make_fundamental_data(),
        quality_status=DataQualityStatus.OK,
    )


def _make_valuation_llm_response(
    status: ValuationStatus = ValuationStatus.FAIRLY_VALUED,
    pd: ValuationPremiumDiscount = ValuationPremiumDiscount.FAIR_VALUE,
    strength: float = 0.72,
    confidence: float = 0.75,
) -> _ValuationLLMResponse:
    return _ValuationLLMResponse(
        valuation_status=status,
        premium_discount_assessment=pd,
        valuation_strength=strength,
        conclusion="Stock appears fairly valued at 20x P/E with moderate growth trajectory.",
        invalidation_conditions=["P/E expansion above 35x without earnings acceleration"],
        risks=["Multiple compression if interest rates rise significantly"],
        assumptions=["Earnings maintain 20% YoY growth for the next 2 years"],
        confidence=confidence,
    )


def _make_specialist(fixed_response=None, raise_error=None) -> ValuationSpecialist:
    mock_llm = MockLLMClient(fixed_response=fixed_response, raise_error=raise_error)
    return ValuationSpecialist(llm_client=mock_llm)


# ─── 1. Creation and Registry ─────────────────────────────────────────────────

class TestValuationSpecialistCreation(unittest.TestCase):

    def test_1_creation(self):
        """ValuationSpecialist can be instantiated with a MockLLMClient."""
        specialist = _make_specialist(fixed_response=_make_valuation_llm_response())
        self.assertIsInstance(specialist, ValuationSpecialist)
        self.assertEqual(specialist.name, "ValuationSpecialist")
        self.assertEqual(specialist.version, "1.0")

    def test_2_registry_registration(self):
        """ValuationSpecialist registers without collision."""
        registry = AgentRegistry()
        specialist = _make_specialist(fixed_response=_make_valuation_llm_response())
        registry.register(specialist)
        self.assertIn("ValuationSpecialist", registry)
        self.assertIs(registry.get("ValuationSpecialist"), specialist)

    def test_3_duplicate_registration_raises(self):
        """Registering two ValuationSpecialist instances raises AgentRegistrationError."""
        registry = AgentRegistry()
        s1 = _make_specialist(fixed_response=_make_valuation_llm_response())
        s2 = _make_specialist(fixed_response=_make_valuation_llm_response())
        registry.register(s1)
        with self.assertRaises(AgentRegistrationError):
            registry.register(s2)

    def test_4_distinct_name_from_other_specialists(self):
        """ValuationSpecialist name does not collide with other specialist names."""
        vs = ValuationSpecialist(llm_client=MockLLMClient())
        other_names = {"TechnicalSpecialist", "MomentumSpecialist", "QuantSpecialist", "FundamentalSpecialist"}
        self.assertNotIn(vs.name, other_names)


# ─── 2. Successful Execution ──────────────────────────────────────────────────

class TestValuationSpecialistExecution(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.llm_response = _make_valuation_llm_response()
        self.specialist = _make_specialist(fixed_response=self.llm_response)
        self.ctx = _make_context()
        self.input_data = AgentInput(symbol="RELIANCE.NS", market_context=self.ctx)

    async def test_5_valid_execution_returns_success(self):
        """Valid MarketContext with fundamental_data produces AgentOutput SUCCESS."""
        output = await self.specialist.execute(self.input_data)
        self.assertEqual(output.status, AgentState.SUCCESS)
        self.assertEqual(output.agent_name, "ValuationSpecialist")

    async def test_6_output_schema_completeness(self):
        """AgentOutput has all required fields populated."""
        output = await self.specialist.execute(self.input_data)
        self.assertIsNotNone(output.raw_data)
        self.assertGreater(output.confidence, 0.0)
        self.assertIsNotNone(output.conclusion)
        self.assertEqual(output.data_timestamp, self.ctx.data_timestamp)

    async def test_7_payload_type_and_fields(self):
        """raw_data can be parsed as ValuationPayload with all required fields."""
        output = await self.specialist.execute(self.input_data)
        payload = ValuationPayload(**output.raw_data)
        self.assertIsInstance(payload.valuation_status, ValuationStatus)
        self.assertIsInstance(payload.premium_discount_assessment, ValuationPremiumDiscount)
        self.assertGreaterEqual(payload.valuation_strength, 0.0)
        self.assertLessEqual(payload.valuation_strength, 1.0)
        self.assertIsInstance(payload.methods_used, list)
        self.assertIsInstance(payload.evidence, list)

    async def test_8_evidence_contains_valuation_records(self):
        """raw_data.evidence contains ValuationMetricRecord-compatible dicts."""
        output = await self.specialist.execute(self.input_data)
        payload = ValuationPayload(**output.raw_data)
        self.assertGreater(len(payload.evidence), 0)
        for record in payload.evidence:
            rec_dict = record.model_dump()
            self.assertIn("metric_name", rec_dict)
            self.assertIn("available", rec_dict)
            self.assertIn("context_id", rec_dict)

    async def test_9_pe_ratio_matches_calculator(self):
        """
        NUMERICAL INTEGRITY: P/E in payload must equal price/eps = 360/18 = 20.0.
        The LLM must not have invented this number.
        """
        output = await self.specialist.execute(self.input_data)
        payload = ValuationPayload(**output.raw_data)
        pe_record = next(
            (r for r in payload.evidence if r.metric_name == "pe_ratio"), None
        )
        self.assertIsNotNone(pe_record, "pe_ratio record must be in evidence")
        self.assertTrue(pe_record.available)
        self.assertAlmostEqual(pe_record.value, 20.0, places=3)

    async def test_10_context_id_in_evidence_records(self):
        """context_id from MarketContext must appear in every evidence record."""
        output = await self.specialist.execute(self.input_data)
        payload = ValuationPayload(**output.raw_data)
        for record in payload.evidence:
            self.assertEqual(record.context_id, self.ctx.context_id)

    async def test_11_methods_used_is_non_empty(self):
        """methods_used must list the names of available methods."""
        output = await self.specialist.execute(self.input_data)
        payload = ValuationPayload(**output.raw_data)
        self.assertGreater(len(payload.methods_used), 0)
        self.assertIn("Price-to-Earnings (P/E)", payload.methods_used)

    async def test_12_relative_valuation_populated(self):
        """relative_valuation dict must contain at least one multiple."""
        output = await self.specialist.execute(self.input_data)
        payload = ValuationPayload(**output.raw_data)
        self.assertGreater(len(payload.relative_valuation), 0)
        self.assertIn("pe_ratio", payload.relative_valuation)

    async def test_13_llm_enriched_fields_present(self):
        """LLM-supplied qualitative fields are propagated to the output."""
        output = await self.specialist.execute(self.input_data)
        self.assertGreater(len(output.risks), 0)
        self.assertGreater(len(output.assumptions), 0)
        self.assertGreater(len(output.invalidation_conditions), 0)


# ─── 3. DEGRADED State ───────────────────────────────────────────────────────

class TestValuationSpecialistDegraded(unittest.IsolatedAsyncioTestCase):

    async def test_14_degraded_when_fundamental_data_empty(self):
        """Empty fundamental_data → DEGRADED, not FAILED."""
        specialist = _make_specialist()
        ctx = _make_context(fundamental_data={})
        input_data = AgentInput(symbol="RELIANCE.NS", market_context=ctx)
        output = await specialist.execute(input_data)
        self.assertEqual(output.status, AgentState.DEGRADED)

    async def test_15_degraded_payload_has_indeterminate_status(self):
        """DEGRADED payload must have INDETERMINATE valuation_status."""
        specialist = _make_specialist()
        ctx = _make_context(fundamental_data={})
        input_data = AgentInput(symbol="RELIANCE.NS", market_context=ctx)
        output = await specialist.execute(input_data)
        payload = ValuationPayload(**output.raw_data)
        self.assertEqual(payload.valuation_status, ValuationStatus.INDETERMINATE)
        self.assertEqual(payload.premium_discount_assessment, ValuationPremiumDiscount.INDETERMINATE)

    async def test_16_degraded_has_zero_confidence(self):
        """DEGRADED output must have confidence == 0.0."""
        specialist = _make_specialist()
        ctx = _make_context(fundamental_data={})
        input_data = AgentInput(symbol="RELIANCE.NS", market_context=ctx)
        output = await specialist.execute(input_data)
        self.assertEqual(output.confidence, 0.0)

    async def test_17_degraded_does_not_crash_orchestrator(self):
        """DEGRADED specialist must not prevent orchestrator from completing."""
        specialist = _make_specialist()  # No fixed_response → will go DEGRADED (no data)
        ctx = _make_context(fundamental_data={})
        orchestrator = SpecialistOrchestrator(
            max_concurrency=1,
            agent_timeout_seconds=5.0,
            retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0),
        )
        result = await orchestrator.run([specialist], ctx)
        self.assertEqual(result.total_agents, 1)
        self.assertEqual(result.degraded_agents, 1)
        self.assertEqual(result.failed_agents, 0)

    async def test_18_degraded_conclusion_mentions_symbol(self):
        """DEGRADED conclusion must reference the symbol for traceability."""
        specialist = _make_specialist()
        ctx = _make_context(fundamental_data={}, symbol="TATASTEEL.NS")
        input_data = AgentInput(symbol="TATASTEEL.NS", market_context=ctx)
        output = await specialist.execute(input_data)
        self.assertIn("TATASTEEL.NS", output.conclusion)


# ─── 4. Error Paths ───────────────────────────────────────────────────────────

class TestValuationSpecialistErrors(unittest.IsolatedAsyncioTestCase):

    async def test_19_llm_parse_error_returns_failed(self):
        """LLMParseError from client → FAILED with LLM_PARSE_ERROR code."""
        specialist = _make_specialist(raise_error=LLMParseError("Bad JSON"))
        ctx = _make_context()
        input_data = AgentInput(symbol="RELIANCE.NS", market_context=ctx)
        output = await specialist.execute(input_data)
        self.assertEqual(output.status, AgentState.FAILED)
        self.assertIsNotNone(output.error)
        self.assertEqual(output.error.code, "LLM_PARSE_ERROR")

    async def test_20_llm_client_error_returns_failed(self):
        """LLMClientError from client → FAILED with LLM_CLIENT_ERROR code."""
        specialist = _make_specialist(raise_error=LLMClientError("503 Upstream"))
        ctx = _make_context()
        input_data = AgentInput(symbol="RELIANCE.NS", market_context=ctx)
        output = await specialist.execute(input_data)
        self.assertEqual(output.status, AgentState.FAILED)
        self.assertEqual(output.error.code, "LLM_CLIENT_ERROR")

    async def test_21_invalid_price_returns_failed(self):
        """Non-positive current_price triggers INVALID_INPUT FAILED state."""
        specialist = _make_specialist(fixed_response=_make_valuation_llm_response())
        ctx = _make_context(price=0.0)
        input_data = AgentInput(symbol="RELIANCE.NS", market_context=ctx)
        output = await specialist.execute(input_data)
        self.assertEqual(output.status, AgentState.FAILED)
        self.assertEqual(output.error.code, "INVALID_INPUT")

    async def test_22_negative_price_returns_failed(self):
        """Negative current_price triggers INVALID_INPUT FAILED state."""
        specialist = _make_specialist(fixed_response=_make_valuation_llm_response())
        ctx = _make_context(price=-10.0)
        input_data = AgentInput(symbol="RELIANCE.NS", market_context=ctx)
        output = await specialist.execute(input_data)
        self.assertEqual(output.status, AgentState.FAILED)
        self.assertEqual(output.error.code, "INVALID_INPUT")


# ─── 5. Orchestrator Integration ─────────────────────────────────────────────

class TestValuationSpecialistOrchestration(unittest.IsolatedAsyncioTestCase):

    def _make_ohlcv(self) -> list:
        """Minimal OHLCV rows for technical and quant specialists."""
        base = datetime(2024, 3, 1, tzinfo=timezone.utc)
        rows = []
        prices = [340.0, 345.0, 350.0, 355.0, 360.0]
        for i, p in enumerate(prices):
            rows.append({
                "date": (base.replace(day=i + 1)).isoformat(),
                "open": p - 2,
                "high": p + 3,
                "low": p - 3,
                "close": p,
                "volume": 1_000_000 + i * 10_000,
            })
        return rows

    def _make_technical_llm_response(self) -> _TechnicalLLMResponse:
        """Correct field names from _TechnicalLLMResponse: trend, setup, technical_score."""
        return _TechnicalLLMResponse(
            trend=TrendDirection.BULLISH,
            setup=SetupType.BREAKOUT,
            technical_score=7.5,
            confirmation=True,
            conclusion="Bullish breakout confirmed.",
            risks=["Reversal risk"],
            assumptions=["Volume holds"],
            invalidation_conditions=["Price below EMA50"],
            confidence=0.75,
        )

    def _make_momentum_llm_response(self) -> _MomentumLLMResponse:
        """Correct field names from _MomentumLLMResponse: momentum_direction, momentum_strength."""
        return _MomentumLLMResponse(
            momentum_direction=MomentumDirection.BULLISH,
            momentum_strength=MomentumStrength.STRONG,
            confirmation=True,
            conclusion="Strong upward momentum.",
            risks=["Momentum fade"],
            assumptions=["Trend continues"],
            invalidation_conditions=["RSI below 50"],
            confidence=0.8,
        )

    def _make_quant_llm_response(self) -> _QuantLLMResponse:
        """Correct field names from _QuantLLMResponse: statistical_regime, risk_characterization."""
        return _QuantLLMResponse(
            statistical_regime=QuantStatisticalRegime.NORMAL_VOLATILITY,
            risk_characterization=QuantRiskCharacterization.MODERATE,
            anomaly_detected=False,
            statistical_strength=0.7,
            conclusion="Trending regime with moderate volatility.",
            risks=["Volatility spike"],
            assumptions=["Normal distribution holds"],
            invalidation_conditions=["Z-score exceeds 3.0"],
            confidence=0.7,
        )

    def _make_fundamental_llm_response(self) -> _FundamentalLLMResponse:
        return _FundamentalLLMResponse(
            fundamental_quality=FundamentalQuality.STRONG,
            growth_assessment=GrowthAssessment.HIGH_GROWTH,
            profitability_assessment=ProfitabilityAssessment.HIGHLY_PROFITABLE,
            balance_sheet_assessment=BalanceSheetAssessment.HEALTHY,
            financial_strength=0.88,
            conclusion="Strong fundamentals.",
            invalidation_conditions=["Margin contraction"],
            risks=["Input cost inflation"],
            assumptions=["Stable demand"],
            confidence=0.85,
        )

    async def test_23_five_way_parallel_orchestration(self):
        """
        5 specialists (Technical, Momentum, Quant, Fundamental, Valuation)
        run concurrently through SpecialistOrchestrator.
        All 5 must succeed.
        """
        ohlcv = self._make_ohlcv()
        ctx = MarketContext(
            context_id="ctx-5way-001",
            symbol="RELIANCE.NS",
            provider="test",
            data_timestamp=datetime(2024, 3, 15, tzinfo=timezone.utc),
            current_price=360.0,
            ohlcv_historical=ohlcv,
            technical_indicators={"ema20": 352.0, "ema50": 345.0, "rsi": 62.0, "20_day_high": 362.0},
            fundamental_data=_make_fundamental_data(),
            quality_status=DataQualityStatus.OK,
        )

        technical = TechnicalSpecialist(llm_client=MockLLMClient(
            fixed_response=self._make_technical_llm_response()
        ))
        momentum = MomentumSpecialist(llm_client=MockLLMClient(
            fixed_response=self._make_momentum_llm_response()
        ))
        quant = QuantSpecialist(llm_client=MockLLMClient(
            fixed_response=self._make_quant_llm_response()
        ))
        fundamental = FundamentalSpecialist(llm_client=MockLLMClient(
            fixed_response=self._make_fundamental_llm_response()
        ))
        valuation = ValuationSpecialist(llm_client=MockLLMClient(
            fixed_response=_make_valuation_llm_response()
        ))

        orchestrator = SpecialistOrchestrator(
            max_concurrency=5,
            agent_timeout_seconds=10.0,
            retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0),
        )
        result = await orchestrator.run(
            [technical, momentum, quant, fundamental, valuation],
            ctx,
        )

        self.assertEqual(result.total_agents, 5)
        self.assertEqual(result.successful_agents, 5)
        self.assertEqual(result.failed_agents, 0)
        self.assertEqual(result.degraded_agents, 0)

        names = {r.agent_name for r in result.records}
        self.assertIn("ValuationSpecialist", names)

    async def test_24_valuation_degraded_does_not_block_others(self):
        """
        If ValuationSpecialist is DEGRADED (no fundamental data),
        the other specialists still succeed. Orchestrator completes normally.
        """
        ctx = MarketContext(
            context_id="ctx-degraded-val-001",
            symbol="TATASTEEL.NS",
            provider="test",
            data_timestamp=datetime(2024, 3, 15, tzinfo=timezone.utc),
            current_price=145.0,
            ohlcv_historical=self._make_ohlcv(),
            technical_indicators={"ema20": 142.0, "ema50": 138.0, "rsi": 55.0, "20_day_high": 148.0},
            fundamental_data={},  # No fundamental data → Valuation DEGRADED
            quality_status=DataQualityStatus.OK,
        )

        technical = TechnicalSpecialist(llm_client=MockLLMClient(
            fixed_response=self._make_technical_llm_response()
        ))
        valuation = ValuationSpecialist(llm_client=MockLLMClient())  # No response needed

        orchestrator = SpecialistOrchestrator(
            max_concurrency=2,
            agent_timeout_seconds=5.0,
            retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0),
        )
        result = await orchestrator.run(
            [technical, valuation],
            ctx,
        )

        self.assertEqual(result.total_agents, 2)
        self.assertEqual(result.successful_agents, 1)
        self.assertEqual(result.degraded_agents, 1)
        self.assertEqual(result.failed_agents, 0)


if __name__ == "__main__":
    unittest.main()
