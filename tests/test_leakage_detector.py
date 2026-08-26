"""
Unit tests for Point-In-Time Leakage Detector — Phase 5.4

Validates detection of look-ahead contamination across OHLCV, fundamentals, news,
institutional observations, and universe constituent updates.
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
from backend.scanner.universe import UniverseConstituent, UniverseSnapshot, UniverseType
from backend.validation.leakage_detector import LeakageDetector
from backend.validation.validation_state import LeakageSeverity


class TestLeakageDetector(unittest.TestCase):
    def setUp(self):
        self.t_decision = datetime(2024, 1, 1, 10, 0, 0)
        self.t_past = datetime(2023, 12, 31, 10, 0, 0)
        self.t_future = datetime(2024, 1, 2, 10, 0, 0)

    def test_clean_context_has_no_leakage(self):
        clean_ctx = MarketContext(
            context_id="ctx-clean",
            symbol="TCS.NS",
            data_timestamp=self.t_decision,
            current_price=3000.0,
            provider="NSE",
            ohlcv_historical=[{"timestamp": "2023-12-31 10:00:00", "close": 3000.0}],
            fundamental_data={"q3": {"publication_time": "2023-12-30", "net_profit": 5000.0}},
            news_data={"articles": [{"title": "Past News", "published_at": "2023-12-30"}]},
            institutional_data=[],
        )
        findings = LeakageDetector.check_market_context(clean_ctx, decision_timestamp=self.t_decision)
        self.assertEqual(len(findings), 0)
        self.assertTrue(LeakageDetector.is_clean(findings))

    def test_future_ohlcv_detected_as_critical(self):
        leaked_ctx = MarketContext(
            context_id="ctx-leak-ohlcv",
            symbol="TCS.NS",
            data_timestamp=self.t_decision,
            current_price=3000.0,
            provider="NSE",
            ohlcv_historical=[
                {"timestamp": "2023-12-31 10:00:00", "close": 3000.0},
                {"timestamp": "2024-01-02 10:00:00", "close": 3200.0},  # Future
            ],
        )
        findings = LeakageDetector.check_market_context(leaked_ctx, decision_timestamp=self.t_decision)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].category, "OHLCV")
        self.assertEqual(findings[0].severity, LeakageSeverity.CRITICAL)
        self.assertFalse(LeakageDetector.is_clean(findings))

    def test_future_fundamentals_detected_as_critical(self):
        leaked_ctx = MarketContext(
            context_id="ctx-leak-fund",
            symbol="TCS.NS",
            data_timestamp=self.t_decision,
            current_price=3000.0,
            provider="NSE",
            ohlcv_historical=[{"timestamp": "2023-12-31 10:00:00", "close": 3000.0}],
            fundamental_data={
                "q4_results": {"publication_time": "2024-01-05 09:00:00", "net_profit": 7000.0}
            },
        )
        findings = LeakageDetector.check_market_context(leaked_ctx, decision_timestamp=self.t_decision)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].category, "FUNDAMENTALS")
        self.assertEqual(findings[0].severity, LeakageSeverity.CRITICAL)

    def test_future_news_detected_as_high(self):
        leaked_ctx = MarketContext(
            context_id="ctx-leak-news",
            symbol="TCS.NS",
            data_timestamp=self.t_decision,
            current_price=3000.0,
            provider="NSE",
            ohlcv_historical=[{"timestamp": "2023-12-31 10:00:00", "close": 3000.0}],
            news_data={"articles": [{"title": "Future Event", "published_at": "2024-01-03 12:00:00"}]},
        )
        findings = LeakageDetector.check_market_context(leaked_ctx, decision_timestamp=self.t_decision)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].category, "NEWS")
        self.assertEqual(findings[0].severity, LeakageSeverity.HIGH)

    def test_future_universe_constituent_detected(self):
        snap = UniverseSnapshot(
            universe_type=UniverseType.CUSTOM,
            as_of=self.t_decision,
            constituents=[
                UniverseConstituent(symbol="TCS.NS", company_name="TCS", effective_from=self.t_past),
                UniverseConstituent(symbol="FUTURE_IPO.NS", company_name="Future IPO", effective_from=self.t_future),
            ],
        )
        findings = LeakageDetector.check_universe_snapshot(snap, decision_timestamp=self.t_decision)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].category, "UNIVERSE_CONSTITUENT")
        self.assertEqual(findings[0].severity, LeakageSeverity.CRITICAL)


if __name__ == "__main__":
    unittest.main()
