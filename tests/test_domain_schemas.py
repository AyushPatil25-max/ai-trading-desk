import unittest
from datetime import datetime
from backend.domain.schemas import (
    MarketContext, AgentInput, AgentOutput, AgentState, AgentEvidence
)
from pydantic import ValidationError

class TestDomainSchemas(unittest.TestCase):
    def test_market_context_validation(self):
        ctx = MarketContext(
            context_id="test-123",
            symbol="TCS.NS",
            current_price=150.0,
            provider="test",
            data_timestamp=datetime.utcnow(),
            technical_indicators={"SMA": 140.0}
        )
        self.assertEqual(ctx.symbol, "TCS.NS")
        self.assertIsInstance(ctx.generated_at, datetime)
        
    def test_agent_output_strict_validation(self):
        output = AgentOutput(
            agent_name="TestAgent",
            version="1.0",
            model="llama-3",
            status=AgentState.SUCCESS,
            data_timestamp=datetime.utcnow(),
            confidence=0.8,
            conclusion="Buy"
        )
        self.assertEqual(output.status, AgentState.SUCCESS)
        
        with self.assertRaises(ValidationError):
            # confidence out of bounds
            AgentOutput(
                agent_name="TestAgent",
                version="1.0",
                model="llama-3",
                status=AgentState.SUCCESS,
                data_timestamp=datetime.utcnow(),
                confidence=1.5,
                conclusion="Buy"
            )
