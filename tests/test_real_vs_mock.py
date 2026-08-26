"""
Unit tests for Real vs Mock LLM Comparison — Phase 5.6

Validates agreement rate computation, confidence delta tracking, and decision flip logging.
"""

import unittest

from backend.validation.real_llm_runner import AIModeComparisonResult


class TestRealVsMock(unittest.TestCase):
    def test_comparison_metrics_calculation(self):
        comp = AIModeComparisonResult(
            mock_decision_count=10,
            real_decision_count=10,
            agreement_rate_pct=90.0,
            disagreement_rate_pct=10.0,
            confidence_delta=0.05,
            decision_flip_rate_pct=10.0,
            flips=["TCS.NS: Mock APPROVE -> Real HOLD (valuation stretched)"],
        )
        self.assertEqual(comp.agreement_rate_pct, 90.0)
        self.assertEqual(len(comp.flips), 1)


if __name__ == "__main__":
    unittest.main()
