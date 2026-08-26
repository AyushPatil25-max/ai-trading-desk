import os
import json
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from pydantic import ValidationError

from backend.agents.risk_agent import run_risk_agent, RiskAssessment

class TestRiskAgent(unittest.IsolatedAsyncioTestCase):
    async def test_run_risk_agent_success(self):
        mock_data = {
            "latest_close": 3280.80,
            "20_day_high": 3271.60,
            "ema20": 3188.45,
            "ema50": 3133.12,
            "rsi": 73.90
        }
        mock_llm_response = {
            "symbol": "TCS.NS",
            "risk_level": "LOW",
            "max_position_size_pct": 10.0,
            "stop_loss_pct": 2.5,
            "risk_summary": "Strong momentum with tight consolidation."
        }

        mock_completion = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = json.dumps(mock_llm_response)
        mock_completion.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)

        with patch.dict(os.environ, {"GROQ_API_KEY": "test_mock_key"}):
            with patch("backend.agents.risk_agent.AsyncGroq", return_value=mock_client):
                result = await run_risk_agent("TCS.NS", mock_data, technical_score=8.5)

        self.assertIsInstance(result, RiskAssessment)
        self.assertEqual(result.symbol, "TCS.NS")
        self.assertEqual(result.risk_level, "LOW")
        self.assertEqual(result.max_position_size_pct, 10.0)
        self.assertEqual(result.stop_loss_pct, 2.5)
        self.assertEqual(result.risk_summary, "Strong momentum with tight consolidation.")

    async def test_run_risk_agent_missing_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as ctx:
                await run_risk_agent("TCS.NS", {}, technical_score=5.0)
            self.assertIn("GROQ_API_KEY is not set", str(ctx.exception))

    async def test_run_risk_agent_invalid_json(self):
        mock_completion = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "Invalid JSON string"
        mock_completion.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)

        with patch.dict(os.environ, {"GROQ_API_KEY": "test_mock_key"}):
            with patch("backend.agents.risk_agent.AsyncGroq", return_value=mock_client):
                with self.assertRaises(ValidationError):
                    await run_risk_agent("TCS.NS", {}, technical_score=5.0)
