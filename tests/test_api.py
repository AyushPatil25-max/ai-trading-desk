import unittest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from backend.main import app
from backend.agents.technical_agent import TechnicalAnalysis
from backend.agents.risk_agent import RiskAssessment

class TestAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_serve_dashboard(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("AI TRADING DESK", response.text)

    @patch("backend.application.orchestration.RiskAgentAdapter.execute", new_callable=AsyncMock)
    @patch("backend.application.orchestration.TechnicalAgentAdapter.execute", new_callable=AsyncMock)
    @patch("backend.infrastructure.providers.orchestrator.MultiSourceOrchestrator.get_market_context")
    def test_analyze_stock_approved(self, mock_market_data, mock_tech_agent, mock_risk_agent):
        from backend.domain.schemas import MarketContext
        from datetime import datetime, timezone
        mock_market_data.return_value = MarketContext(
            context_id="test-123",
            symbol="TCS.NS",
            current_price=3280.80,
            provider="test",
            data_timestamp=datetime.now(timezone.utc),
            technical_indicators={
                "20_day_high": 3271.60,
                "ema20": 3188.45,
                "ema50": 3133.12,
                "rsi": 73.90
            }
        )
        mock_tech_agent.return_value = type('obj', (object,), {'raw_data': {'trend': 'BULLISH', 'setup': 'BREAKOUT', 'confirmation': True}})
        mock_risk_agent.return_value = type('obj', (object,), {'raw_data': {'risk_level': 'LOW'}})

        response = self.client.get("/api/analyze?symbol=TCS.NS")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["symbol"], "TCS.NS")
        self.assertEqual(data["market_data"]["latest_close"], 3280.80)
        self.assertEqual(data["technical"]["trend"], "BULLISH")
        self.assertEqual(data["technical"]["confirmation"], True)
        self.assertEqual(data["risk"]["risk_level"], "LOW")
        self.assertEqual(data["final_verdict"], "APPROVED BULLISH BREAKOUT")

    @patch("backend.application.orchestration.RiskAgentAdapter.execute", new_callable=AsyncMock)
    @patch("backend.application.orchestration.TechnicalAgentAdapter.execute", new_callable=AsyncMock)
    @patch("backend.market_data.get_live_market_data")
    def test_analyze_stock_rejected_high_risk(self, mock_market_data, mock_tech_agent, mock_risk_agent):
        from backend.domain.schemas import MarketContext
        from datetime import datetime, timezone
        mock_market_data.return_value = MarketContext(
            context_id="test-123",
            symbol="TCS.NS",
            current_price=3280.80,
            provider="test",
            data_timestamp=datetime.now(timezone.utc),
            technical_indicators={
                "20_day_high": 3271.60,
                "ema20": 3188.45,
                "ema50": 3133.12,
                "rsi": 73.90
            }
        )
        mock_tech_agent.return_value = type('obj', (object,), {'raw_data': {'trend': 'BULLISH', 'setup': 'BREAKOUT', 'confirmation': True}})
        mock_risk_agent.return_value = type('obj', (object,), {'raw_data': {'risk_level': 'HIGH'}})

        response = self.client.get("/api/analyze?symbol=TCS.NS")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["final_verdict"], "REJECTED (High Risk or Unconfirmed Setup)")

    @patch("backend.infrastructure.data_providers.YFinanceProvider.get_market_context")
    def test_analyze_stock_market_data_failure(self, mock_market_data):
        from backend.domain.schemas import MarketContext, DataQualityStatus
        from datetime import datetime, timezone
        mock_market_data.return_value = MarketContext(
            context_id="test-123",
            symbol="INVALID",
            provider="test",
            data_timestamp=datetime.now(timezone.utc),
            current_price=0.0,
            quality_status=DataQualityStatus.CRITICAL_FAILURE,
            warnings=["Empty dataset returned from provider."]
        )
        response = self.client.get("/api/analyze?symbol=INVALID")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Critical Data Failure", response.json()["final_verdict"])
