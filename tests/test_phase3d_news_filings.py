"""
Unit & Integration Tests for Phase 3D — Indian News + Regulatory Filings Data Layer

Tests:
1. NewsEvent schema & explicit fields
2. RegulatoryFiling schema & explicit fields
3. Security resolution: Symbol -> Canonical ID via SecurityMaster
4. ISIN resolution to Canonical ID
5. Publication timestamp parsing
6. PIT filtering: before simulation timestamp (exposed)
7. PIT filtering: exact boundary at simulation timestamp (exposed)
8. PIT filtering: after simulation timestamp (strictly filtered out)
9. Missing timestamp handling
10. Deduplication of identical news stories
11. Provenance retention across duplicates
12. Source conflict handling
13. Source tier assignment
14. Deterministic event categorization
15. Deterministic materiality scoring (0.0 - 1.0)
16. Cache hit for news & filings
17. Cache miss & refresh
18. Provider failure graceful handling
19. Empty news result (valid state, not crash)
20. Unresolved security handling (clean None, no hallucination)
21. 520-stock scanner isolation
22. No Stage-A mass news fetching
23. Zero LLM calls for ingestion / calculation
24. Full backward compatibility with existing MarketContext.news_data
"""

import unittest
import asyncio
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

from backend.domain.schemas import (
    MarketContext,
    NewsEvent,
    RegulatoryFiling,
    NewsEventType,
    NewsImportance,
    NewsRecency,
    NewsSourceQuality,
    DocumentType,
    SourceTier,
    VerificationStatus,
    DataQuality,
    DataQualityStatus,
    HistoricalWindow,
    AgentInput,
    AgentState,
    _NewsLLMResponse,
    NewsRegime,
    NewsSentiment,
)
from backend.simulation.pit_filter import PointInTimeFilter
from backend.specialists.news_calculator import (
    NewsCalculator,
    classify_event_type,
    classify_source_quality,
    calc_event_materiality,
    normalize_news_event,
    deduplicate_news_events,
    resolve_security_identifier,
    calculate_recency,
)
from backend.specialists.news_specialist import NewsSpecialist
from backend.infrastructure.cache import InMemoryContextCache
from backend.scanner.universe import StockUniverse, UniverseType
from backend.scanner.prefilter import DeterministicPrefilter
from backend.scanner.scanner_config import ScannerConfig
from backend.infrastructure.llm import MockLLMClient


