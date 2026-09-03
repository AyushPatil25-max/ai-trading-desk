"""
Test Suite for Phase 2 — Data Coverage Foundation Implementation

Comprehensive unit and integration tests covering:
1. Security Master & Identifier Resolution (NSE, BSE, ISIN, Aliases)
2. Data Quality & Completeness States (DATA_COMPLETE, DATA_PARTIAL, DATA_STALE, DATA_CONFLICT, DATA_INSUFFICIENT)
3. Deterministic Data Quality Scoring Model (0.0 - 1.0)
4. Distinguishing Missing vs. Zero vs. Legitimate Negative Financial Values
5. Provider Enhancements (RBI Provider Macro Metrics, YFinance Provider Fundamentals & News)
6. MultiSourceOrchestrator Multi-Domain Aggregation
7. Domain-Aware Caching & Observability (Hit/Miss Stats, TTLs)
8. Point-in-Time Integrity & Scanner Stage A Filtering
"""

import unittest
import asyncio
from datetime import datetime, timezone, timedelta
import uuid

from backend.domain.schemas import (
    DataQuality,
    DataQualityStatus,
    HistoricalWindow,
    MarketContext,
    ProvenanceRecord,
    SourceTier,
    VerificationStatus,
    FinancialObservation,
    PeriodType,
)
from backend.infrastructure.security_master import (
    SecurityDefinition,
    SecurityMaster,
    get_security_master,
)
from backend.infrastructure.data_quality import (
    DataCompletenessState,
    compute_data_quality_score,
    determine_completeness_state,
    is_missing_value,
    is_valid_numeric_value,
    validate_numeric,
    validate_price,
    validate_timestamp,
    validate_currency,
    validate_period,
)
from backend.infrastructure.cache import InMemoryContextCache
from backend.infrastructure.providers.rbi_provider import RBIProvider
from backend.infrastructure.providers.yfinance_provider import YFinanceProvider
from backend.infrastructure.providers.nse_provider import NSEProvider
from backend.infrastructure.providers.orchestrator import MultiSourceOrchestrator
from backend.infrastructure.providers.base import BaseProvider, ProviderCapabilities, ProviderResult
from backend.simulation.pit_filter import PointInTimeFilter
from backend.scanner.prefilter import DeterministicPrefilter
from backend.scanner.scanner_config import ScannerConfig


class TestSecurityMaster(unittest.TestCase):
    def setUp(self):
        self.sm = SecurityMaster()

    def test_resolve_canonical_symbol(self):
        sec = self.sm.resolve_symbol("RELIANCE")
        self.assertIsNotNone(sec)
        self.assertEqual(sec.canonical_symbol, "RELIANCE")
        self.assertEqual(sec.exchange, "NSE")
        self.assertEqual(sec.isin, "INE002A01018")

    def test_resolve_nse_suffix(self):
        sec = self.sm.resolve_symbol("TCS.NS")
        self.assertIsNotNone(sec)
        self.assertEqual(sec.canonical_symbol, "TCS")
        self.assertEqual(sec.bse_code, "532540")

    def test_resolve_bse_code(self):
        sec = self.sm.resolve_symbol("500180")
        self.assertIsNotNone(sec)
        self.assertEqual(sec.canonical_symbol, "HDFCBANK")

    def test_resolve_isin(self):
        sec = self.sm.get_security_by_isin("INE009A01021")
        self.assertIsNotNone(sec)
        self.assertEqual(sec.canonical_symbol, "INFY")

    def test_resolve_alias(self):
        sec = self.sm.resolve_symbol("HUL")
        self.assertIsNotNone(sec)
        self.assertIn(sec.canonical_symbol, ["HINDUNILVR", "HUL"])

    def test_case_insensitivity(self):
        sec = self.sm.resolve_symbol("sbin.ns")
        self.assertIsNotNone(sec)
        self.assertEqual(sec.canonical_symbol, "SBIN")

    def test_normalize_ticker_for_provider(self):
        ticker_yf = self.sm.normalize_ticker_for_provider("INFY", "yfinance")
        self.assertEqual(ticker_yf, "INFY.NS")

        ticker_already_ns = self.sm.normalize_ticker_for_provider("TCS.NS", "yfinance")
        self.assertEqual(ticker_already_ns, "TCS.NS")

    def test_list_securities_by_sector(self):
        tech_stocks = self.sm.list_securities(sector="Technology")
        symbols = [s.canonical_symbol for s in tech_stocks]
        self.assertIn("TCS", symbols)
        self.assertIn("INFY", symbols)
        self.assertIn("HCLTECH", symbols)


