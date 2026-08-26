"""
Tests for news_calculator.py — Phase 3.9

Tests deterministic news parsing, recency classification, source credibility tiering,
event classification, deduplication, and summary counts.
"""

import unittest
from datetime import datetime, timezone

from backend.domain.schemas import (
    MarketContext,
    HistoricalWindow,
    NewsEventType,
    NewsImportance,
    NewsRecency,
    NewsSourceQuality,
)
from backend.specialists.news_calculator import (
    NewsCalculator,
    calculate_recency,
    classify_event_type,
    classify_source_quality,
    assess_importance,
    _parse_timestamp,
)


class TestNewsCalculator(unittest.TestCase):

    def setUp(self):
        self.ref_time = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        self.base_context = MarketContext(
            context_id="ctx-news-test-001",
            symbol="INFY.NS",
            data_timestamp=self.ref_time,
            provider="test-provider",
            historical_window=HistoricalWindow.RECENT,
            current_price=1600.0,
            news_data={},
        )

    def test_timestamp_parsing(self):
        # ISO with Z
        dt = _parse_timestamp("2025-06-15T10:00:00Z")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2025)
        self.assertEqual(dt.hour, 10)

        # ISO with offset
        dt = _parse_timestamp("2025-06-15T10:00:00+05:30")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.astimezone(timezone.utc).hour, 4)

        # Date only
        dt = _parse_timestamp("2025-06-14")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.day, 14)

        # Epoch seconds
        dt = _parse_timestamp(1750000000)
        self.assertIsNotNone(dt)

        # Epoch milliseconds
        dt = _parse_timestamp(1750000000000)
        self.assertIsNotNone(dt)

        # Invalid / None
        self.assertIsNone(_parse_timestamp(None))
        self.assertIsNone(_parse_timestamp(""))
        self.assertIsNone(_parse_timestamp("invalid-date-string"))

    def test_recency_classification(self):
        # 2 hours before -> VERY_RECENT
        r = calculate_recency("2025-06-15T10:00:00Z", self.ref_time)
        self.assertEqual(r, NewsRecency.VERY_RECENT)

        # 24 hours before -> VERY_RECENT
        r = calculate_recency("2025-06-14T12:00:00Z", self.ref_time)
        self.assertEqual(r, NewsRecency.VERY_RECENT)

        # 48 hours before -> RECENT
        r = calculate_recency("2025-06-13T12:00:00Z", self.ref_time)
        self.assertEqual(r, NewsRecency.RECENT)

        # 7 days before (168h) -> OLDER
        r = calculate_recency("2025-06-08T12:00:00Z", self.ref_time)
        self.assertEqual(r, NewsRecency.OLDER)

        # 60 days before -> STALE
        r = calculate_recency("2025-04-15T12:00:00Z", self.ref_time)
        self.assertEqual(r, NewsRecency.STALE)

        # Invalid / Missing
        self.assertEqual(calculate_recency(None, self.ref_time), NewsRecency.UNKNOWN)
        self.assertEqual(calculate_recency("not-a-date", self.ref_time), NewsRecency.UNKNOWN)

    def test_source_quality_classification(self):
        self.assertEqual(classify_source_quality("SEC Filing"), NewsSourceQuality.OFFICIAL)
        self.assertEqual(classify_source_quality("BSE Corporate Disclosure"), NewsSourceQuality.OFFICIAL)
        self.assertEqual(classify_source_quality("Company Press Release"), NewsSourceQuality.OFFICIAL)
        self.assertEqual(classify_source_quality("SEBI Order"), NewsSourceQuality.REGULATORY)
        self.assertEqual(classify_source_quality("Reuters"), NewsSourceQuality.REPUTABLE_MEDIA)
        self.assertEqual(classify_source_quality("Bloomberg"), NewsSourceQuality.REPUTABLE_MEDIA)
        self.assertEqual(classify_source_quality("Economic Times"), NewsSourceQuality.REPUTABLE_MEDIA)
        self.assertEqual(classify_source_quality("Seeking Alpha"), NewsSourceQuality.SECONDARY)
        self.assertEqual(classify_source_quality("Random Blog"), NewsSourceQuality.SECONDARY)
        self.assertEqual(classify_source_quality("Twitter / X"), NewsSourceQuality.SECONDARY)
        self.assertEqual(classify_source_quality("Some Local Newspaper"), NewsSourceQuality.UNKNOWN)
        self.assertEqual(classify_source_quality(None), NewsSourceQuality.UNKNOWN)

    def test_event_type_classification(self):
        # Explicit type
        self.assertEqual(classify_event_type("EARNINGS", "Infosys reports results"), NewsEventType.EARNINGS)
        self.assertEqual(classify_event_type("M_AND_A", "Infosys acquires cloud firm"), NewsEventType.M_AND_A)

        # Inferred from keywords
        self.assertEqual(classify_event_type(None, "Infosys Q4 net profit rises 12%"), NewsEventType.EARNINGS)
        self.assertEqual(classify_event_type(None, "Company raises FY26 revenue guidance"), NewsEventType.GUIDANCE)
        self.assertEqual(classify_event_type(None, "Infosys appoints new CFO"), NewsEventType.MANAGEMENT)
        self.assertEqual(classify_event_type(None, "SEBI issues notice on insider trading"), NewsEventType.REGULATORY)
        self.assertEqual(classify_event_type(None, "Court dismisses patent lawsuit against firm"), NewsEventType.LEGAL)
        self.assertEqual(classify_event_type(None, "Infosys bags $500M mega contract with European bank"), NewsEventType.CONTRACT)
        self.assertEqual(classify_event_type(None, "Company announces Rs 10000 Cr share buyback"), NewsEventType.FINANCING)
        self.assertEqual(classify_event_type(None, "Morgan Stanley upgrades Infosys to Overweight"), NewsEventType.RATING)

    def test_importance_assessment(self):
        # Explicit override
        self.assertEqual(assess_importance("HIGH", NewsEventType.OTHER, NewsSourceQuality.SECONDARY), NewsImportance.HIGH)
        self.assertEqual(assess_importance("LOW", NewsEventType.EARNINGS, NewsSourceQuality.OFFICIAL), NewsImportance.LOW)

        # Rule-based inference
        self.assertEqual(assess_importance(None, NewsEventType.EARNINGS, NewsSourceQuality.REPUTABLE_MEDIA), NewsImportance.HIGH)
        self.assertEqual(assess_importance(None, NewsEventType.REGULATORY, NewsSourceQuality.SECONDARY), NewsImportance.HIGH)
        self.assertEqual(assess_importance(None, NewsEventType.CONTRACT, NewsSourceQuality.REPUTABLE_MEDIA), NewsImportance.MEDIUM)
        self.assertEqual(assess_importance(None, NewsEventType.OTHER, NewsSourceQuality.SECONDARY), NewsImportance.LOW)

    def test_deduplication_and_summary_stats(self):
        articles_data = [
            {
                "headline": "Infosys wins $500M deal from Nordic Bank",
                "source": "Reuters",
                "published_at": "2025-06-15T08:00:00Z",
                "summary": "Infosys has secured a multi-year digital transformation contract.",
            },
            {
                "headline": "BREAKING: Infosys wins $500M deal from Nordic Bank!",
                "source": "Bloomberg",
                "published_at": "2025-06-15T08:30:00Z",
                "summary": "Nordic bank awards $500 million agreement to Infosys.",
            },
            {
                "headline": "Infosys Q4 results date announced for April 18",
                "source": "BSE",
                "published_at": "2025-06-14T10:00:00Z",
                "summary": "Board meeting to consider audited financial results.",
            },
        ]

        ctx = self.base_context.model_copy(update={"news_data": {"articles": articles_data}})
        articles, stats = NewsCalculator.process_news_data(ctx)

        self.assertEqual(len(articles), 3)
        self.assertEqual(stats["total_articles"], 3)
        
        # 1st article is not duplicate
        self.assertFalse(articles[0].is_duplicate)
        # 2nd article is duplicate of the 1st
        self.assertTrue(articles[1].is_duplicate)
        self.assertEqual(articles[0].duplicate_group_id, articles[1].duplicate_group_id)
        # 3rd article is distinct event
        self.assertFalse(articles[2].is_duplicate)

        # Total unique events = 2 (not 3!)
        self.assertEqual(stats["unique_events_count"], 2)
        # High importance count (BSE filing for earnings results)
        self.assertGreaterEqual(stats["high_importance_count"], 1)
        # Recent count (both unique events within 48h)
        self.assertEqual(stats["recent_count"], 2)

    def test_empty_and_malformed_news_data(self):
        # Empty dict
        ctx_empty = self.base_context.model_copy(update={"news_data": {}})
        articles, stats = NewsCalculator.process_news_data(ctx_empty)
        self.assertEqual(len(articles), 0)
        self.assertEqual(stats["total_articles"], 0)
        self.assertEqual(stats["unique_events_count"], 0)

        # Malformed list containing non-dict and empty headline items
        ctx_malformed = self.base_context.model_copy(update={
            "news_data": {
                "articles": [
                    "not a dict",
                    None,
                    {"headline": ""},
                    {"headline": "   "},
                    {"headline": "Valid Headline", "ticker_relevance": "NaN"},
                ]
            }
        })
        articles, stats = NewsCalculator.process_news_data(ctx_malformed)
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].headline, "Valid Headline")
        self.assertEqual(articles[0].ticker_relevance, 1.0)
        self.assertEqual(articles[0].context_id, "ctx-news-test-001")


if __name__ == "__main__":
    unittest.main()
