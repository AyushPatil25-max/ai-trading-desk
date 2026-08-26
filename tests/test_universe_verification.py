"""
Unit tests for Historical Universe Verification — Phase 5.5

Validates official circular verification, duplicate detection, and lifespan checks.
"""

from datetime import datetime
import unittest

from backend.scanner.historical_universe import HistoricalUniverse
from backend.validation.universe_verification import (
    UniverseVerificationStatus,
    UniverseVerifier,
)


class TestUniverseVerification(unittest.TestCase):
    def setUp(self):
        self.hu = HistoricalUniverse()

    def test_verify_historical_universe_passes_fully_verified(self):
        res = UniverseVerifier.verify_historical_universe(self.hu)
        self.assertEqual(res.verification_status, UniverseVerificationStatus.FULLY_VERIFIED)
        self.assertEqual(len(res.invalid_effective_dates), 0)
        self.assertEqual(len(res.duplicate_events), 0)
        self.assertEqual(res.coverage_percentage, 100.0)


if __name__ == "__main__":
    unittest.main()
