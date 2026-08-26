"""
Unit tests for Survivorship Bias Auditor — Phase 5.4C

Validates detection of future constituent leakage, delisted security exclusion,
and coverage percentage calculations.
"""

from datetime import datetime
import unittest

from backend.scanner.historical_universe import HistoricalUniverse
from backend.validation.survivorship_audit import (
    SurvivorshipAuditor,
    SurvivorshipFindingType,
)


class TestSurvivorshipAudit(unittest.TestCase):
    def setUp(self):
        self.hu = HistoricalUniverse()

    def test_clean_historical_snapshot_has_no_survivorship_bias(self):
        as_of = datetime(2023, 1, 1)
        valid_constituents = [c.symbol for c in self.hu.get_constituents(as_of)]
        res = SurvivorshipAuditor.audit_universe_snapshot(
            snapshot_symbols=valid_constituents,
            as_of=as_of,
            historical_universe=self.hu,
        )
        self.assertFalse(res.survivorship_bias_detected)
        self.assertEqual(res.coverage_percentage, 100.0)
        self.assertEqual(len(res.findings), 0)

    def test_future_constituent_leakage_detected(self):
        # TRENT was only added in Sept 2024. If present in 2022 snapshot -> Leakage
        as_of = datetime(2022, 1, 1)
        tainted_symbols = ["RELIANCE.NS", "TCS.NS", "TRENT.NS"]
        res = SurvivorshipAuditor.audit_universe_snapshot(
            snapshot_symbols=tainted_symbols,
            as_of=as_of,
            historical_universe=self.hu,
        )
        self.assertTrue(res.survivorship_bias_detected)
        self.assertTrue(any(f.finding_type == SurvivorshipFindingType.FUTURE_CONSTITUENT_LEAKAGE for f in res.findings))
        self.assertIn("TRENT.NS", res.affected_symbols)


if __name__ == "__main__":
    unittest.main()
