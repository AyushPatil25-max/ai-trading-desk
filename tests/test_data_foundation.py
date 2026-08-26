import unittest
from datetime import datetime, timezone, timedelta
import uuid
import math

from backend.domain.schemas import (
    SourceTier, VerificationStatus, DataQuality, DataSource,
    ProvenanceRecord, DataConflict, MarketContext, HistoricalWindow
)
from backend.infrastructure.data_quality import (
    validate_numeric, validate_price, validate_timestamp,
    validate_currency, validate_period, validate_provenance
)
from backend.infrastructure.conflict_engine import Phase2ConflictEngine

class TestDataTrustFoundation(unittest.TestCase):
    
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.past = self.now - timedelta(days=1)
        
        self.ds1 = DataSource(
            provider_name="NSE",
            source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
            authority="Exchange",
            subscription_required=False,
            authentication_required=True,
            provider_version="v2"
        )
        self.ds2 = DataSource(
            provider_name="Aggregator",
            source_tier=SourceTier.TIER_3_LICENSED,
            authority="Vendor",
            subscription_required=True,
            authentication_required=True,
            provider_version="v1"
        )
        
        self.engine = Phase2ConflictEngine(tolerance_pct=0.05)

    def _make_provenance(self, ds, val, dt=None):
        ts = dt or self.now
        return ProvenanceRecord(
            metric="price",
            symbol="TEST",
            value=val,
            unit="INR",
            currency="INR",
            source=ds,
            verification_status=VerificationStatus.VERIFIED,
            quality=DataQuality.HIGH,
            observed_at=ts,
            retrieved_at=ts,
            publication_time=ts,
            effective_time=ts,
            period="Q1",
            context_id="ctx123",
            adjusted=False
        )

    # 1. provenance creation
    def test_1_provenance_creation(self):
        rec = self._make_provenance(self.ds1, 100.0)
        self.assertEqual(rec.metric, "price")
        self.assertEqual(rec.source.provider_name, "NSE")
        self.assertEqual(rec.quality, DataQuality.HIGH)

    # 2. tier ordering (Conflict Engine) & 6. conflict resolution
    def test_2_6_tier_ordering_and_resolution(self):
        # ds1 is TIER 1, ds2 is TIER 3. ds1 should win regardless of time.
        rec_a = self._make_provenance(self.ds2, 100.0, self.now) # Newer, but lower tier
        rec_b = self._make_provenance(self.ds1, 100.0, self.past) # Older, but higher tier
        
        winner, conflict = self.engine.resolve(rec_a, rec_b)
        self.assertEqual(winner.source.source_tier, SourceTier.TIER_1_PRIMARY_OFFICIAL)
        self.assertIsNone(conflict) # Values are identical (100.0)

    # 3. verification status & 5. conflict creation
    def test_3_5_verification_status_and_conflict_creation(self):
        # Different values > 5% tolerance -> CONFLICTED status and DataConflict record
        rec_a = self._make_provenance(self.ds1, 100.0) # Tier 1
        rec_b = self._make_provenance(self.ds2, 110.0) # Tier 3
        
        winner, conflict = self.engine.resolve(rec_a, rec_b)
        
        self.assertEqual(winner.verification_status, VerificationStatus.CONFLICTED)
        self.assertIsNotNone(conflict)
        self.assertEqual(conflict.absolute_difference, 10.0)
        self.assertAlmostEqual(conflict.percentage_difference, 0.1)

    # 4. quality validation
    def test_4_quality_validation(self):
        rec = self._make_provenance(self.ds1, 100.0)
        summary = validate_provenance(rec)
        self.assertEqual(summary["value"], DataQuality.HIGH)
        self.assertEqual(summary["currency"], DataQuality.HIGH)

    # 7. timestamp integrity (Equal tier newer wins)
    def test_7_timestamp_integrity_newer_wins(self):
        # Same tier (Tier 1), but one is newer
        ds1_alt = self.ds1.model_copy()
        ds1_alt.provider_name = "NSE_Backup"
        
        rec_old = self._make_provenance(self.ds1, 100.0, self.past)
        rec_new = self._make_provenance(ds1_alt, 100.0, self.now)
        
        winner, conflict = self.engine.resolve(rec_old, rec_new)
        self.assertEqual(winner.source.provider_name, "NSE_Backup")

    # 8. immutable context
    def test_8_immutable_context(self):
        ctx = MarketContext(
            context_id="ctx",
            symbol="TEST",
            data_timestamp=self.now,
            provider="test",
            current_price=100.0
        )
        with self.assertRaises(Exception): # Pydantic ValidationError on mutation
            ctx.current_price = 101.0
            
    # 9. backward compatibility
    def test_9_backward_compatibility(self):
        # Old code didn't provide provenance_records, conflicts, quality_summary
        ctx = MarketContext(
            context_id="ctx",
            symbol="TEST",
            data_timestamp=self.now,
            provider="test",
            current_price=100.0
        )
        # Should initialize gracefully
        self.assertEqual(ctx.conflicts, [])
        self.assertEqual(ctx.provenance_records, {})
        self.assertEqual(ctx.quality_summary, {})

    # 10. serialization
    def test_10_serialization(self):
        rec = self._make_provenance(self.ds1, 100.0)
        dumped = rec.model_dump_json()
        self.assertIn("TIER_1_PRIMARY_OFFICIAL", dumped)
        self.assertIn("VERIFIED", dumped)

    # 11. NaN rejection
    def test_11_nan_rejection(self):
        self.assertEqual(validate_numeric(float('nan')), DataQuality.INVALID)
        self.assertEqual(validate_numeric(math.inf), DataQuality.INVALID)
        self.assertEqual(validate_numeric("invalid_str"), DataQuality.INVALID)

    # 12. currency mismatch
    def test_12_currency_mismatch(self):
        self.assertEqual(validate_currency("USD", expected="INR"), DataQuality.LOW)
        self.assertEqual(validate_currency("INR", expected="INR"), DataQuality.HIGH)
        self.assertEqual(validate_currency(None), DataQuality.INVALID)

    # 13. period mismatch
    def test_13_period_mismatch(self):
        self.assertEqual(validate_period("Q1"), DataQuality.HIGH)
        self.assertEqual(validate_period("FY23"), DataQuality.HIGH)
        self.assertEqual(validate_period("RANDOM"), DataQuality.MEDIUM)
        self.assertEqual(validate_period(""), DataQuality.INVALID)

    # 14. invalid timestamps
    def test_14_invalid_timestamps(self):
        future_ts = self.now + timedelta(hours=2) # beyond 60s tolerance
        self.assertEqual(validate_timestamp(future_ts), DataQuality.INVALID)
        self.assertEqual(validate_timestamp("not_a_date"), DataQuality.INVALID)
        self.assertEqual(validate_timestamp(self.past), DataQuality.HIGH)

    # 15. duplicate provenance
    def test_15_duplicate_provenance_same_values(self):
        # Resolving identical records should not create conflict
        rec_a = self._make_provenance(self.ds1, 100.0)
        rec_b = self._make_provenance(self.ds1, 100.0)
        winner, conflict = self.engine.resolve(rec_a, rec_b)
        self.assertIsNone(conflict)

if __name__ == '__main__':
    unittest.main()