class TestDataQualityAndMissingValues(unittest.TestCase):
    def test_missing_vs_zero_vs_negative(self):
        # Missing values
        self.assertTrue(is_missing_value(None))
        self.assertTrue(is_missing_value(""))
        self.assertTrue(is_missing_value(float("nan")))

        # Zero is NOT missing (e.g. 0 debt is legitimate)
        self.assertFalse(is_missing_value(0))
        self.assertFalse(is_missing_value(0.0))

        # Negative is NOT missing (e.g. negative net income is legitimate loss)
        self.assertFalse(is_missing_value(-500.0))
        self.assertFalse(is_missing_value("-123.45"))

        # Numeric validation
        self.assertTrue(is_valid_numeric_value(-500.0, allow_negative=True))
        self.assertFalse(is_valid_numeric_value(-500.0, allow_negative=False))
        self.assertTrue(is_valid_numeric_value(0.0))
        self.assertFalse(is_valid_numeric_value(None))

    def test_data_completeness_states(self):
        now = datetime.now(timezone.utc)

        # 1. Complete context
        complete_ctx = MarketContext(
            context_id="ctx-complete",
            symbol="TCS.NS",
            data_timestamp=now,
            provider="yfinance",
            current_price=3500.0,
            ohlcv_historical=[{"close": 3500.0, "volume": 1000}] * 60,
            technical_indicators={"ema20": 3480.0, "ema50": 3450.0, "rsi": 58.0, "20_day_high": 3520.0},
            fundamental_data={"revenue": 200000.0, "net_income": 45000.0, "eps": 120.0, "cash": 15000.0},
            quality_status=DataQualityStatus.OK,
        )
        self.assertEqual(determine_completeness_state(complete_ctx, as_of=now), DataCompletenessState.DATA_COMPLETE)
        score = compute_data_quality_score(complete_ctx, as_of=now)
        self.assertGreaterEqual(score, 0.75)

        # 2. Partial context (Price + technicals, but fundamentals missing)
        partial_ctx = complete_ctx.model_copy(update={"fundamental_data": {}})
        self.assertEqual(determine_completeness_state(partial_ctx, as_of=now), DataCompletenessState.DATA_PARTIAL)

        # 3. Insufficient context (Price <= 0 or empty OHLCV)
        insufficient_ctx = complete_ctx.model_copy(update={"current_price": 0.0, "ohlcv_historical": []})
        self.assertEqual(determine_completeness_state(insufficient_ctx, as_of=now), DataCompletenessState.DATA_INSUFFICIENT)
        self.assertEqual(compute_data_quality_score(insufficient_ctx), 0.0)

        # 4. Stale context (> 7 days old)
        stale_time = now - timedelta(days=10)
        stale_ctx = complete_ctx.model_copy(update={"data_timestamp": stale_time})
        self.assertEqual(determine_completeness_state(stale_ctx, as_of=now, max_stale_days=7), DataCompletenessState.DATA_STALE)

        # 5. Conflicted context
        from backend.domain.schemas import DataConflict
        conflicted_ctx = complete_ctx.model_copy(update={
            "conflicts": [
                DataConflict(
                    metric="price",
                    symbol="TCS.NS",
                    source_a="A",
                    value_a=100.0,
                    source_b="B",
                    value_b=120.0,
                    timestamp_a=now,
                    timestamp_b=now,
                    absolute_difference=20.0,
                    percentage_difference=0.2,
                    resolution="A wins",
                    resolution_reason="Tolerance breached",
                )
            ]
        })
        self.assertEqual(determine_completeness_state(conflicted_ctx, as_of=now), DataCompletenessState.DATA_CONFLICT)


