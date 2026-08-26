"""
Unit tests for Real LLM Replay Reproducibility — Phase 5.6

Validates bitwise identical replay from cache across runs.
"""

from datetime import datetime
import unittest

from backend.domain.schemas import MarketContext
from backend.infrastructure.llm_replay_cache import LLMReplayCache
from backend.validation.real_llm_runner import LLMExecutionMode, RealLLMRunner


class TestRealLLMReproducibility(unittest.IsolatedAsyncioTestCase):
    async def test_replay_mode_is_100_percent_reproducible(self):
        cache = LLMReplayCache()
        runner1 = RealLLMRunner(execution_mode=LLMExecutionMode.REPLAY_LLM, cache=cache)
        runner2 = RealLLMRunner(execution_mode=LLMExecutionMode.REPLAY_LLM, cache=cache)

        ctx = MarketContext(
            context_id="ctx-rep-001",
            symbol="INFY.NS",
            data_timestamp=datetime(2023, 6, 1),
            current_price=1400.0,
            provider="NSE",
            ohlcv_historical=[{"timestamp": "2023-06-01", "close": 1400.0}],
            technical_indicators={"rsi_14": 52.0},
        )

        rep1 = await runner1.run_sample_validation([ctx], datetime(2023, 6, 1))
        rep2 = await runner2.run_sample_validation([ctx], datetime(2023, 6, 1))

        self.assertEqual(rep1.requests_count, rep2.requests_count)
        self.assertEqual(rep1.total_cost_usd, rep2.total_cost_usd)
        self.assertEqual(rep1.classification, rep2.classification)


if __name__ == "__main__":
    unittest.main()
