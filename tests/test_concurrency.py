import time
import asyncio
import unittest
from unittest.mock import patch, AsyncMock
import httpx

from backend.main import app
from backend.agents.technical_agent import TechnicalAnalysis
from backend.agents.risk_agent import RiskAssessment

class TestConcurrency(unittest.IsolatedAsyncioTestCase):
    @patch("backend.application.orchestration.RiskAgentAdapter.execute", new_callable=AsyncMock)
    @patch("backend.application.orchestration.TechnicalAgentAdapter.execute", new_callable=AsyncMock)
    @patch("backend.infrastructure.data_providers.YFinanceProvider.get_market_context")
    async def test_concurrent_requests_do_not_block_event_loop(
        self, mock_market_data, mock_tech_agent, mock_risk_agent
    ):
        # Simulate synchronous, blocking network/CPU latency in market data fetching
        def slow_market_data(symbol: str, window=None):
            from backend.domain.schemas import MarketContext
            from datetime import datetime
            time.sleep(0.15)
            return MarketContext(
                context_id="test-123",
                symbol=symbol,
                current_price=3280.80,
                provider="test",
                data_timestamp=datetime.utcnow(),
                technical_indicators={
                    "20_day_high": 3271.60,
                    "ema20": 3188.45,
                    "ema50": 3133.12,
                    "rsi": 73.90
                }
            )

        mock_market_data.side_effect = slow_market_data
        mock_tech_agent.return_value = type('obj', (object,), {'raw_data': {'trend': 'BULLISH', 'setup': 'BREAKOUT', 'confirmation': True}})
        mock_risk_agent.return_value = type('obj', (object,), {'raw_data': {'risk_level': 'LOW'}})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            start_time = time.perf_counter()
            # Send 3 concurrent requests
            responses = await asyncio.gather(
                client.get("/api/analyze?symbol=TCS1.NS"),
                client.get("/api/analyze?symbol=TCS2.NS"),
                client.get("/api/analyze?symbol=TCS3.NS")
            )
            elapsed = time.perf_counter() - start_time

        # Verify all completed successfully
        for res in responses:
            self.assertEqual(res.status_code, 200)
            self.assertIn("APPROVED", res.json()["final_verdict"])

        # Sequential would take >= 3 * 0.15 = 0.45 seconds plus overhead.
        # Since asyncio.to_thread runs them across threadpool workers in parallel,
        # elapsed time should be under 0.80s even under high test suite CPU load.
        self.assertLess(elapsed, 0.80, f"Expected concurrent execution, but took {elapsed:.2f}s")
