import os
import json
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from pydantic import ValidationError

from backend.agents.technical_agent import run_technical_agent, TechnicalAnalysis

class TestTechnicalAgent(unittest.IsolatedAsyncioTestCase):
    async def test_run_technical_agent_success(self):
        mock_data = {
            "latest_close": 3280.80,
            "20_day_high": 3271.60,
            "ema20": 3188.45,
            "ema50": 3133.12,
            "rsi": 73.90
        }
        mock_llm_response = {
            "symbol": "TCS.NS",
            "trend": "BULLISH",
            "setup": "BREAKOUT",
            "technical_score": 8.5,
            "confirmation": True
        }

        mock_completion = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = json.dumps(mock_llm_response)
        mock_completion.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)

        with patch.dict(os.environ, {"GROQ_API_KEY": "test_mock_key"}):
            with patch("backend.agents.technical_agent.AsyncGroq", return_value=mock_client):
                result = await run_technical_agent("TCS.NS", mock_data)

        self.assertIsInstance(result, TechnicalAnalysis)
        self.assertEqual(result.symbol, "TCS.NS")
        self.assertEqual(result.trend, "BULLISH")
        self.assertEqual(result.setup, "BREAKOUT")
        self.assertEqual(result.technical_score, 8.5)
        self.assertTrue(result.confirmation)

    async def test_run_technical_agent_missing_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as ctx:
                await run_technical_agent("TCS.NS", {})
            self.assertIn("GROQ_API_KEY is not set", str(ctx.exception))

    async def test_run_technical_agent_invalid_json(self):
        mock_completion = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "Invalid Non-JSON response"
        mock_completion.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)

        with patch.dict(os.environ, {"GROQ_API_KEY": "test_mock_key"}):
            with patch("backend.agents.technical_agent.AsyncGroq", return_value=mock_client):
                with self.assertRaises(ValidationError):
                    await run_technical_agent("TCS.NS", {})
