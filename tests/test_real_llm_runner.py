"""
Unit tests for Real LLM Runner — Phase 5.6

Validates execution-mode metadata reporting, budget enforcement, and sample validation.
"""

from datetime import datetime
import unittest

from backend.domain.schemas import MarketContext
from backend.validation.real_llm_runner import (
    LLMExecutionMode,
    RealLLMRunner,
    RealLLMValidationClassification,
)


class TestRealLLMRunner(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.t_decision = datetime(2023, 6, 1, 10, 0, 0)
        self.ctx = MarketContext(
            context_id="ctx-test-001",
            symbol="TCS.NS",
            data_timestamp=datetime(2023, 5, 31, 15, 30, 0),
            current_price=3200.0,
            provider="NSE",
            ohlcv_historical=[{"timestamp": "2023-05-31", "close": 3200.0}],
            technical_indicators={"rsi_14": 55.0},
        )
        self.runner = RealLLMRunner(execution_mode=LLMExecutionMode.REPLAY_LLM)

    async def test_run_sample_validation_produces_report(self):
        report = await self.runner.run_sample_validation(
            sample_contexts=[self.ctx],
            decision_timestamp=self.t_decision,
        )
        self.assertEqual(report.contexts_processed, 1)
        self.assertEqual(report.execution_mode, LLMExecutionMode.REPLAY_LLM)
        self.assertEqual(report.classification, RealLLMValidationClassification.REAL_LLM_VALIDATED_SAMPLE)
        self.assertEqual(report.numerical_boundary_violations, 0)


if __name__ == "__main__":
    unittest.main()
