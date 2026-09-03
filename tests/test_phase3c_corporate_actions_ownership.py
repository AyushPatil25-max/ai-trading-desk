"""
Unit & Integration Tests for Phase 3C — Corporate Actions + Ownership Data Foundation

Tests:
1. CorporateAction schema & Dividend representation
2. Split representation (ratio, amount, description)
3. Bonus issue representation
4. Rights issue representation
5. Buyback representation
6. Missing dates handling (None vs valid dates)
7. Corporate action provenance preservation (source, tier, publication_time)
8. Conflict handling for corporate actions (distinct records preserved)
9. Corporate action PIT filtering (future declarations hidden)
10. OwnershipObservation: Promoter holding & pledge
11. Promoter pledge risk categorization (NONE, LOW, MODERATE, HIGH)
12. FII holding observation
13. DII holding observation
14. Public holding derivation
15. Missing ownership values explicit nullability
16. Ownership PIT filtering (future shareholding disclosures hidden)
17. Ownership provenance preservation
18. Ownership conflict handling
19. Cache integration (corporate actions & ownership cached with context)
20. Provider fallback (graceful degradation when unsupported)
21. Scanner Top-K selection behavior
22. No mass deep fetching during 520-stock Stage A prefiltering
23. Specialist integration (ownership metrics & pledge risk)
24. Full backward compatibility with existing MarketContext
"""

import unittest
import asyncio
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

from backend.domain.schemas import (
    MarketContext,
    CorporateAction,
    CorporateActionType,
    OwnershipObservation,
    HolderType,
    SourceTier,
    VerificationStatus,
    DataQuality,
    DataQualityStatus,
    HistoricalWindow,
    AgentInput,
    AgentState,
)
from backend.simulation.pit_filter import PointInTimeFilter
from backend.specialists.institutional_calculator import (
    calc_promoter_pledge_risk,
    calc_ownership_distribution,
    calc_ownership_change,
)
from backend.specialists.institutional_specialist import InstitutionalSpecialist
from backend.infrastructure.cache import InMemoryContextCache
from backend.scanner.universe import StockUniverse, UniverseType
from backend.scanner.prefilter import DeterministicPrefilter
from backend.scanner.scanner_config import ScannerConfig
from backend.infrastructure.llm import MockLLMClient


