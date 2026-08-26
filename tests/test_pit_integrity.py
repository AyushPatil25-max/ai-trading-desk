import unittest
from datetime import datetime, timezone, timedelta
import uuid

from backend.domain.schemas import MarketContext
from backend.infrastructure.pit_integrity import PointInTimeValidator, PiTViolationLevel

class TestPointInTimeValidator(unittest.TestCase):
    def setUp(self):
        self.validator = PointInTimeValidator(max_staleness_hours=72.0)
        self.snapshot_time = datetime(2023, 1, 5, 12, 0, tzinfo=timezone.utc)
        
    def _make_context(self, data_ts: datetime, ohlcv: list = None) -> MarketContext:
        return MarketContext(
            context_id=str(uuid.uuid4()),
            symbol="TEST",
            data_timestamp=data_ts,
            provider="test",
            current_price=100.0,
            ohlcv_historical=ohlcv or []
        )
        
    def test_valid_context(self):
        # 2 hours old
        ctx = self._make_context(self.snapshot_time - timedelta(hours=2))
        report = self.validator.validate(ctx, self.snapshot_time)
        
        self.assertTrue(report.is_valid)
        self.assertTrue(report.frozen_verified)
        self.assertEqual(len(report.violations), 0)
        
    def test_future_leakage_root_timestamp(self):
        # 1 hour in the FUTURE
        future_ts = self.snapshot_time + timedelta(hours=1)
        ctx = self._make_context(future_ts)
        report = self.validator.validate(ctx, self.snapshot_time)
        
        self.assertFalse(report.is_valid)
        self.assertEqual(len(report.violations), 2) # Future leakage AND negative staleness
        
        rules = [v.rule for v in report.violations]
        self.assertIn("NO_FUTURE_LEAKAGE", rules)
        
        critical_violations = [v for v in report.violations if v.level == PiTViolationLevel.CRITICAL]
        self.assertEqual(len(critical_violations), 2)
        
    def test_future_leakage_ohlcv_data(self):
        # Root timestamp is fine
        ctx = self._make_context(self.snapshot_time - timedelta(hours=2))
        
        # But OHLCV contains future data
        future_date = (self.snapshot_time + timedelta(days=1)).isoformat()
        ctx_dict = ctx.model_dump()
        ctx_dict["ohlcv_historical"] = [
            {"date": (self.snapshot_time - timedelta(days=1)).isoformat()},
            {"date": future_date} # Leakage!
        ]
        
        # Re-instantiate frozen context
        leaky_ctx = MarketContext(**ctx_dict)
        report = self.validator.validate(leaky_ctx, self.snapshot_time)
        
        self.assertFalse(report.is_valid)
        self.assertEqual(len(report.violations), 1)
        self.assertEqual(report.violations[0].rule, "HISTORICAL_SNAPSHOT_CONSISTENCY")
        self.assertEqual(report.violations[0].level, PiTViolationLevel.CRITICAL)

    def test_provider_freshness_warning(self):
        # 100 hours old (limit is 72)
        stale_ts = self.snapshot_time - timedelta(hours=100)
        ctx = self._make_context(stale_ts)
        report = self.validator.validate(ctx, self.snapshot_time)
        
        # It should still be valid, but have a WARNING
        self.assertTrue(report.is_valid)
        self.assertEqual(len(report.violations), 1)
        self.assertEqual(report.violations[0].rule, "FRESHNESS_VALIDATION")
        self.assertEqual(report.violations[0].level, PiTViolationLevel.WARNING)
        
    def test_context_freeze_guarantee(self):
        # Monkeypatch the context to simulate a non-frozen model
        ctx = self._make_context(self.snapshot_time - timedelta(hours=2))
        
        # Temporarily override model_config
        original_config = ctx.model_config
        ctx.__class__.model_config = {"frozen": False}
        
        try:
            report = self.validator.validate(ctx, self.snapshot_time)
            self.assertFalse(report.is_valid)
            self.assertFalse(report.frozen_verified)
            self.assertEqual(len(report.violations), 1)
            self.assertEqual(report.violations[0].rule, "CONTEXT_FREEZE_GUARANTEE")
        finally:
            ctx.__class__.model_config = original_config

if __name__ == '__main__':
    unittest.main()
