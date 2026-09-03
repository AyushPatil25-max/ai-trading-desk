import unittest
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock
from backend.adapters.legacy_agents import TechnicalAgentAdapter, RiskAgentAdapter
from backend.domain.schemas import AgentInput, MarketContext
from backend.agents.technical_agent import TechnicalAnalysis
from backend.agents.risk_agent import RiskAssessment

class TestLegacyAdapters(unittest.IsolatedAsyncioTestCase):
    @patch('backend.adapters.legacy_agents.run_technical_agent', new_callable=AsyncMock)
    async def test_technical_adapter_success(self, mock_run):
        mock_run.return_value = TechnicalAnalysis(
            symbol="TCS.NS",
            trend="BULLISH",
            setup="BREAKOUT",
            technical_score=8.0,
            confirmation=True
        )
        
        adapter = TechnicalAgentAdapter()
        ctx = MarketContext(
            context_id="test-123",
            symbol="TCS.NS", 
            current_price=100.0, 
            provider="test",
            data_timestamp=datetime.now(timezone.utc),
            technical_indicators={}
        )
        input_data = AgentInput(symbol="TCS.NS", market_context=ctx)
        
        output = await adapter.execute(input_data)
        
        self.assertEqual(output.status, "SUCCESS")
        self.assertEqual(output.agent_name, "TechnicalAgent")
        self.assertEqual(output.confidence, 0.8)
        self.assertEqual(output.conclusion, "BULLISH - BREAKOUT")
        self.assertEqual(output.raw_data["technical_score"], 8.0)

    @patch('backend.adapters.legacy_agents.run_risk_agent', new_callable=AsyncMock)
    async def test_risk_adapter_success(self, mock_run):
        mock_run.return_value = RiskAssessment(
            symbol="TCS.NS",
            risk_level="MEDIUM",
            max_position_size_pct=10.0,
            stop_loss_pct=2.5,
            risk_summary="Strong setup."
        )
        
        adapter = RiskAgentAdapter()
        ctx = MarketContext(
            context_id="test-123",
            symbol="TCS.NS", 
            current_price=100.0, 
            provider="test",
            data_timestamp=datetime.now(timezone.utc),
            technical_indicators={}
        )
        input_data = AgentInput(symbol="TCS.NS", market_context=ctx, additional_data={"technical_score": 8.0})
        
        output = await adapter.execute(input_data)
        
        self.assertEqual(output.status, "SUCCESS")
        self.assertEqual(output.agent_name, "RiskAgent")
        self.assertEqual(output.conclusion, "MEDIUM")
        self.assertEqual(output.raw_data["risk_level"], "MEDIUM")