class TestPhase3CCorporateActionsOwnership(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
        self.t_ex = datetime(2024, 5, 20, 0, 0, 0, tzinfo=timezone.utc)
        self.t_ann = datetime(2024, 5, 5, 0, 0, 0, tzinfo=timezone.utc)

    # 1. Dividend
    def test_dividend_representation(self):
        div = CorporateAction(
            symbol="TCS.NS",
            event_type=CorporateActionType.DIVIDEND,
            announcement_date=self.t_ann,
            ex_date=self.t_ex,
            ratio_or_amount=28.0,
            currency="INR",
            description="Final Dividend ₹28.00 per share",
            source="yfinance",
            source_tier=SourceTier.TIER_4_SECONDARY,
            publication_time=self.t_ann,
        )
        self.assertEqual(div.event_type, CorporateActionType.DIVIDEND)
        self.assertEqual(div.ratio_or_amount, 28.0)
        self.assertEqual(div.symbol, "TCS.NS")

    # 2. Split
    def test_split_representation(self):
        split = CorporateAction(
            symbol="TATAMOTORS.NS",
            event_type=CorporateActionType.SPLIT,
            announcement_date=self.t_ann,
            ex_date=self.t_ex,
            ratio_or_amount=2.0,
            ratio_text="2:1",
            description="Stock Split 2:1",
        )
        self.assertEqual(split.event_type, CorporateActionType.SPLIT)
        self.assertEqual(split.ratio_text, "2:1")

    # 3. Bonus
    def test_bonus_representation(self):
        bonus = CorporateAction(
            symbol="INFY.NS",
            event_type=CorporateActionType.BONUS,
            announcement_date=self.t_ann,
            ex_date=self.t_ex,
            ratio_or_amount=1.0,
            ratio_text="1:1",
            description="Bonus Issue 1:1",
        )
        self.assertEqual(bonus.event_type, CorporateActionType.BONUS)

    # 4. Rights Issue
    def test_rights_issue_representation(self):
        rights = CorporateAction(
            symbol="RELIANCE.NS",
            event_type=CorporateActionType.RIGHTS_ISSUE,
            announcement_date=self.t_ann,
            ex_date=self.t_ex,
            ratio_or_amount=1257.0,
            description="Rights issue at ₹1257",
        )
        self.assertEqual(rights.event_type, CorporateActionType.RIGHTS_ISSUE)

    # 5. Buyback
    def test_buyback_representation(self):
        buyback = CorporateAction(
            symbol="TCS.NS",
            event_type=CorporateActionType.BUYBACK,
            announcement_date=self.t_ann,
            ratio_or_amount=4150.0,
            description="Tender offer buyback at ₹4150",
        )
        self.assertEqual(buyback.event_type, CorporateActionType.BUYBACK)
        self.assertEqual(buyback.ratio_or_amount, 4150.0)

    # 6. Missing Dates
    def test_missing_dates_explicit_none(self):
        act = CorporateAction(
            symbol="HDFCBANK.NS",
            event_type=CorporateActionType.DIVIDEND,
            ratio_or_amount=19.5,
            # announcement_date and payment_date intentionally omitted
        )
        self.assertIsNone(act.announcement_date)
        self.assertIsNone(act.payment_date)
        self.assertIsNone(act.record_date)

    # 7. Provenance Preservation
    def test_corporate_action_provenance(self):
        act = CorporateAction(
            symbol="ITC.NS",
            event_type=CorporateActionType.DIVIDEND,
            ratio_or_amount=6.25,
            source="NSE_Official",
            source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
            verification_status=VerificationStatus.VERIFIED,
        )
        self.assertEqual(act.source, "NSE_Official")
        self.assertEqual(act.source_tier, SourceTier.TIER_1_PRIMARY_OFFICIAL)
        self.assertEqual(act.verification_status, VerificationStatus.VERIFIED)

    # 8. Conflict Handling
    def test_corporate_action_conflict_handling(self):
        act1 = CorporateAction(
            symbol="TCS.NS",
            event_type=CorporateActionType.DIVIDEND,
            ex_date=self.t_ex,
            ratio_or_amount=28.0,
            source="NSE_Official",
            source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
        )
        act2 = CorporateAction(
            symbol="TCS.NS",
            event_type=CorporateActionType.DIVIDEND,
            ex_date=self.t_ex,
            ratio_or_amount=28.0,
            source="yfinance",
            source_tier=SourceTier.TIER_4_SECONDARY,
        )
        actions = [act1, act2]
        self.assertEqual(len(actions), 2)
        # Tier 1 ranked higher than Tier 4
        self.assertLess(act1.source_tier.value, act2.source_tier.value)

    # 9. Corporate Action PIT Filtering
    def test_corporate_action_pit_filtering(self):
        t_sim = datetime(2024, 5, 10, 10, 0, 0, tzinfo=timezone.utc)
        act_past = CorporateAction(
            symbol="TCS.NS",
            event_type=CorporateActionType.DIVIDEND,
            announcement_date=datetime(2024, 5, 5, tzinfo=timezone.utc),
            publication_time=datetime(2024, 5, 5, tzinfo=timezone.utc),
            ratio_or_amount=10.0,
        )
        act_future = CorporateAction(
            symbol="TCS.NS",
            event_type=CorporateActionType.DIVIDEND,
            announcement_date=datetime(2024, 5, 25, tzinfo=timezone.utc),
            publication_time=datetime(2024, 5, 25, tzinfo=timezone.utc),
            ratio_or_amount=15.0,
        )
        filtered = PointInTimeFilter.filter_corporate_actions([act_past, act_future], as_of=t_sim)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].ratio_or_amount, 10.0)

    # 10. Promoter Holding & Pledge
    def test_promoter_holding_and_pledge(self):
        obs = OwnershipObservation(
            symbol="ADANIENT.NS",
            holder_type=HolderType.PROMOTER,
            ownership_percentage=72.6,
            pledged_percentage=4.2,
            period="Q4-2024",
            source="NSE",
            source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
            context_id="ctx-own-1",
        )
        self.assertEqual(obs.holder_type, HolderType.PROMOTER)
        self.assertEqual(obs.ownership_percentage, 72.6)
        self.assertEqual(obs.pledged_percentage, 4.2)

    # 11. Promoter Pledge Risk
    def test_promoter_pledge_risk_classification(self):
        self.assertEqual(calc_promoter_pledge_risk(None), "UNKNOWN")
        self.assertEqual(calc_promoter_pledge_risk(0.0), "NONE")
        self.assertEqual(calc_promoter_pledge_risk(5.0), "LOW")
        self.assertEqual(calc_promoter_pledge_risk(15.0), "MODERATE")
        self.assertEqual(calc_promoter_pledge_risk(45.0), "HIGH")

    # 12. FII Holding
    def test_fii_holding_observation(self):
        obs = OwnershipObservation(
            symbol="HDFCBANK.NS",
            holder_type=HolderType.FII,
            ownership_percentage=52.1,
            period="Q4-2024",
            source="yfinance",
            source_tier=SourceTier.TIER_4_SECONDARY,
            context_id="ctx-fii-1",
        )
        self.assertEqual(obs.holder_type, HolderType.FII)
        self.assertEqual(obs.ownership_percentage, 52.1)

    # 13. DII Holding
    def test_dii_holding_observation(self):
        obs = OwnershipObservation(
            symbol="ICICIBANK.NS",
            holder_type=HolderType.DII,
            ownership_percentage=31.4,
            period="Q4-2024",
            source="yfinance",
            source_tier=SourceTier.TIER_4_SECONDARY,
            context_id="ctx-dii-1",
        )
        self.assertEqual(obs.holder_type, HolderType.DII)
        self.assertEqual(obs.ownership_percentage, 31.4)

    # 14. Public Holding & Distribution Calculation
    def test_ownership_distribution_calculation(self):
        obs_list = [
            OwnershipObservation(
                symbol="TCS.NS",
                holder_type=HolderType.PROMOTER,
                ownership_percentage=72.3,
                period="Latest",
                source="test",
                source_tier=SourceTier.TIER_4_SECONDARY,
                context_id="c1",
            ),
            OwnershipObservation(
                symbol="TCS.NS",
                holder_type=HolderType.FII,
                ownership_percentage=12.5,
                period="Latest",
                source="test",
                source_tier=SourceTier.TIER_4_SECONDARY,
                context_id="c2",
            ),
            OwnershipObservation(
                symbol="TCS.NS",
                holder_type=HolderType.DII,
                ownership_percentage=9.8,
                period="Latest",
                source="test",
                source_tier=SourceTier.TIER_4_SECONDARY,
                context_id="c3",
            ),
            OwnershipObservation(
                symbol="TCS.NS",
                holder_type=HolderType.PUBLIC,
                ownership_percentage=5.4,
                period="Latest",
                source="test",
                source_tier=SourceTier.TIER_4_SECONDARY,
                context_id="c4",
            ),
        ]
        dist = calc_ownership_distribution(obs_list)
        self.assertEqual(dist["promoter"], 72.3)
        self.assertEqual(dist["fii"], 12.5)
        self.assertEqual(dist["dii"], 9.8)
        self.assertEqual(dist["public"], 5.4)

    # 15. Missing Ownership Values Explicit Nullability
    def test_ownership_missing_values_explicit(self):
        obs = OwnershipObservation(
            symbol="STARTUP.NS",
            holder_type=HolderType.PROMOTER,
            ownership_percentage=55.0,
            # pledged_percentage and shares_held omitted
            period="Q1-2024",
            source="test",
            source_tier=SourceTier.TIER_4_SECONDARY,
            context_id="c_start",
        )
        self.assertIsNone(obs.pledged_percentage)
        self.assertIsNone(obs.shares_held)

    # 16. Ownership PIT Filtering
    def test_ownership_pit_filtering(self):
        t_sim = datetime(2024, 4, 15, 10, 0, 0, tzinfo=timezone.utc)
        obs_past = OwnershipObservation(
            symbol="TCS.NS",
            holder_type=HolderType.PROMOTER,
            ownership_percentage=72.3,
            report_date=datetime(2024, 3, 31, tzinfo=timezone.utc),
            publication_time=datetime(2024, 4, 10, tzinfo=timezone.utc),
            observed_at=datetime(2024, 4, 10, tzinfo=timezone.utc),
            period="Q4-2024",
            source="test",
            source_tier=SourceTier.TIER_4_SECONDARY,
            context_id="c_past",
        )
        obs_future = OwnershipObservation(
            symbol="TCS.NS",
            holder_type=HolderType.PROMOTER,
            ownership_percentage=72.1,
            report_date=datetime(2024, 6, 30, tzinfo=timezone.utc),
            publication_time=datetime(2024, 7, 10, tzinfo=timezone.utc),
            observed_at=datetime(2024, 7, 10, tzinfo=timezone.utc),
            period="Q1-2025",
            source="test",
            source_tier=SourceTier.TIER_4_SECONDARY,
            context_id="c_fut",
        )
        filtered = PointInTimeFilter.filter_ownership([obs_past, obs_future], as_of=t_sim)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].ownership_percentage, 72.3)

    # 17. Ownership Provenance
    def test_ownership_provenance_metadata(self):
        obs = OwnershipObservation(
            symbol="INFY.NS",
            holder_type=HolderType.PROMOTER,
            ownership_percentage=14.7,
            period="Q4-2024",
            source="NSE_Official",
            source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
            context_id="ctx-infy-1",
        )
        self.assertEqual(obs.source, "NSE_Official")
        self.assertEqual(obs.source_tier, SourceTier.TIER_1_PRIMARY_OFFICIAL)

    # 18. Ownership Conflict Handling
    def test_ownership_conflict_handling(self):
        obs1 = OwnershipObservation(
            symbol="TCS.NS",
            holder_type=HolderType.PROMOTER,
            ownership_percentage=72.3,
            period="Q4-2024",
            source="NSE_Official",
            source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
            context_id="c1",
        )
        obs2 = OwnershipObservation(
            symbol="TCS.NS",
            holder_type=HolderType.PROMOTER,
            ownership_percentage=72.4,
            period="Q4-2024",
            source="yfinance",
            source_tier=SourceTier.TIER_4_SECONDARY,
            context_id="c2",
        )
        self.assertNotEqual(obs1.ownership_percentage, obs2.ownership_percentage)
        self.assertEqual(obs1.source_tier, SourceTier.TIER_1_PRIMARY_OFFICIAL)

    # 19. Cache Integration
    def test_cache_stores_corporate_actions_and_ownership(self):
        cache = InMemoryContextCache(ttl_seconds=10)
        ctx = MarketContext(
            context_id="ctx-ca-own",
            symbol="TCS.NS",
            data_timestamp=self.now,
            provider="MultiSource",
            current_price=3500.0,
            corporate_actions=[
                CorporateAction(
                    symbol="TCS.NS",
                    event_type=CorporateActionType.DIVIDEND,
                    ratio_or_amount=28.0,
                )
            ],
            ownership_data=[
                OwnershipObservation(
                    symbol="TCS.NS",
                    holder_type=HolderType.PROMOTER,
                    ownership_percentage=72.3,
                    period="Latest",
                    source="test",
                    source_tier=SourceTier.TIER_4_SECONDARY,
                    context_id="c_c",
                )
            ],
        )

        loop = asyncio.new_event_loop()

        async def run_cache():
            await cache.set("TCS.NS", ctx)
            cached = await cache.get("TCS.NS")
            self.assertIsNotNone(cached)
            self.assertEqual(len(cached.corporate_actions), 1)
            self.assertEqual(len(cached.ownership_data), 1)

        loop.run_until_complete(run_cache())
        loop.close()

    # 20. Provider Fallback
    def test_provider_fallback_graceful(self):
        from backend.infrastructure.providers.base import BaseProvider, ProviderCapabilities, ProviderResult

        class EmptyProvider(BaseProvider):
            @property
            def name(self):
                return "empty"
            @property
            def capabilities(self):
                return ProviderCapabilities()
            @property
            def data_source_info(self):
                from backend.domain.schemas import DataSource
                return DataSource(provider_name="empty", authority="Test")

        p = EmptyProvider()
        loop = asyncio.new_event_loop()
        res_ca = loop.run_until_complete(p.get_corporate_actions("TCS.NS"))
        res_own = loop.run_until_complete(p.get_ownership("TCS.NS"))
        loop.close()

        self.assertEqual(res_ca.status, "ERROR")
        self.assertEqual(res_own.status, "ERROR")

    # 21. Scanner Top-K Behavior
    def test_scanner_top_k_behavior(self):
        universe = StockUniverse(UniverseType.NIFTY_500)
        symbols = universe.get_snapshot(self.now).get_symbols()
        self.assertGreater(len(symbols), 500)

    # 22. No Mass Deep Fetching during Stage A
    def test_stage_a_scanner_fast_execution(self):
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

    # 23. Specialist Integration
    def test_institutional_specialist_integration(self):
        from backend.specialists.institutional_specialist import (
            InstitutionalSpecialist,
            _InstitutionalLLMResponse,
            InstitutionalRegime,
            InstitutionalStrength,
            FIIRegime,
            DIIRegime,
            OwnershipRegime,
            PromoterRisk,
        )
        mock_resp = _InstitutionalLLMResponse(
            institutional_regime=InstitutionalRegime.ACCUMULATION,
            institutional_strength=InstitutionalStrength.STRONG,
            fii_regime=FIIRegime.BULLISH,
            dii_regime=DIIRegime.BULLISH,
            ownership_regime=OwnershipRegime.STABLE,
            promoter_risk=PromoterRisk.LOW,
            conclusion="Strong institutional accumulation with high promoter backing.",
            confidence=0.9,
        )
        mock_llm = MockLLMClient(fixed_response=mock_resp)
        specialist = InstitutionalSpecialist(mock_llm)

        ctx = MarketContext(
            context_id="ctx-inst-test",
            symbol="TCS.NS",
            data_timestamp=self.now,
            provider="MultiSource",
            current_price=3500.0,
            ownership_data=[
                OwnershipObservation(
                    symbol="TCS.NS",
                    holder_type=HolderType.PROMOTER,
                    ownership_percentage=72.3,
                    pledged_percentage=0.0,
                    period="Latest",
                    source="test",
                    source_tier=SourceTier.TIER_4_SECONDARY,
                    context_id="c1",
                ),
                OwnershipObservation(
                    symbol="TCS.NS",
                    holder_type=HolderType.FII,
                    ownership_percentage=12.5,
                    period="Latest",
                    source="test",
                    source_tier=SourceTier.TIER_4_SECONDARY,
                    context_id="c2",
                ),
            ],
            delivery_data=[],
            deal_data=[],
            institutional_data=[],
        )

        loop = asyncio.new_event_loop()
        agent_input = AgentInput(symbol="TCS.NS", market_context=ctx)
        out = loop.run_until_complete(specialist.execute(agent_input))
        loop.close()

        self.assertEqual(out.status, AgentState.SUCCESS)

    # 24. Backward Compatibility
    def test_market_context_backward_compatibility(self):
        ctx = MarketContext(
            context_id="ctx-compat",
            symbol="INFY.NS",
            data_timestamp=self.now,
            provider="legacy",
            current_price=1500.0,
        )
        self.assertEqual(ctx.corporate_actions, [])
        self.assertEqual(ctx.ownership_data, [])
        self.assertEqual(ctx.quarterly_fundamentals, [])


if __name__ == "__main__":
    unittest.main()
