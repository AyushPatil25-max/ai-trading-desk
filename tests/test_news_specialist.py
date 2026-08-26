"""
Tests for Phase 3.9 — NewsSpecialist.

All LLM calls are mocked. No real News APIs. No network requests.
Tests validate the complete specialist lifecycle including:
- Creation and registry registration
- Valid execution -> SUCCESS + NewsPayload
- DEGRADED when news_data is empty
- Error paths: LLM parse error, LLM client error, invalid price
- Numerical/count integrity (counts from calculator, not LLM)
- Provenance (context_id in records)
- 8-way parallel orchestration (Technical + Momentum + Quant + Fundamental + Valuation + Sector + Macro + News)
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
    HistoricalWindow,
    InflationRegime,
    MacroRegime,
    MacroRisk,
    MarketContext,
    MomentumDirection,
    MomentumStrength,
    NewsImportance,
    NewsPayload,
    NewsRecency,
    NewsRegime,
    NewsSentiment,
    NewsSourceQuality,
    ProfitabilityAssessment,
    QuantRiskCharacterization,
    QuantStatisticalRegime,
    RateRegime,
    RelativeStrengthRank,
    SectorAttractiveness,
    SectorRegime,
    SetupType,
    TrendDirection,
    ValuationPremiumDiscount,
    ValuationStatus,
    _FundamentalLLMResponse,
    _MacroLLMResponse,
    _MomentumLLMResponse,
    _NewsLLMResponse,
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
from backend.specialists.macro_specialist import MacroSpecialist
from backend.specialists.momentum_specialist import MomentumSpecialist
from backend.specialists.news_specialist import NewsSpecialist
from backend.specialists.quant_specialist import QuantSpecialist
from backend.specialists.sector_specialist import SectorSpecialist
from backend.specialists.technical_specialist import TechnicalSpecialist
from backend.specialists.valuation_specialist import ValuationSpecialist


# ─── Fixtures ────────────────────────────────────────────────────────────────

def _make_news_data() -> dict:
    return {
        "articles": [
            {
                "headline": "Infosys signs $1B cloud deal with European enterprise",
                "source": "Reuters",
                "published_at": "2025-06-15T08:00:00Z",
                "summary": "Infosys secures mega deal in digital transformation.",
                "importance": "HIGH",
            },
            {
                "headline": "BREAKING: Infosys signs $1B cloud deal with European enterprise",
                "source": "Bloomberg",
                "published_at": "2025-06-15T08:15:00Z",
                "summary": "European enterprise awards $1B contract to Infosys.",
                "importance": "HIGH",
            },
            {
                "headline": "Infosys Q4 Board Meeting scheduled for April 18",
                "source": "BSE",
                "published_at": "2025-06-14T10:00:00Z",
                "summary": "Board to consider audited financial results.",
                "importance": "HIGH",
            },
            {
                "headline": "Tech sector outlook remains positive on AI adoption",
                "source": "Economic Times",
                "published_at": "2025-06-10T12:00:00Z",
                "summary": "Analysts see steady IT services spending.",
                "importance": "MEDIUM",
            },
        ]
    }


def _make_ohlcv() -> list:
    base = datetime(2025, 6, 1, tzinfo=timezone.utc)
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
    return rows


def _make_context(
    context_id: str = "ctx-news-001",
    symbol: str = "INFY.NS",
    price: float = 1600.0,
    news_data: dict | None = None,
) -> MarketContext:
    return MarketContext(
        context_id=context_id,
        symbol=symbol,
        provider="test",
        data_timestamp=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        current_price=price,
        ohlcv_historical=_make_ohlcv(),
        technical_indicators={"ema20": 1580.0, "ema50": 1550.0, "rsi": 62.0},
        fundamental_data={"eps": 15.0},
        sector_data={"sector": "Technology", "sector_return_pct": 5.0, "benchmark_return_pct": 2.0},
        macro_data={"policy_rate": 6.5, "inflation_rate": 4.8, "treasury_10y": 7.1, "treasury_2y": 7.0},
        news_data=news_data if news_data is not None else _make_news_data(),
        quality_status=DataQualityStatus.OK,
    )


def _make_news_llm_response(
    regime: NewsRegime = NewsRegime.BULLISH,
    sentiment: NewsSentiment = NewsSentiment.POSITIVE,
    confidence: float = 0.85,
) -> _NewsLLMResponse:
    return _NewsLLMResponse(
        news_regime=regime,
        overall_sentiment=sentiment,
        catalysts=["$1B mega cloud deal", "Steady enterprise spending"],
        headwinds=["Foreign exchange volatility"],
        risks=["Execution delays on large contracts"],
        assumptions=["Deal ramp-up begins within 2 quarters"],
        invalidation_conditions=["Contract cancellation or scope reduction"],
        conclusion="Strong positive news flow backed by $1B mega deal win and upcoming earnings.",
        confidence=confidence,
    )


def _make_specialist(fixed_response=None, raise_error=None) -> NewsSpecialist:
    mock_llm = MockLLMClient(fixed_response=fixed_response, raise_error=raise_error)
    return NewsSpecialist(llm_client=mock_llm)


# ─── 1. Creation and Registry ─────────────────────────────────────────────────

class TestNewsSpecialistCreation(unittest.TestCase):

    def test_1_creation(self):
        spec = _make_specialist()
        self.assertEqual(spec.name, "NewsSpecialist")
        self.assertEqual(spec.version, "1.0.0")

    def test_2_registry_registration(self):
        registry = AgentRegistry()
        spec = _make_specialist()
        registry.register(spec)
        self.assertIs(registry.get("NewsSpecialist"), spec)

    def test_3_duplicate_registration_raises(self):
        registry = AgentRegistry()
        spec1 = _make_specialist()
        spec2 = _make_specialist()
        registry.register(spec1)
        with self.assertRaises(AgentRegistrationError):
            registry.register(spec2)

    def test_4_distinct_name_from_other_specialists(self):
        names = {
            TechnicalSpecialist(MockLLMClient()).name,
            MomentumSpecialist(MockLLMClient()).name,
            QuantSpecialist(MockLLMClient()).name,
            FundamentalSpecialist(MockLLMClient()).name,
            ValuationSpecialist(MockLLMClient()).name,
            SectorSpecialist(MockLLMClient()).name,
            MacroSpecialist(MockLLMClient()).name,
            NewsSpecialist(MockLLMClient()).name,
        }
        self.assertEqual(len(names), 8)


# ─── 2. Execution and Success Paths ──────────────────────────────────────────

class TestNewsSpecialistExecution(unittest.IsolatedAsyncioTestCase):

    async def test_5_valid_execution_returns_success(self):
        spec = _make_specialist(fixed_response=_make_news_llm_response())
        ctx = _make_context()
        inp = AgentInput(symbol="INFY.NS", market_context=ctx)

        output = await spec.execute(inp)

        self.assertEqual(output.status, AgentState.SUCCESS)
        self.assertEqual(output.agent_name, "NewsSpecialist")
        self.assertEqual(output.confidence, 0.85)
        self.assertIn("$1B mega deal win", output.conclusion)

    async def test_6_output_schema_completeness(self):
        spec = _make_specialist(fixed_response=_make_news_llm_response())
        ctx = _make_context()
        inp = AgentInput(symbol="INFY.NS", market_context=ctx)

        output = await spec.execute(inp)

        self.assertIsNotNone(output.raw_data)
        payload = NewsPayload(**output.raw_data)
        self.assertEqual(payload.news_regime, NewsRegime.BULLISH)
        self.assertEqual(payload.overall_sentiment, NewsSentiment.POSITIVE)
        self.assertEqual(len(payload.catalysts), 2)
        self.assertEqual(len(payload.headwinds), 1)
        self.assertEqual(len(payload.risks), 1)

    async def test_7_numerical_and_count_integrity(self):
        """
        Deduplication and counts must be computed purely by NewsCalculator
        and preserved in the payload.
        Total articles: 4
        Unique events: 3 (2 duplicates grouped into 1)
        High importance count: 2
        Recent count: 2
        """
        spec = _make_specialist(fixed_response=_make_news_llm_response())
        ctx = _make_context()
        inp = AgentInput(symbol="INFY.NS", market_context=ctx)

        output = await spec.execute(inp)
        payload = NewsPayload(**output.raw_data)

        self.assertEqual(payload.total_articles, 4)
        self.assertEqual(payload.unique_events_count, 3)
        self.assertEqual(payload.high_importance_count, 2)
        self.assertEqual(payload.recent_count, 2)

    async def test_8_evidence_and_provenance(self):
        spec = _make_specialist(fixed_response=_make_news_llm_response())
        ctx = _make_context(context_id="ctx-provenance-news-999")
        inp = AgentInput(symbol="INFY.NS", market_context=ctx)

        output = await spec.execute(inp)
        payload = NewsPayload(**output.raw_data)

        self.assertGreater(len(output.evidence), 0)
        for article in payload.articles:
            self.assertEqual(article.context_id, "ctx-provenance-news-999")
            self.assertEqual(article.data_timestamp, ctx.data_timestamp.isoformat())


# ─── 3. Degraded Paths (Missing Data) ─────────────────────────────────────────

class TestNewsSpecialistDegraded(unittest.IsolatedAsyncioTestCase):

    async def test_9_degraded_when_news_data_empty(self):
        spec = _make_specialist(fixed_response=_make_news_llm_response())
        ctx = _make_context(news_data={})
        inp = AgentInput(symbol="INFY.NS", market_context=ctx)

        output = await spec.execute(inp)

        self.assertEqual(output.status, AgentState.DEGRADED)
        self.assertEqual(output.confidence, 0.0)
        self.assertIn("No news data", output.conclusion)
        self.assertIn("INFY.NS", output.conclusion)

        payload = NewsPayload(**output.raw_data)
        self.assertEqual(payload.news_regime, NewsRegime.INDETERMINATE)
        self.assertEqual(payload.overall_sentiment, NewsSentiment.INDETERMINATE)
        self.assertEqual(payload.total_articles, 0)

    async def test_10_degraded_when_articles_list_empty(self):
        spec = _make_specialist(fixed_response=_make_news_llm_response())
        ctx = _make_context(news_data={"articles": []})
        inp = AgentInput(symbol="INFY.NS", market_context=ctx)

        output = await spec.execute(inp)

        self.assertEqual(output.status, AgentState.DEGRADED)
        self.assertEqual(output.confidence, 0.0)


# ─── 4. Error Paths ──────────────────────────────────────────────────────────

class TestNewsSpecialistErrors(unittest.IsolatedAsyncioTestCase):

    async def test_11_llm_parse_error_returns_failed(self):
        spec = _make_specialist(raise_error=LLMParseError("Bad JSON from LLM"))
        ctx = _make_context()
        inp = AgentInput(symbol="INFY.NS", market_context=ctx)

        output = await spec.execute(inp)

        self.assertEqual(output.status, AgentState.FAILED)
        self.assertEqual(output.error.code, "LLM_PARSE_ERROR")

    async def test_12_llm_client_error_returns_failed(self):
        spec = _make_specialist(raise_error=LLMClientError("503 Upstream unavailable"))
        ctx = _make_context()
        inp = AgentInput(symbol="INFY.NS", market_context=ctx)

        output = await spec.execute(inp)

        self.assertEqual(output.status, AgentState.FAILED)
        self.assertEqual(output.error.code, "LLM_CLIENT_ERROR")

    async def test_13_invalid_price_returns_failed(self):
        spec = _make_specialist(fixed_response=_make_news_llm_response())
        ctx = _make_context(price=0.0)
        inp = AgentInput(symbol="INFY.NS", market_context=ctx)

        output = await spec.execute(inp)

        self.assertEqual(output.status, AgentState.FAILED)
        self.assertEqual(output.error.code, "INVALID_INPUT")


# ─── 5. 8-Way Parallel Orchestration ─────────────────────────────────────────

class TestNewsSpecialistOrchestration(unittest.IsolatedAsyncioTestCase):

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

    def _make_sector_llm_response(self) -> _SectorLLMResponse:
        return _SectorLLMResponse(
            sector_regime=SectorRegime.STRONG_OUTPERFORMING,
            sector_attractiveness=SectorAttractiveness.HIGHLY_ATTRACTIVE,
            cyclicality=CyclicalityCategory.GROWTH,
            relative_strength_rank=RelativeStrengthRank.LEADER,
            sector_score=0.88,
            conclusion="IT sector is in a strong secular growth regime.",
            tailwinds=["Enterprise digital transformation"],
            headwinds=["Foreign exchange volatility"],
            invalidation_conditions=["Sector relative performance turns negative"],
            risks=["Macro slowdown in enterprise budgets"],
            assumptions=["Cloud budget growth continues"],
            confidence=0.85,
        )

    def _make_macro_llm_response(self) -> _MacroLLMResponse:
        return _MacroLLMResponse(
            macro_regime=MacroRegime.EXPANSIONARY,
            macro_risk=MacroRisk.MODERATE,
            rate_regime=RateRegime.HOLDING,
            inflation_regime=InflationRegime.STABLE,
            asset_impact="Positive for equities.",
            company_sensitivity="Moderate sensitivity to rates.",
            conclusion="Constructive macro environment.",
            tailwinds=["GDP growth"],
            headwinds=["Sticky inflation"],
            invalidation_conditions=["Inflation spikes above 6%"],
            risks=["Policy rate shock"],
            assumptions=["Rate cuts begin later in year"],
            confidence=0.8,
        )

    async def test_14_eight_way_parallel_orchestration(self):
        """
        8 specialists (Technical, Momentum, Quant, Fundamental, Valuation, Sector, Macro, News)
        run concurrently through SpecialistOrchestrator against ONE shared MarketContext.
        All 8 must succeed.
        """
        ctx = _make_context()

        tech = TechnicalSpecialist(llm_client=MockLLMClient(fixed_response=self._make_technical_llm_response()))
        mom = MomentumSpecialist(llm_client=MockLLMClient(fixed_response=self._make_momentum_llm_response()))
        quant = QuantSpecialist(llm_client=MockLLMClient(fixed_response=self._make_quant_llm_response()))
        fund = FundamentalSpecialist(llm_client=MockLLMClient(fixed_response=self._make_fundamental_llm_response()))
        val = ValuationSpecialist(llm_client=MockLLMClient(fixed_response=self._make_valuation_llm_response()))
        sec = SectorSpecialist(llm_client=MockLLMClient(fixed_response=self._make_sector_llm_response()))
        macro = MacroSpecialist(llm_client=MockLLMClient(fixed_response=self._make_macro_llm_response()))
        news = NewsSpecialist(llm_client=MockLLMClient(fixed_response=_make_news_llm_response()))

        orchestrator = SpecialistOrchestrator(
            max_concurrency=8,
            agent_timeout_seconds=10.0,
            retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0),
        )

        result = await orchestrator.run([tech, mom, quant, fund, val, sec, macro, news], ctx)

        self.assertEqual(result.total_agents, 8)
        self.assertEqual(result.successful_agents, 8)
        self.assertEqual(result.failed_agents, 0)
        self.assertEqual(len(result.outputs), 8)

        agent_names = {out.agent_name for out in result.outputs}
        self.assertEqual(
            agent_names,
            {
                "TechnicalSpecialist",
                "MomentumSpecialist",
                "QuantSpecialist",
                "FundamentalSpecialist",
                "ValuationSpecialist",
                "SectorSpecialist",
                "MacroSpecialist",
                "NewsSpecialist",
            },
        )

        news_out = next(out for out in result.outputs if out.agent_name == "NewsSpecialist")
        self.assertEqual(news_out.status, AgentState.SUCCESS)
        payload = NewsPayload(**news_out.raw_data)
        self.assertEqual(payload.news_regime, NewsRegime.BULLISH)
        self.assertEqual(payload.total_articles, 4)

    async def test_15_news_degraded_does_not_block_others(self):
        """
        If NewsSpecialist is DEGRADED (no news data), the other 7 specialists
        still succeed and orchestrator run completes with successful_agents=7, degraded_agents=1.
        """
        ctx = _make_context(news_data={})

        tech = TechnicalSpecialist(llm_client=MockLLMClient(fixed_response=self._make_technical_llm_response()))
        mom = MomentumSpecialist(llm_client=MockLLMClient(fixed_response=self._make_momentum_llm_response()))
        quant = QuantSpecialist(llm_client=MockLLMClient(fixed_response=self._make_quant_llm_response()))
        fund = FundamentalSpecialist(llm_client=MockLLMClient(fixed_response=self._make_fundamental_llm_response()))
        val = ValuationSpecialist(llm_client=MockLLMClient(fixed_response=self._make_valuation_llm_response()))
        sec = SectorSpecialist(llm_client=MockLLMClient(fixed_response=self._make_sector_llm_response()))
        macro = MacroSpecialist(llm_client=MockLLMClient(fixed_response=self._make_macro_llm_response()))
        news = NewsSpecialist(llm_client=MockLLMClient(fixed_response=_make_news_llm_response()))

        orchestrator = SpecialistOrchestrator(
            max_concurrency=8,
            agent_timeout_seconds=10.0,
            retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0),
        )

        result = await orchestrator.run([tech, mom, quant, fund, val, sec, macro, news], ctx)

        self.assertEqual(result.total_agents, 8)
        self.assertEqual(result.successful_agents, 7)
        self.assertEqual(result.degraded_agents, 1)

        news_out = next(out for out in result.outputs if out.agent_name == "NewsSpecialist")
        self.assertEqual(news_out.status, AgentState.DEGRADED)


if __name__ == "__main__":
    unittest.main()
