import unittest
from datetime import datetime, timezone
from pydantic import ValidationError

from backend.domain.schemas import (
    DataQualityTier,
    ProviderType,
    TrustLevel,
    ConflictSeverity,
    SourceAttribution,
    MetricProvenance,
    DataConflictRecord,
    MarketContext,
    HistoricalWindow,
    DataQualityStatus
)

class TestDataProvenanceSchemas(unittest.TestCase):
    def test_enums_exist_and_have_correct_values(self):
        self.assertEqual(DataQualityTier.TIER_1_PRIMARY_OFFICIAL.value, "TIER_1_PRIMARY_OFFICIAL")
        self.assertEqual(ProviderType.EXCHANGE.value, "EXCHANGE")
        self.assertEqual(TrustLevel.VERIFIED_HIGH_TRUST.value, "VERIFIED_HIGH_TRUST")
        self.assertEqual(ConflictSeverity.CRITICAL.value, "CRITICAL")

    def test_source_attribution_instantiation(self):
        sa = SourceAttribution(
            provider_name="NSE",
            provider_type=ProviderType.EXCHANGE,
            quality_tier=DataQualityTier.TIER_1_PRIMARY_OFFICIAL,
            trust_level=TrustLevel.VERIFIED_HIGH_TRUST,
            attribution_notes="Direct websocket feed"
        )
        self.assertEqual(sa.provider_name, "NSE")
        self.assertEqual(sa.provider_type, ProviderType.EXCHANGE)
        self.assertEqual(sa.quality_tier, DataQualityTier.TIER_1_PRIMARY_OFFICIAL)
        self.assertEqual(sa.trust_level, TrustLevel.VERIFIED_HIGH_TRUST)

    def test_metric_provenance_instantiation(self):
        ts = datetime.now(timezone.utc)
        mp = MetricProvenance(
            metric_name="revenue",
            metric_value=1500000.0,
            provider="CompanyXBRL",
            provider_timestamp=ts,
            quality_tier=DataQualityTier.TIER_1_PRIMARY_OFFICIAL,
            trust_score=0.95
        )
        self.assertEqual(mp.metric_name, "revenue")
        self.assertEqual(mp.metric_value, 1500000.0)
        self.assertIsNotNone(mp.ingestion_timestamp)
        self.assertEqual(mp.trust_score, 0.95)

    def test_metric_provenance_trust_score_validation(self):
        ts = datetime.now(timezone.utc)
        with self.assertRaises(ValidationError):
            MetricProvenance(
                metric_name="revenue",
                metric_value=100.0,
                provider="Test",
                provider_timestamp=ts,
                quality_tier=DataQualityTier.TIER_1_PRIMARY_OFFICIAL,
                trust_score=1.5  # Invalid, > 1.0
            )

    def test_data_conflict_record_instantiation(self):
        cr = DataConflictRecord(
            field_name="current_price",
            conflict_severity=ConflictSeverity.LOW,
            conflicting_values=[100.5, 100.6],
            resolution_strategy="MAJORITY",
            resolved_value=100.55
        )
        self.assertEqual(cr.field_name, "current_price")
        self.assertEqual(cr.conflict_severity, ConflictSeverity.LOW)
        self.assertEqual(len(cr.conflicting_values), 2)
        self.assertEqual(cr.resolved_value, 100.55)

    def test_market_context_backwards_compatibility(self):
        # Ensure we can instantiate MarketContext just like before
        ts = datetime.now(timezone.utc)
        mc = MarketContext(
            context_id="test-123",
            symbol="RELIANCE.NS",
            data_timestamp=ts,
            provider="yfinance",
            current_price=2500.0
        )
        # Check new default fields
        self.assertEqual(mc.source_provider, "UNKNOWN")
        self.assertIsNone(mc.source_timestamp)
        self.assertEqual(mc.provider_priority, 99)
        self.assertIsNone(mc.data_quality_tier)
        self.assertEqual(mc.trust_score, 0.5)
        self.assertEqual(mc.confidence_score, 0.5)
        self.assertEqual(mc.conflicts, [])
        self.assertEqual(mc.provenance_records, {})

        # Check existing fields
        self.assertEqual(mc.current_price, 2500.0)
        self.assertEqual(mc.historical_window, HistoricalWindow.RECENT)
        self.assertEqual(mc.quality_status, DataQualityStatus.OK)

    def test_market_context_with_provenance(self):
        ts = datetime.now(timezone.utc)
        mp = MetricProvenance(
            metric_name="current_price",
            metric_value=2500.0,
            provider="NSE",
            provider_timestamp=ts,
            quality_tier=DataQualityTier.TIER_1_PRIMARY_OFFICIAL,
            trust_score=0.99
        )
        cr = DataConflictRecord(
            field_name="current_price",
            conflict_severity=ConflictSeverity.LOW,
            conflicting_values=[2500.0, 2499.5],
            resolution_strategy="TIER_1_OVERRIDE",
            resolved_value=2500.0
        )
        
        mc = MarketContext(
            context_id="test-124",
            symbol="RELIANCE.NS",
            data_timestamp=ts,
            provider="NSE",
            current_price=2500.0,
            source_provider="NSE",
            source_timestamp=ts,
            provider_priority=1,
            data_quality_tier=DataQualityTier.TIER_1_PRIMARY_OFFICIAL,
            trust_score=0.99,
            confidence_score=0.95,
            conflicts=[cr],
            provenance_records={"current_price": mp}
        )

        self.assertEqual(mc.source_provider, "NSE")
        self.assertEqual(mc.provider_priority, 1)
        self.assertEqual(mc.data_quality_tier, DataQualityTier.TIER_1_PRIMARY_OFFICIAL)
        self.assertEqual(len(mc.conflicts), 1)
        self.assertIn("current_price", mc.provenance_records)

if __name__ == '__main__':
    unittest.main()
