import unittest
from datetime import datetime, timezone, timedelta
import asyncio
from typing import List

from backend.domain.schemas import (
    MarketContext, HistoricalWindow, DataQualityStatus,
    InvestorType, HolderType, DealType,
    InstitutionalFlowObservation, OwnershipObservation,
    InstitutionalDeal, DeliveryObservation,
    SourceTier, VerificationStatus, DataQuality
)
from backend.specialists.institutional_calculator import (
    calc_net_flow, calc_ownership_change, calc_delivery_percentage,
    validate_percentage, validate_quantity, _clean_number
)

class TestInstitutionalFoundation(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        
    def test_1_flow_observation_creation(self):
        obs = InstitutionalFlowObservation(
            symbol="RELIANCE.NS",
            investor_type=InvestorType.FII,
            buy_value=1200.5,
            sell_value=1100.0,
            net_value=100.5,
            currency="INR_CR",
            exchange="NSE",
            period="1D",
            observed_at=self.now,
            source="NSE_Official",
            source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
            context_id="ctx-1"
        )
        self.assertEqual(obs.investor_type, InvestorType.FII)
        self.assertEqual(obs.net_value, 100.5)
        
    def test_2_fii_net_flow_calc(self):
        self.assertEqual(calc_net_flow(1200, 1100), 100)
        self.assertEqual(calc_net_flow(500, 700), -200)
        self.assertIsNone(calc_net_flow(1200, None))
        
    def test_3_dii_net_flow_calc(self):
        self.assertEqual(calc_net_flow(800.5, 400.0), 400.5)
        
    def test_4_combined_flow_calc(self):
        fii_net = calc_net_flow(1200, 1100)
        dii_net = calc_net_flow(800, 400)
        self.assertEqual(fii_net + dii_net, 500)
        
    def test_5_ownership_observation(self):
        obs = OwnershipObservation(
            symbol="TCS.NS",
            holder_type=HolderType.PROMOTER,
            ownership_percentage=72.3,
            period="Q3_2024",
            source="BSE_Official",
            source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
            context_id="ctx-2"
        )
        self.assertEqual(obs.holder_type, HolderType.PROMOTER)
        
    def test_6_ownership_change_calc(self):
        self.assertEqual(round(calc_ownership_change(72.3, 71.8), 4), 0.5)
        self.assertEqual(round(calc_ownership_change(50.0, 52.5), 4), -2.5)
        self.assertIsNone(calc_ownership_change(None, 52.5))
        
    def test_7_promoter_pledge_validation(self):
        self.assertEqual(validate_percentage(25.5), 25.5)
        self.assertIsNone(validate_percentage(-5.0))
        self.assertIsNone(validate_percentage(105.0))
        
    def test_8_bulk_deal_schema(self):
        deal = InstitutionalDeal(
            symbol="HDFCBANK.NS",
            exchange="NSE",
            deal_type=DealType.BULK,
            participant="VANGUARD",
            buy_sell="BUY",
            quantity=1500000,
            price=1600.0,
            value=2400000000,
            trade_date=self.now,
            source="NSE_Official",
            source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
            context_id="ctx-3"
        )
        self.assertEqual(deal.deal_type, DealType.BULK)
        
    def test_9_block_deal_schema(self):
        deal = InstitutionalDeal(
            symbol="HDFCBANK.NS",
            exchange="NSE",
            deal_type=DealType.BLOCK,
            participant="BLACKROCK",
            buy_sell="SELL",
            quantity=2000000,
            price=1590.0,
            value=3180000000,
            trade_date=self.now,
            source="NSE_Official",
            source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
            context_id="ctx-4"
        )
        self.assertEqual(deal.deal_type, DealType.BLOCK)
        
    def test_10_delivery_calculation(self):
        self.assertEqual(calc_delivery_percentage(62000, 100000), 62.0)
        self.assertEqual(calc_delivery_percentage(0, 100000), 0.0)
        self.assertIsNone(calc_delivery_percentage(62000, 0))
        self.assertIsNone(calc_delivery_percentage(62000, None))
        
    def test_11_invalid_percentages(self):
        self.assertIsNone(validate_percentage(-1))
        self.assertIsNone(validate_percentage(100.1))
        
    def test_12_invalid_quantities(self):
        self.assertIsNone(validate_quantity(-500))
        self.assertEqual(validate_quantity(0), 0)
        self.assertEqual(validate_quantity(500), 500)
        
    def test_13_provenance(self):
        obs = DeliveryObservation(
            symbol="INFY.NS",
            trade_date=self.now,
            traded_quantity=100,
            delivery_quantity=60,
            delivery_percentage=60.0,
            source="MOCK",
            source_tier=SourceTier.TIER_5_UNVERIFIED,
            observed_at=self.now,
            context_id="ctx-5"
        )
        self.assertEqual(obs.source_tier, SourceTier.TIER_5_UNVERIFIED)
        
    def test_14_market_context_integration(self):
        fii_flow = InstitutionalFlowObservation(
            symbol="RELIANCE.NS",
            investor_type=InvestorType.FII,
            buy_value=100.0,
            sell_value=0.0,
            net_value=100.0,
            currency="INR",
            exchange="NSE",
            period="1D",
            observed_at=self.now,
            source="Mock",
            source_tier=SourceTier.TIER_3_LICENSED,
            context_id="ctx"
        )
        dii_flow = InstitutionalFlowObservation(
            symbol="RELIANCE.NS",
            investor_type=InvestorType.DII,
            buy_value=0.0,
            sell_value=40.0,
            net_value=-40.0,
            currency="INR",
            exchange="NSE",
            period="1D",
            observed_at=self.now,
            source="Mock",
            source_tier=SourceTier.TIER_3_LICENSED,
            context_id="ctx"
        )
        promoter_own = OwnershipObservation(
            symbol="RELIANCE.NS",
            holder_type=HolderType.PROMOTER,
            ownership_percentage=51.2,
            period="Q3",
            source="Mock",
            source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
            context_id="ctx"
        )
        deliv = DeliveryObservation(
            symbol="RELIANCE.NS",
            trade_date=self.now,
            traded_quantity=1000,
            delivery_quantity=620,
            delivery_percentage=62.0,
            source="Mock",
            source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
            observed_at=self.now,
            context_id="ctx"
        )
        
        ctx = MarketContext(
            context_id="ctx",
            symbol="RELIANCE.NS",
            data_timestamp=self.now,
            provider="Mock",
            current_price=2500.0,
            institutional_data=[fii_flow, dii_flow],
            ownership_data=[promoter_own],
            delivery_data=[deliv]
        )
        
        self.assertEqual(len(ctx.institutional_data), 2)
        self.assertEqual(ctx.institutional_data[0].net_value, 100.0)
        self.assertEqual(ctx.institutional_data[1].net_value, -40.0)
        self.assertEqual(ctx.ownership_data[0].ownership_percentage, 51.2)
        self.assertEqual(ctx.delivery_data[0].delivery_percentage, 62.0)

if __name__ == "__main__":
    unittest.main()
