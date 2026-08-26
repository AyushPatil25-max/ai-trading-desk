"""
Tests for Phase 3.7 — SectorSpecialist.

All LLM calls are mocked. No Groq calls. No Yahoo Finance calls.
Tests validate the complete specialist lifecycle including:
- Creation and registry registration
- Valid execution -> SUCCESS + SectorPayload
- DEGRADED when sector_data is empty
- Error paths: LLM parse error, LLM client error, invalid price
- Numerical integrity (values from calculator not LLM)
- Provenance (context_id in records)
- 6-way parallel orchestration
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
    BalanceSheetAssessment,
    CyclicalityCategory,
    DataQualityStatus,
    FundamentalQuality,
    GrowthAssessment,
    MarketContext,
    MomentumDirection,
    MomentumStrength,
    ProfitabilityAssessment,
    QuantRiskCharacterization,
    QuantStatisticalRegime,
    RelativeStrengthRank,
    SectorAttractiveness,
    SectorPayload,
    SectorRegime,
    SetupType,
    TrendDirection,
    ValuationPremiumDiscount,
    ValuationStatus,
    _FundamentalLLMResponse,
    _MomentumLLMResponse,
    _QuantLLMResponse,
    _SectorLLMResponse,
    _TechnicalLLMResponse,
    _ValuationLLMResponse,
)
from backend.infrastructure.llm import (
    LLMClientError,
    LLMParseError,
    MockLLMClient,
)
from backend.specialists.fundamental_specialist import FundamentalSpecialist
from backend.specialists.momentum_specialist import MomentumSpecialist
from backend.specialists.quant_specialist import QuantSpecialist
from backend.specialists.sector_specialist import SectorSpecialist
from backend.specialists.technical_specialist import TechnicalSpecialist
from backend.specialists.valuation_specialist import ValuationSpecialist


# ─── Fixtures ────────────────────────────────────────────────────────────────

def _make_sector_data() -> dict:
    return {
        "sector": "Information Technology",
        "industry": "Software - Infrastructure",
        "sector_symbol": "^CNXIT",
        "benchmark_symbol": "^NSEI",
        "sector_return_pct": 6.0,
        "benchmark_return_pct": 2.5,
    }


def _make_ohlcv() -> list:
    base = datetime(2024, 3, 1, tzinfo=timezone.utc)
    prices = [100.0, 103.0, 106.0, 108.0, 110.0]
    rows = []
    for i, p in enumerate(prices):
        rows.append({
            "date": (base.replace(day=i + 1)).isoformat(),
            "open": p - 1,
            "high": p + 2,
            "low": p - 2,
            "close": p,
            "volume": 1_000_000 + i * 10_000,
        })
    return rows  # first=100.0, last=110.0 -> +10.0% company return


def _make_context(
    context_id: str = "ctx-sec-001",
    symbol: str = "INFY.NS",
    price: float = 110.0,
    sector_data: dict | None = None,
) -> MarketContext:
    return MarketContext(
        context_id=context_id,
        symbol=symbol,
        provider="test",
        data_timestamp=datetime(2024, 3, 15, tzinfo=timezone.utc),
        current_price=price,
        ohlcv_historical=_make_ohlcv(),
        technical_indicators={"ema20": 105.0, "ema50": 102.0, "rsi": 62.0},
        fundamental_data={"eps": 15.0},
        sector_data=sector_data if sector_data is not None else _make_sector_data(),
        quality_status=DataQualityStatus.OK,
    )


def _make_sector_llm_response(
    regime: SectorRegime = SectorRegime.STRONG_OUTPERFORMING,
    attractiveness: SectorAttractiveness = SectorAttractiveness.HIGHLY_ATTRACTIVE,
    cyclicality: CyclicalityCategory = CyclicalityCategory.GROWTH,
    rank: RelativeStrengthRank = RelativeStrengthRank.LEADER,
    score: float = 0.88,
    confidence: float = 0.85,
) -> _SectorLLMResponse:
    return _SectorLLMResponse(
        sector_regime=regime,
        sector_attractiveness=attractiveness,
        cyclicality=cyclicality,
        relative_strength_rank=rank,
        sector_score=score,
        conclusion="IT sector is in a strong secular growth regime; company leads peers by 400 bps.",
        tailwinds=["Enterprise digital transformation", "Cloud migration spending growth"],
        headwinds=["Foreign exchange volatility", "Wage inflation in tier-1 talent"],
        invalidation_conditions=["Sector relative performance turns negative vs benchmark"],
        risks=["Macro slowdown in North American enterprise budgets"],
        assumptions=["Cloud budget allocation remains at or above 15% YoY growth"],
        confidence=confidence,
    )


def _make_specialist(fixed_response=None, raise_error=None) -> SectorSpecialist:
    mock_llm = MockLLMClient(fixed_response=fixed_response, raise_error=raise_error)
    return SectorSpecialist(llm_client=mock_llm)


# ─── 1. Creation and Registry ─────────────────────────────────────────────────

class TestSectorSpecialistCreation(unittest.TestCase):

    def test_1_creation(self):
        """SectorSpecialist can be instantiated with a MockLLMClient."""
        specialist = _make_specialist(fixed_response=_make_sector_llm_response())
        self.assertIsInstance(specialist, SectorSpecialist)
        self.assertEqual(specialist.name, "SectorSpecialist")
        self.assertEqual(specialist.version, "1.0")

    def test_2_registry_registration(self):
        """SectorSpecialist registers without collision in AgentRegistry."""
        registry = AgentRegistry()
        specialist = _make_specialist(fixed_response=_make_sector_llm_response())
        registry.register(specialist)
        self.assertIn("SectorSpecialist", registry)
        self.assertIs(registry.get("SectorSpecialist"), specialist)

    def test_3_duplicate_registration_raises(self):
        """Registering two SectorSpecialist instances raises AgentRegistrationError."""
        registry = AgentRegistry()
        s1 = _make_specialist(fixed_response=_make_sector_llm_response())
        s2 = _make_specialist(fixed_response=_make_sector_llm_response())
        registry.register(s1)
        with self.assertRaises(AgentRegistrationError):
            registry.register(s2)

    def test_4_distinct_name_from_other_specialists(self):
        """SectorSpecialist name does not collide with other specialist names."""
        ss = SectorSpecialist(llm_client=MockLLMClient())
        other_names = {
            "TechnicalSpecialist",
            "MomentumSpecialist",
            "QuantSpecialist",
            "FundamentalSpecialist",
            "ValuationSpecialist",
        }
        self.assertNotIn(ss.name, other_names)


# ─── 2. Successful Execution ──────────────────────────────────────────────────

class TestSectorSpecialistExecution(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.llm_response = _make_sector_llm_response()
        self.specialist = _make_specialist(fixed_response=self.llm_response)
        self.ctx = _make_context()
        self.input_data = AgentInput(symbol="INFY.NS", market_context=self.ctx)

    async def test_5_valid_execution_returns_success(self):
        """Valid MarketContext with sector_data produces AgentOutput SUCCESS."""
        output = await self.specialist.execute(self.input_data)
        self.assertEqual(output.status, AgentState.SUCCESS)
        self.assertEqual(output.agent_name, "SectorSpecialist")

    async def test_6_output_schema_completeness(self):
        """AgentOutput has all required fields populated."""
        output = await self.specialist.execute(self.input_data)
        self.assertIsNotNone(output.raw_data)
        self.assertGreater(output.confidence, 0.0)
        self.assertIsNotNone(output.conclusion)
        self.assertEqual(output.data_timestamp, self.ctx.data_timestamp)

    async def test_7_payload_type_and_fields(self):
        """raw_data can be parsed as SectorPayload with all required fields."""
        output = await self.specialist.execute(self.input_data)
        payload = SectorPayload(**output.raw_data)
        self.assertEqual(payload.sector, "Information Technology")
        self.assertEqual(payload.industry, "Software - Infrastructure")
        self.assertIsInstance(payload.sector_regime, SectorRegime)
        self.assertIsInstance(payload.sector_attractiveness, SectorAttractiveness)
        self.assertIsInstance(payload.cyclicality, CyclicalityCategory)
        self.assertIsInstance(payload.relative_strength_rank, RelativeStrengthRank)
        self.assertAlmostEqual(payload.sector_score, 0.88, places=2)
        self.assertGreaterEqual(len(payload.evidence), 1)

    async def test_8_numerical_integrity_spreads(self):
        """
        NUMERICAL INTEGRITY:
        company_return = +10.0%
        sector_return = +6.0%
        relative_to_sector = +4.0%
        The LLM must not have calculated or altered these numbers.
        """
        output = await self.specialist.execute(self.input_data)
        payload = SectorPayload(**output.raw_data)

        # Check relative_performance dict
        self.assertIn("relative_to_sector", payload.relative_performance)
        self.assertAlmostEqual(payload.relative_performance["relative_to_sector"], 4.0, places=3)
        self.assertAlmostEqual(payload.relative_performance["relative_to_benchmark"], 7.5, places=3)

        # Check evidence records
        rec = next(r for r in payload.evidence if r.metric_name == "relative_to_sector")
        self.assertTrue(rec.available)
        self.assertAlmostEqual(rec.value, 4.0, places=3)

    async def test_9_context_id_in_evidence_records(self):
        """context_id from MarketContext must appear in every evidence record."""
        output = await self.specialist.execute(self.input_data)
        payload = SectorPayload(**output.raw_data)
        for record in payload.evidence:
            self.assertEqual(record.context_id, self.ctx.context_id)

    async def test_10_llm_enriched_fields_present(self):
        """LLM-supplied qualitative fields (tailwinds, headwinds, risks) are propagated."""
        output = await self.specialist.execute(self.input_data)
        payload = SectorPayload(**output.raw_data)
        self.assertGreater(len(payload.tailwinds), 0)
        self.assertGreater(len(payload.headwinds), 0)
        self.assertGreater(len(output.risks), 0)
        self.assertGreater(len(output.assumptions), 0)
        self.assertGreater(len(output.invalidation_conditions), 0)


# ─── 3. DEGRADED State ───────────────────────────────────────────────────────

class TestSectorSpecialistDegraded(unittest.IsolatedAsyncioTestCase):

    async def test_11_degraded_when_sector_data_empty(self):
        """Empty sector_data and unknown sector -> DEGRADED, not FAILED."""
        specialist = _make_specialist()
        ctx = _make_context(sector_data={})
        input_data = AgentInput(symbol="INFY.NS", market_context=ctx)
        output = await specialist.execute(input_data)
        self.assertEqual(output.status, AgentState.DEGRADED)

    async def test_12_degraded_payload_has_indeterminate_enums(self):
        """DEGRADED payload must have INDETERMINATE enums."""
        specialist = _make_specialist()
        ctx = _make_context(sector_data={})
        input_data = AgentInput(symbol="INFY.NS", market_context=ctx)
        output = await specialist.execute(input_data)
        payload = SectorPayload(**output.raw_data)
        self.assertEqual(payload.sector_regime, SectorRegime.INDETERMINATE)
        self.assertEqual(payload.sector_attractiveness, SectorAttractiveness.INDETERMINATE)
        self.assertEqual(payload.cyclicality, CyclicalityCategory.INDETERMINATE)
        self.assertEqual(payload.relative_strength_rank, RelativeStrengthRank.INDETERMINATE)
        self.assertEqual(payload.sector_score, 0.0)

    async def test_13_degraded_has_zero_confidence(self):
        """DEGRADED output must have confidence == 0.0."""
        specialist = _make_specialist()
        ctx = _make_context(sector_data={})
        input_data = AgentInput(symbol="INFY.NS", market_context=ctx)
        output = await specialist.execute(input_data)
        self.assertEqual(output.confidence, 0.0)

    async def test_14_degraded_does_not_crash_orchestrator(self):
        """DEGRADED specialist must not prevent orchestrator from completing."""
        specialist = _make_specialist()  # No fixed response -> DEGRADED
        ctx = _make_context(sector_data={})
        orchestrator = SpecialistOrchestrator(
            max_concurrency=1,
            agent_timeout_seconds=5.0,
            retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0),
        )
        result = await orchestrator.run([specialist], ctx)
        self.assertEqual(result.total_agents, 1)
        self.assertEqual(result.degraded_agents, 1)
        self.assertEqual(result.failed_agents, 0)


# ─── 4. Error Paths ───────────────────────────────────────────────────────────

class TestSectorSpecialistErrors(unittest.IsolatedAsyncioTestCase):

    async def test_15_llm_parse_error_returns_failed(self):
        """LLMParseError from client -> FAILED with LLM_PARSE_ERROR code."""
        specialist = _make_specialist(raise_error=LLMParseError("Bad JSON"))
        ctx = _make_context()
        input_data = AgentInput(symbol="INFY.NS", market_context=ctx)
        output = await specialist.execute(input_data)
        self.assertEqual(output.status, AgentState.FAILED)
        self.assertIsNotNone(output.error)
        self.assertEqual(output.error.code, "LLM_PARSE_ERROR")

    async def test_16_llm_client_error_returns_failed(self):
        """LLMClientError from client -> FAILED with LLM_CLIENT_ERROR code."""
        specialist = _make_specialist(raise_error=LLMClientError("503 Upstream"))
        ctx = _make_context()
        input_data = AgentInput(symbol="INFY.NS", market_context=ctx)
        output = await specialist.execute(input_data)
        self.assertEqual(output.status, AgentState.FAILED)
        self.assertEqual(output.error.code, "LLM_CLIENT_ERROR")

    async def test_17_invalid_price_returns_failed(self):
        """Non-positive current_price triggers INVALID_INPUT FAILED state."""
        specialist = _make_specialist(fixed_response=_make_sector_llm_response())
        ctx = _make_context(price=0.0)
        input_data = AgentInput(symbol="INFY.NS", market_context=ctx)
        output = await specialist.execute(input_data)
        self.assertEqual(output.status, AgentState.FAILED)
        self.assertEqual(output.error.code, "INVALID_INPUT")


# ─── 5. Orchestrator Integration (6-Way Parallel Run) ────────────────────────

class TestSectorSpecialistOrchestration(unittest.IsolatedAsyncioTestCase):

    def _make_technical_llm_response(self) -> _TechnicalLLMResponse:
        return _TechnicalLLMResponse(
            trend=TrendDirection.BULLISH,
            setup=SetupType.BREAKOUT,
            technical_score=8.0,
            confirmation=True,
            conclusion="Bullish breakout.",
            risks=["False breakout"],
            assumptions=["Volume expansion"],
            invalidation_conditions=["Close below EMA50"],
            confidence=0.8,
        )

    def _make_momentum_llm_response(self) -> _MomentumLLMResponse:
        return _MomentumLLMResponse(
            momentum_direction=MomentumDirection.BULLISH,
            momentum_strength=MomentumStrength.STRONG,
            confirmation=True,
            conclusion="Strong momentum.",
            risks=["Overbought RSI"],
            assumptions=["Trend persists"],
            invalidation_conditions=["RSI rolls over"],
            confidence=0.8,
        )

    def _make_quant_llm_response(self) -> _QuantLLMResponse:
        return _QuantLLMResponse(
            statistical_regime=QuantStatisticalRegime.TREND_CONSISTENT,
            risk_characterization=QuantRiskCharacterization.MODERATE,
            anomaly_detected=False,
            statistical_strength=0.75,
            conclusion="Positive quantitative trend.",
            risks=["Volatility expansion"],
            assumptions=["Stationary distribution"],
            invalidation_conditions=["Z-score > 2.5"],
            confidence=0.75,
        )

    def _make_fundamental_llm_response(self) -> _FundamentalLLMResponse:
        return _FundamentalLLMResponse(
            fundamental_quality=FundamentalQuality.STRONG,
            growth_assessment=GrowthAssessment.HIGH_GROWTH,
            profitability_assessment=ProfitabilityAssessment.HIGHLY_PROFITABLE,
            balance_sheet_assessment=BalanceSheetAssessment.HEALTHY,
            financial_strength=0.9,
            conclusion="High quality fundamentals.",
            invalidation_conditions=["Margin compression"],
            risks=["Cost inflation"],
            assumptions=["Stable demand"],
            confidence=0.85,
        )

    def _make_valuation_llm_response(self) -> _ValuationLLMResponse:
        return _ValuationLLMResponse(
            valuation_status=ValuationStatus.FAIRLY_VALUED,
            premium_discount_assessment=ValuationPremiumDiscount.FAIR_VALUE,
            valuation_strength=0.75,
            conclusion="Fairly valued.",
            invalidation_conditions=["P/E > 30x"],
            risks=["Multiple contraction"],
            assumptions=["Earnings growth continues"],
            confidence=0.75,
        )

    async def test_18_six_way_parallel_orchestration(self):
        """
        6 specialists (Technical, Momentum, Quant, Fundamental, Valuation, Sector)
        run concurrently through SpecialistOrchestrator against ONE shared MarketContext.
        All 6 must succeed.
        """
        ctx = MarketContext(
            context_id="ctx-6way-001",
            symbol="INFY.NS",
            provider="test",
            data_timestamp=datetime(2024, 3, 15, tzinfo=timezone.utc),
            current_price=110.0,
            ohlcv_historical=_make_ohlcv(),
            technical_indicators={"ema20": 105.0, "ema50": 102.0, "rsi": 62.0, "20_day_high": 112.0},
            fundamental_data={
                "eps": 15.0,
                "prior_eps": 12.0,
                "revenue": 5000.0,
                "shares_outstanding": 100.0,
                "total_equity": 3000.0,
                "ebitda": 1500.0,
                "operating_cash_flow": 1200.0,
                "capex": 200.0,
            },
            sector_data=_make_sector_data(),
            quality_status=DataQualityStatus.OK,
        )

        tech = TechnicalSpecialist(llm_client=MockLLMClient(fixed_response=self._make_technical_llm_response()))
        mom = MomentumSpecialist(llm_client=MockLLMClient(fixed_response=self._make_momentum_llm_response()))
        quant = QuantSpecialist(llm_client=MockLLMClient(fixed_response=self._make_quant_llm_response()))
        fund = FundamentalSpecialist(llm_client=MockLLMClient(fixed_response=self._make_fundamental_llm_response()))
        val = ValuationSpecialist(llm_client=MockLLMClient(fixed_response=self._make_valuation_llm_response()))
        sec = SectorSpecialist(llm_client=MockLLMClient(fixed_response=_make_sector_llm_response()))

        orchestrator = SpecialistOrchestrator(
            max_concurrency=6,
            agent_timeout_seconds=10.0,
            retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0),
        )

        result = await orchestrator.run([tech, mom, quant, fund, val, sec], ctx)

        self.assertEqual(result.total_agents, 6)
        self.assertEqual(result.successful_agents, 6)
        self.assertEqual(result.failed_agents, 0)
        self.assertEqual(result.degraded_agents, 0)

        names = {r.agent_name for r in result.records}
        self.assertEqual(
            names,
            {
                "TechnicalSpecialist",
                "MomentumSpecialist",
                "QuantSpecialist",
                "FundamentalSpecialist",
                "ValuationSpecialist",
                "SectorSpecialist",
            },
        )
        self.assertEqual(result.context_id, "ctx-6way-001")


if __name__ == "__main__":
    unittest.main()
