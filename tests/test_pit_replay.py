"""
Unit tests for Point-In-Time (PIT) Data Filtering — Phase 5.2

Validates that no future data leaks into the simulation across any market modality.
"""

from datetime import datetime, timedelta
import unittest

from backend.domain.schemas import (
    CorporateDocument,
    DocumentType,
    HistoricalWindow,
    InstitutionalFlowObservation,
    InvestorType,
    MarketContext,
    SourceTier,
    VerificationStatus,
)
from backend.simulation.pit_filter import PointInTimeFilter


class TestPointInTimeFilter(unittest.TestCase):
    def setUp(self):
        self.t0 = datetime(2024, 1, 1, 10, 0, 0)
        self.t1 = datetime(2024, 1, 2, 10, 0, 0)
        self.t2 = datetime(2024, 1, 3, 10, 0, 0)
        self.t3 = datetime(2024, 1, 4, 10, 0, 0)

    def test_ohlcv_future_bars_rejected(self):
        bars = [
            {"timestamp": "2024-01-01 10:00:00", "close": 100.0},
            {"timestamp": "2024-01-02 10:00:00", "close": 105.0},
            {"timestamp": "2024-01-03 10:00:00", "close": 110.0},
            {"timestamp": "2024-01-04 10:00:00", "close": 115.0},
        ]
        # At T1: only bars for Jan 1 and Jan 2 must be included
        filtered = PointInTimeFilter.filter_ohlcv(bars, as_of=self.t1)
        self.assertEqual(len(filtered), 2)
        self.assertEqual(filtered[-1]["close"], 105.0)

    def test_fundamentals_future_filings_rejected(self):
        fundamental_data = {
            "pe_ratio": 22.5,
            "q3_results": {
                "publication_time": "2024-01-01 09:00:00",
                "net_profit": 5000.0,
            },
            "q4_results": {
                "publication_time": "2024-01-03 09:00:00",
                "net_profit": 6500.0,
            },
        }
        # At T1: Q4 results must NOT be visible
        filtered = PointInTimeFilter.filter_fundamentals(fundamental_data, as_of=self.t1)
        self.assertIn("pe_ratio", filtered)
        self.assertIn("q3_results", filtered)
        self.assertNotIn("q4_results", filtered)

    def test_news_future_articles_rejected(self):
        news = [
            {"title": "Past News", "published_at": "2024-01-01 08:00:00"},
            {"title": "Future News", "published_at": "2024-01-03 08:00:00"},
        ]
        filtered = PointInTimeFilter.filter_news(news, as_of=self.t1)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["title"], "Past News")

    def test_institutional_future_flows_rejected(self):
        from backend.domain.schemas import DataQuality
        flows = [
            InstitutionalFlowObservation(
                symbol="TCS.NS",
                investor_type=InvestorType.FII,
                buy_value=100.0,
                sell_value=50.0,
                net_value=50.0,
                currency="INR",
                exchange="NSE",
                period="1D",
                observed_at=self.t0,
                source="NSE",
                source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
                quality=DataQuality.HIGH,
                context_id="ctx-1",
            ),
            InstitutionalFlowObservation(
                symbol="TCS.NS",
                investor_type=InvestorType.FII,
                buy_value=200.0,
                sell_value=100.0,
                net_value=100.0,
                currency="INR",
                exchange="NSE",
                period="1D",
                observed_at=self.t2,
                source="NSE",
                source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
                quality=DataQuality.HIGH,
                context_id="ctx-1",
            ),
        ]
        filtered = PointInTimeFilter.filter_institutional(flows, as_of=self.t1)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].observed_at, self.t0)

    def test_corporate_documents_future_publications_rejected(self):
        docs = [
            CorporateDocument(
                document_id="doc-1",
                symbol="TCS.NS",
                company_name="TCS",
                document_type=DocumentType.ANNUAL_REPORT,
                title="FY23 Annual Report",
                source="BSE",
                source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
                publication_time=self.t0,
                period="FY23",
                reference="ref-1",
            ),
            CorporateDocument(
                document_id="doc-2",
                symbol="TCS.NS",
                company_name="TCS",
                document_type=DocumentType.ANNUAL_REPORT,
                title="FY24 Annual Report",
                source="BSE",
                source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
                publication_time=self.t2,
                period="FY24",
                reference="ref-2",
            ),
        ]
        filtered = PointInTimeFilter.filter_corporate_documents(docs, as_of=self.t1)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].document_id, "doc-1")

    def test_filter_market_context_updates_timestamp_and_price(self):
        raw_ctx = MarketContext(
            context_id="ctx-raw",
            symbol="INFY.NS",
            data_timestamp=self.t3,
            current_price=1600.0,
            provider="NSE",
            ohlcv_historical=[
                {"timestamp": "2024-01-01 10:00:00", "close": 1500.0},
                {"timestamp": "2024-01-02 10:00:00", "close": 1550.0},
                {"timestamp": "2024-01-03 10:00:00", "close": 1600.0},
            ],
        )
        pit_ctx = PointInTimeFilter.filter_market_context(raw_ctx, as_of=self.t1)
        self.assertEqual(pit_ctx.data_timestamp, self.t1)
        self.assertEqual(pit_ctx.current_price, 1550.0)
        self.assertEqual(len(pit_ctx.ohlcv_historical), 2)


if __name__ == "__main__":
    unittest.main()