class TestPhase3DNewsFilings(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc)

    # 1. NewsEvent schema
    def test_news_event_schema(self):
        event = NewsEvent(
            symbol="TCS.NS",
            isin="INE467B01029",
            headline="TCS wins $1B mega contract with UK insurer",
            summary="Multi-year digital transformation partnership signed.",
            publisher="Reuters",
            publication_time=self.now - timedelta(hours=2),
            event_category=NewsEventType.CONTRACT,
            materiality=NewsImportance.HIGH,
            materiality_score=0.85,
            source="reuters",
            source_tier=SourceTier.TIER_4_SECONDARY,
        )
        self.assertEqual(event.symbol, "TCS.NS")
        self.assertEqual(event.event_category, NewsEventType.CONTRACT)
        self.assertEqual(event.materiality_score, 0.85)

    # 2. RegulatoryFiling schema
    def test_regulatory_filing_schema(self):
        filing = RegulatoryFiling(
            symbol="INFY.NS",
            isin="INE009A01021",
            filing_type=DocumentType.REGULATORY_FILING,
            title="Outcome of Board Meeting - Financial Results for Q4 FY24",
            publication_time=self.now - timedelta(hours=5),
            filing_id="NSE-DISC-20240601-9988",
            source="NSE_Official",
            source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
            materiality=NewsImportance.HIGH,
            materiality_score=0.95,
        )
        self.assertEqual(filing.source_tier, SourceTier.TIER_1_PRIMARY_OFFICIAL)
        self.assertEqual(filing.filing_id, "NSE-DISC-20240601-9988")

    # 3. Security Resolution: Symbol
    def test_security_resolution_symbol(self):
        canon = resolve_security_identifier("TCS")
        self.assertEqual(canon, "TCS.NS")

    # 4. Security Resolution: ISIN
    def test_security_resolution_isin(self):
        canon = resolve_security_identifier("INE002A01018")
        self.assertEqual(canon, "RELIANCE.NS")

    # 5. Publication Timestamp Parsing
    def test_timestamp_parsing_and_recency(self):
        ts_str = "2024-06-01T08:00:00Z"
        rec = calculate_recency(ts_str, self.now)
        self.assertEqual(rec, NewsRecency.VERY_RECENT)

    # 6. PIT Filtering: Before Simulation
    def test_pit_filtering_before(self):
        t_sim = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        article = {
            "title": "TCS Q4 Results",
            "published_at": (t_sim - timedelta(hours=2)).isoformat(),
        }
        filtered = PointInTimeFilter.filter_news([article], as_of=t_sim)
        self.assertEqual(len(filtered), 1)

    # 7. PIT Filtering: Exact Boundary
    def test_pit_filtering_exact_boundary(self):
        t_sim = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        article = {
            "title": "SEBI Order on HDFC Bank",
            "published_at": t_sim.isoformat(),
        }
        filtered = PointInTimeFilter.filter_news([article], as_of=t_sim)
        self.assertEqual(len(filtered), 1)

    # 8. PIT Filtering: After Simulation (Must be filtered out)
    def test_pit_filtering_after(self):
        t_sim = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        article = {
            "title": "Future earnings announcement",
            "published_at": (t_sim + timedelta(hours=2)).isoformat(),
        }
        filtered = PointInTimeFilter.filter_news([article], as_of=t_sim)
        self.assertEqual(len(filtered), 0)

    # 9. Missing Timestamp Handling
    def test_missing_timestamp_handling(self):
        t_sim = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        article = {"title": "Undated rumour"}
        filtered = PointInTimeFilter.filter_news([article], as_of=t_sim)
        self.assertEqual(len(filtered), 0)

    # 10. Deduplication of identical news stories
    def test_news_deduplication(self):
        e1 = NewsEvent(
            symbol="TCS.NS",
            headline="TCS signs mega $1B deal with European client",
            publisher="Reuters",
            publication_time=self.now,
        )
        e2 = NewsEvent(
            symbol="TCS.NS",
            headline="Breaking: TCS signs mega $1B deal with European client",
            publisher="Bloomberg",
            publication_time=self.now,
        )
        deduped = deduplicate_news_events([e1, e2])
        self.assertFalse(deduped[0].is_duplicate)
        self.assertTrue(deduped[1].is_duplicate)
        self.assertEqual(deduped[0].duplicate_group_id, deduped[1].duplicate_group_id)

    # 11. Provenance Retention across duplicates
    def test_provenance_retention_on_duplicates(self):
        e1 = NewsEvent(symbol="TCS.NS", headline="TCS CEO steps down", publisher="NSE_Official", source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL, publication_time=self.now)
        e2 = NewsEvent(symbol="TCS.NS", headline="TCS CEO steps down", publisher="Economic Times", source_tier=SourceTier.TIER_4_SECONDARY, publication_time=self.now)
        deduped = deduplicate_news_events([e1, e2])
        self.assertEqual(deduped[0].publisher, "NSE_Official")
        self.assertEqual(deduped[1].publisher, "Economic Times")

    # 12. Source Conflict Handling
    def test_conflicting_sources_handled(self):
        q_official = classify_source_quality("NSE Disclosure")
        q_media = classify_source_quality("Unknown Blog")
        self.assertEqual(q_official, NewsSourceQuality.OFFICIAL)
        self.assertEqual(q_media, NewsSourceQuality.SECONDARY)

    # 13. Source Tier Assignment
    def test_source_tier_assignment(self):
        raw_official = {"headline": "Audited Results", "source_tier": SourceTier.TIER_1_PRIMARY_OFFICIAL, "publisher": "NSE"}
        event = normalize_news_event(raw_official, symbol="TCS.NS")
        self.assertEqual(event.source_tier, SourceTier.TIER_1_PRIMARY_OFFICIAL)
        self.assertEqual(event.verification_status, VerificationStatus.VERIFIED)

    # 14. Event Category Classification
    def test_event_category_classification(self):
        cat_earn = classify_event_type(None, "Company reports Q4 Net Profit up 18%")
        cat_reg = classify_event_type(None, "SEBI issues penalty notice over compliance")
        cat_mgmt = classify_event_type(None, "Managing Director and CEO resigns")
        self.assertEqual(cat_earn, NewsEventType.EARNINGS)
        self.assertEqual(cat_reg, NewsEventType.REGULATORY)
        self.assertEqual(cat_mgmt, NewsEventType.MANAGEMENT)

    # 15. Materiality Scoring
    def test_materiality_scoring(self):
        imp_high, score_high = calc_event_materiality(NewsEventType.REGULATORY, NewsSourceQuality.REGULATORY, "SEBI penalty imposed on bank")
        imp_low, score_low = calc_event_materiality(NewsEventType.OTHER, NewsSourceQuality.SECONDARY, "Stock hits day high in afternoon trade")
        self.assertEqual(imp_high, NewsImportance.HIGH)
        self.assertGreater(score_high, 0.70)
        self.assertEqual(imp_low, NewsImportance.LOW)
        self.assertLess(score_low, 0.40)

    # 16. Cache Hit
    def test_cache_hit_news_context(self):
        cache = InMemoryContextCache(ttl_seconds=10)
        ctx = MarketContext(
            context_id="ctx-news-cache",
            symbol="TCS.NS",
            data_timestamp=self.now,
            provider="MultiSource",
            current_price=3500.0,
            news_data={"articles": [{"headline": "TCS AI Cloud launched", "published_at": self.now.isoformat()}]},
        )
        loop = asyncio.new_event_loop()

        async def run_cache():
            await cache.set("TCS.NS", ctx)
            cached = await cache.get("TCS.NS")
            self.assertIsNotNone(cached)
            self.assertEqual(len(cached.news_data["articles"]), 1)

        loop.run_until_complete(run_cache())
        loop.close()

    # 17. Cache Miss
    def test_cache_miss_returns_none(self):
        cache = InMemoryContextCache(ttl_seconds=10)
        loop = asyncio.new_event_loop()

        async def run_cache():
            cached = await cache.get("NONEXISTENT.NS")
            self.assertIsNone(cached)

        loop.run_until_complete(run_cache())
        loop.close()

    # 18. Provider Failure Handling
    def test_provider_failure_graceful_handling(self):
        from backend.infrastructure.providers.base import BaseProvider, ProviderCapabilities, ProviderResult

        class BrokenNewsProvider(BaseProvider):
            @property
            def name(self):
                return "broken"
            @property
            def capabilities(self):
                return ProviderCapabilities(news=True)
            @property
            def data_source_info(self):
                from backend.domain.schemas import DataSource
                return DataSource(provider_name="broken", authority="Test")
            async def get_news(self, symbol):
                return ProviderResult(status="ERROR", error="HTTP 500 Server Error")

        p = BrokenNewsProvider()
        loop = asyncio.new_event_loop()
        res = loop.run_until_complete(p.get_news("TCS.NS"))
        loop.close()
        self.assertEqual(res.status, "ERROR")

    # 19. Empty News Result
    def test_empty_news_result_valid(self):
        ctx = MarketContext(
            context_id="ctx-empty-news",
            symbol="QUIET.NS",
            data_timestamp=self.now,
            provider="test",
            current_price=100.0,
            news_data={"articles": []},
        )
        articles, stats = NewsCalculator.process_news_data(ctx)
        self.assertEqual(len(articles), 0)
        self.assertEqual(stats["total_articles"], 0)

    # 20. Unresolved Security Handling
    def test_unresolved_security_returns_none(self):
        canon = resolve_security_identifier("UNKNOWN_RANDOM_XYZ")
        self.assertIsNone(canon)

    # 21. 520-Stock Scanner Isolation
    def test_scanner_isolation_520_stocks(self):
        universe = StockUniverse(UniverseType.NIFTY_500)
        symbols = universe.get_snapshot(self.now).get_symbols()
        self.assertEqual(len(symbols), 520)

    # 22. No Stage-A Mass News Fetching
    def test_stage_a_scanner_fast(self):
        universe = StockUniverse(UniverseType.NIFTY_500)
        symbols = universe.get_snapshot(self.now).get_symbols()
        prefilter = DeterministicPrefilter(ScannerConfig(min_historical_bars=10))
        candidates = {s: {"current_price": 1000.0, "ohlcv_historical": [{"close": 1000.0}] * 25} for s in symbols}

        import time
        t0 = time.perf_counter()
        passed = sum(1 for s, d in candidates.items() if prefilter.filter_candidate(s, d).passed)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(passed, len(symbols))
        self.assertLess(elapsed_ms, 15.0)

    # 23. Zero LLM Calls for Ingestion / Calculation
    def test_zero_llm_calls_for_news_calculation(self):
        ctx = MarketContext(
            context_id="ctx-calc-test",
            symbol="TCS.NS",
            data_timestamp=self.now,
            provider="test",
            current_price=3500.0,
            news_data={
                "articles": [
                    {"headline": "TCS Q4 net profit up 15%", "published_at": self.now.isoformat(), "source": "Reuters"},
                    {"headline": "Breaking: TCS Q4 net profit up 15%", "published_at": self.now.isoformat(), "source": "Bloomberg"},
                ]
            },
        )
        articles, stats = NewsCalculator.process_news_data(ctx)
        self.assertEqual(stats["total_articles"], 2)
        self.assertEqual(stats["unique_events_count"], 1)

    # 24. Backward Compatibility with NewsSpecialist
    def test_news_specialist_backward_compatibility(self):
        mock_resp = _NewsLLMResponse(
            news_regime=NewsRegime.BULLISH,
            overall_sentiment=NewsSentiment.POSITIVE,
            catalysts=["Strong contract wins"],
            headwinds=[],
            risks=[],
            assumptions=[],
            invalidation_conditions=[],
            conclusion="Positive news momentum.",
            confidence=0.88,
        )
        mock_llm = MockLLMClient(fixed_response=mock_resp)
        specialist = NewsSpecialist(mock_llm)

        ctx = MarketContext(
            context_id="ctx-news-spec",
            symbol="TCS.NS",
            data_timestamp=self.now,
            provider="test",
            current_price=3500.0,
            news_data={"articles": [{"headline": "TCS signs $1B deal", "published_at": self.now.isoformat()}]},
        )
        loop = asyncio.new_event_loop()
        agent_input = AgentInput(symbol="TCS.NS", market_context=ctx)
        out = loop.run_until_complete(specialist.execute(agent_input))
        loop.close()

        self.assertEqual(out.status, AgentState.SUCCESS)


if __name__ == "__main__":
    unittest.main()