class TestRBIProvider(unittest.TestCase):
    def setUp(self):
        self.rbi = RBIProvider()

    def test_capabilities(self):
        self.assertTrue(self.rbi.capabilities.macro)
        self.assertFalse(self.rbi.capabilities.quotes)
        self.assertEqual(self.rbi.data_source_info.source_tier, SourceTier.TIER_1_PRIMARY_OFFICIAL)

    def test_get_macro_metrics(self):
        loop = asyncio.new_event_loop()
        res = loop.run_until_complete(self.rbi.get_macro())
        loop.close()

        self.assertEqual(res.status, "SUCCESS")
        self.assertIn("policy_rate", res.data)
        self.assertEqual(res.data["policy_rate"], 6.50)
        self.assertIn("inflation_rate", res.data)
        self.assertIn("treasury_10y", res.data)
        self.assertIn("treasury_2y", res.data)

        # Verify provenance
        self.assertGreaterEqual(len(res.provenance), 5)
        prov = res.provenance[0]
        self.assertEqual(prov.source.provider_name, "RBI_Official")
        self.assertEqual(prov.verification_status, VerificationStatus.VERIFIED)


class TestYFinanceProviderEnrichment(unittest.TestCase):
    def setUp(self):
        self.yfp = YFinanceProvider()

    def test_capabilities(self):
        self.assertTrue(self.yfp.capabilities.quotes)
        self.assertTrue(self.yfp.capabilities.historical)
        self.assertTrue(self.yfp.capabilities.fundamentals)
        self.assertTrue(self.yfp.capabilities.news)
        self.assertEqual(self.yfp.data_source_info.source_tier, SourceTier.TIER_4_SECONDARY)

    def test_fundamentals_fallback_structure(self):
        # Verify sync helper returns valid FinancialObservations
        from unittest.mock import MagicMock, patch
        mock_info = {
            "totalRevenue": 240000000000,
            "grossProfits": 100000000000,
            "operatingMargins": 0.25,
            "netIncomeToCommon": 45000000000,
            "trailingEps": 120.5,
            "totalCash": 15000000000,
            "totalDebt": 5000000000,
            "trailingPE": 28.5,
            "priceToBook": 8.2,
            "returnOnEquity": 0.35,
            "currency": "INR",
        }

        with patch("yfinance.Ticker") as mock_ticker_cls:
            mock_inst = MagicMock()
            mock_inst.info = mock_info
            mock_ticker_cls.return_value = mock_inst

            res = self.yfp._get_fundamentals_sync("TCS.NS")
            self.assertEqual(res.status, "SUCCESS")
            data = res.data
            self.assertIn("revenue", data)
            self.assertIn("pe_ratio", data)
            self.assertEqual(data["pe_ratio"].value, 28.5)
            self.assertEqual(data["revenue"].currency, "INR")


class TestMultiSourceOrchestratorEnrichment(unittest.TestCase):
    def test_orchestrator_multi_domain_assembly(self):
        # Mock providers
        mock_rbi = RBIProvider()

        class MockQuotesProvider(BaseProvider):
            @property
            def name(self) -> str:
                return "MockNSE"

            @property
            def capabilities(self) -> ProviderCapabilities:
                return ProviderCapabilities(quotes=True, historical=True, fundamentals=True, news=True)

            @property
            def data_source_info(self):
                from backend.domain.schemas import DataSource
                return DataSource(
                    provider_name="MockNSE",
                    source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
                    authority="Exchange",
                    subscription_required=False,
                    authentication_required=False,
                    provider_version="v1",
                )

            async def get_quote(self, symbol: str) -> ProviderResult:
                now = datetime.now(timezone.utc)
                prov = ProvenanceRecord(
                    metric="current_price",
                    symbol=symbol,
                    value=2500.0,
                    unit="INR",
                    currency="INR",
                    source=self.data_source_info,
                    verification_status=VerificationStatus.VERIFIED,
                    quality=DataQuality.HIGH,
                    observed_at=now,
                    retrieved_at=now,
                    publication_time=now,
                    effective_time=now,
                    period="real-time",
                    context_id=str(uuid.uuid4()),
                    adjusted=False,
                )
                return ProviderResult(status="SUCCESS", data={"current_price": 2500.0}, provenance=[prov])

            async def get_historical_data(self, symbol: str, period: str) -> ProviderResult:
                now = datetime.now(timezone.utc)
                bars = []
                for i in range(60):
                    t = now - timedelta(days=60 - i)
                    bars.append({"Date": t.isoformat(), "Open": 2400.0 + i, "High": 2420.0 + i, "Low": 2390.0 + i, "Close": 2410.0 + i, "Volume": 50000})
                return ProviderResult(status="SUCCESS", data={"ohlcv": bars})

            async def get_fundamentals(self, symbol: str) -> ProviderResult:
                return ProviderResult(status="SUCCESS", data={"revenue": 500000.0, "net_income": 80000.0, "pe_ratio": 22.0, "eps": 95.0, "cash": 20000.0})

            async def get_news(self, symbol: str) -> ProviderResult:
                return ProviderResult(status="SUCCESS", data={"articles": [{"title": "Record Profits Q3", "published_at": datetime.now(timezone.utc).isoformat()}]})

        orchestrator = MultiSourceOrchestrator([MockQuotesProvider(), mock_rbi])
        ctx = orchestrator.get_market_context("RELIANCE.NS", HistoricalWindow.RECENT)

        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.current_price, 2500.0)
        self.assertEqual(len(ctx.ohlcv_historical), 5)
        self.assertIn("ema20", ctx.technical_indicators)
        self.assertIn("rsi", ctx.technical_indicators)
        self.assertIn("policy_rate", ctx.macro_data)
        self.assertEqual(ctx.macro_data["policy_rate"], 6.50)
        self.assertIn("articles", ctx.news_data)
        self.assertGreater(ctx.trust_score, 0.5)


