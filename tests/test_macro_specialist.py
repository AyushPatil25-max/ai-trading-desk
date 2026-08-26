import unittest
from datetime import datetime
from unittest.mock import MagicMock

from backend.domain.schemas import (
    MarketContext, HistoricalWindow, AgentState, AgentInput,
    MacroRegime, MacroRisk, RateRegime, InflationRegime, _MacroLLMResponse,
    MacroPayload
)
from backend.specialists.macro_specialist import MacroSpecialist
from backend.specialists.technical_specialist import TechnicalSpecialist
from backend.specialists.momentum_specialist import MomentumSpecialist
from backend.specialists.quant_specialist import QuantSpecialist
from backend.specialists.fundamental_specialist import FundamentalSpecialist
from backend.specialists.valuation_specialist import ValuationSpecialist
from backend.specialists.sector_specialist import SectorSpecialist
from backend.application.specialist_orchestrator import SpecialistOrchestrator
from backend.infrastructure.llm import MockLLMClient

class TestMacroSpecialist(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.base_context = MarketContext(
            context_id="test_macro_123",
            symbol="SPY",
            data_timestamp=datetime(2025, 1, 1),
            provider="test",
            historical_window=HistoricalWindow.RECENT,
            current_price=500.0,
            macro_data={
                "policy_rate": 5.25,
                "inflation_rate": 3.1,
                "treasury_10y": 4.1,
                "treasury_2y": 4.5,
                "gdp_growth": 2.5
            }
        )
        
        self.mock_llm_response = _MacroLLMResponse(
            macro_regime=MacroRegime.EXPANSIONARY,
            macro_risk=MacroRisk.MODERATE,
            rate_regime=RateRegime.HOLDING,
            inflation_regime=InflationRegime.STABLE,
            asset_impact="Positive for broad equities.",
            company_sensitivity="High sensitivity to interest rates.",
            conclusion="Constructive macro environment.",
            tailwinds=["GDP growth"],
            headwinds=["Inverted yield curve"],
            invalidation_conditions=["Inflation spikes above 4%"],
            risks=["Policy error"],
            assumptions=["Rates stay unchanged"],
            confidence=0.85
        )
        
        self.specialist = MacroSpecialist(llm_client=MockLLMClient(fixed_response=self.mock_llm_response))

    async def test_successful_analysis(self):
        output = await self.specialist.execute(AgentInput(symbol=self.base_context.symbol, market_context=self.base_context))
        self.assertEqual(output.status, AgentState.SUCCESS)
        self.assertEqual(output.confidence, 0.85)
        
        payload = MacroPayload(**output.raw_data)
        self.assertEqual(payload.macro_regime, MacroRegime.EXPANSIONARY)
        self.assertEqual(payload.rate_regime, RateRegime.HOLDING)
        
        available_evidence = [e for e in payload.evidence if e.available]
        self.assertEqual(len(available_evidence), 7) # policy, inflation, real, t10, t2, spread, gdp

    async def test_degraded_due_to_missing_data(self):
        ctx = self.base_context.model_copy(update={"macro_data": {}})
        output = await self.specialist.execute(AgentInput(symbol=ctx.symbol, market_context=ctx))
        
        self.assertEqual(output.status, AgentState.DEGRADED)
        self.assertEqual(output.confidence, 0.0)
        
        payload = MacroPayload(**output.raw_data)
        self.assertEqual(payload.macro_regime, MacroRegime.INDETERMINATE)

    async def test_7_way_orchestrator(self):
        # We need mock data for all specialists to not fail
        ctx = self.base_context.model_copy(update={
            "technical_indicators": {"sma_20": 100},
            "ohlcv_historical": [{"close": 100}, {"close": 110}],
            "fundamental_data": {"pe_ratio": 15},
            "sector_data": {"sector_name": "Tech"}
        })
        
        # We only really care that they don't crash and we get results.
        # Since we use MockLLMClient for all or they gracefully degrade, it's fine.
        mock_client = MockLLMClient(None)
        
        agents = [
            TechnicalSpecialist(mock_client),
            MomentumSpecialist(mock_client),
            QuantSpecialist(mock_client),
            FundamentalSpecialist(mock_client),
            ValuationSpecialist(mock_client),
            SectorSpecialist(mock_client),
            self.specialist
        ]
        
        orchestrator = SpecialistOrchestrator()
        results = await orchestrator.run(agents, ctx)
        
        self.assertEqual(len(results.outputs), 7)
        
        macro_outputs = [out for out in results.outputs if out.agent_name == "MacroSpecialist"]
        self.assertEqual(len(macro_outputs), 1)
        
        macro_result = macro_outputs[0]
        self.assertEqual(macro_result.status, AgentState.SUCCESS)

if __name__ == '__main__':
    unittest.main()
