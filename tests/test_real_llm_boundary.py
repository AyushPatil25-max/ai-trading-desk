"""
Unit tests for Specialist Numerical Boundary Enforcement — Phase 5.6

Validates that LLM qualitative interpretation cannot modify Python calculated numbers.
"""

from datetime import datetime
import unittest

from backend.validation.real_llm_runner import RealLLMRunner


class TestRealLLMBoundary(unittest.TestCase):
    def setUp(self):
        self.runner = RealLLMRunner()

    def test_numerical_boundary_satisfied_when_numbers_match(self):
        py_calc = {"rsi_14": 58.4, "ema_20": 3200.0}
        llm_out = {"rsi_14": 58.4, "sentiment": "BULLISH"}
        self.assertTrue(self.runner.verify_specialist_numerical_boundary(py_calc, llm_out))

    def test_numerical_boundary_fails_when_llm_mutates_calculated_number(self):
        py_calc = {"rsi_14": 58.4}
        llm_out = {"rsi_14": 75.0}  # LLM hallucinates different RSI
        self.assertFalse(self.runner.verify_specialist_numerical_boundary(py_calc, llm_out))


if __name__ == "__main__":
    unittest.main()