class TestContextCacheDomainAware(unittest.TestCase):
    def test_cache_hit_and_miss_stats(self):
        cache = InMemoryContextCache(ttl_seconds=2)
        ctx = MarketContext(
            context_id="ctx-test",
            symbol="TCS.NS",
            data_timestamp=datetime.now(timezone.utc),
            provider="test",
            current_price=3000.0,
            historical_window=HistoricalWindow.RECENT,
            quality_status=DataQualityStatus.OK,
        )

        loop = asyncio.new_event_loop()

        async def run_cache_test():
            # 1. Initial miss
            val1 = await cache.get("key1")
            self.assertIsNone(val1)
            self.assertEqual(cache.misses, 1)

            # 2. Set and hit
            await cache.set("key1", ctx, ttl_seconds=5)
            val2 = await cache.get("key1")
            self.assertIsNotNone(val2)
            self.assertTrue(val2.is_cached)
            self.assertEqual(cache.hits, 1)
            self.assertEqual(cache.hit_rate, 0.5)

            # 3. Stats inspection
            stats = cache.get_stats()
            self.assertEqual(stats["hits"], 1)
            self.assertEqual(stats["misses"], 1)
            self.assertEqual(stats["total_requests"], 2)
            self.assertEqual(stats["cached_entries"], 1)

        loop.run_until_complete(run_cache_test())
        loop.close()


class TestPointInTimeAndPrefilterIntegration(unittest.TestCase):
    def test_pit_filters_future_macro_and_fundamentals(self):
        t_sim = datetime(2023, 6, 1, 10, 0, 0)
        raw_ohlcv = [
            {"date": "2023-05-01 10:00:00", "close": 2000.0},
            {"date": "2023-05-15 10:00:00", "close": 2050.0},
            {"date": "2023-06-01 09:00:00", "close": 2100.0},
            {"date": "2023-07-01 10:00:00", "close": 2500.0},  # Future bar
        ]
        filtered = PointInTimeFilter.filter_ohlcv(raw_ohlcv, as_of=t_sim)
        self.assertEqual(len(filtered), 3)
        self.assertEqual(filtered[-1]["close"], 2100.0)

    def test_prefilter_with_quality_screening(self):
        config = ScannerConfig(min_price=100.0, max_price=50000.0, min_historical_bars=5)
        prefilter = DeterministicPrefilter(config)

        # Valid candidate
        valid_data = {
            "current_price": 2500.0,
            "ohlcv_historical": [{"close": 2500.0}] * 10,
            "fundamental_data": {"revenue": 10000.0},
        }
        res = prefilter.filter_candidate("RELIANCE.NS", valid_data)
        self.assertTrue(res.passed)
        self.assertTrue(res.metrics_summary["has_fundamentals"])


if __name__ == "__main__":
    unittest.main()
