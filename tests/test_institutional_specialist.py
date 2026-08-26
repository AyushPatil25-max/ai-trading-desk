"""
Tests for InstitutionalSpecialist - Phase 3.10
"""

import unittest
from datetime import datetime, timezone, timedelta
import asyncio
from unittest.mock import MagicMock, AsyncMock

from backend.domain.schemas import (
    MarketContext, AgentInput, AgentState, AgentOutput,
    InstitutionalFlowObservation, InvestorType, OwnershipObservation, HolderType,
    DeliveryObservation, InstitutionalDeal, DealType,
    SourceTier, VerificationStatus, DataQuality,
    InstitutionalRegime, InstitutionalStrength, FIIRegime, DIIRegime, OwnershipRegime, PromoterRisk,
    InstitutionalPayload
)
from backend.specialists.institutional_specialist import InstitutionalSpecialist, _InstitutionalLLMResponse
from backend.specialists.technical_specialist import TechnicalSpecialist
from backend.specialists.momentum_specialist import MomentumSpecialist
from backend.specialists.quant_specialist import QuantSpecialist
from backend.specialists.fundamental_specialist import FundamentalSpecialist
from backend.specialists.valuation_specialist import ValuationSpecialist
from backend.specialists.sector_specialist import SectorSpecialist
from backend.specialists.macro_specialist import MacroSpecialist
from backend.specialists.news_specialist import NewsSpecialist
from backend.application.agent_registry import AgentRegistry, AgentRegistrationError
from backend.application.specialist_orchestrator import SpecialistOrchestrator, RetryPolicy

class MockLLMClient:
    def __init__(self, fixed_response=None, should_raise=None):
        self.fixed_response = fixed_response
        self.should_raise = should_raise
        self.model_name = "mock-llm-3.1"

    async def generate_structured(self, system_prompt, user_prompt, response_model):
        if self.should_raise:
            raise self.should_raise
        return self.fixed_response

def _make_context(empty=False):
    now = datetime.now(timezone.utc)
    past = now - timedelta(days=90)
    
    inst_data = []
    own_data = []
    del_data = []
    deal_data = []
    fund_data = {}
    news_data = {}
    
    if not empty:
        inst_data = [
            InstitutionalFlowObservation(
                symbol="RELIANCE.NS", investor_type=InvestorType.FII,
                buy_value=150.0, sell_value=50.0, net_value=100.0,
                currency="INR", exchange="NSE", period="1D",
                observed_at=now, source="MOCK", source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL, context_id="ctx-inst-001"
            ),
            InstitutionalFlowObservation(
                symbol="RELIANCE.NS", investor_type=InvestorType.DII,
                buy_value=80.0, sell_value=120.0, net_value=-40.0,
                currency="INR", exchange="NSE", period="1D",
                observed_at=now, source="MOCK", source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL, context_id="ctx-inst-001"
            )
        ]
        own_data = [
            OwnershipObservation(
                symbol="RELIANCE.NS", holder_type=HolderType.PROMOTER,
                ownership_percentage=50.7, period="Q2",
                source="MOCK", source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
                report_date=past, context_id="ctx-inst-001"
            ),
            OwnershipObservation(
                symbol="RELIANCE.NS", holder_type=HolderType.PROMOTER,
                ownership_percentage=51.2, period="Q3",
                source="MOCK", source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
                report_date=now, context_id="ctx-inst-001"
            )
        ]
        del_data = [
            DeliveryObservation(
                symbol="RELIANCE.NS", trade_date=now,
                traded_quantity=1000000, delivery_quantity=620000,
                delivery_percentage=62.0, source="MOCK",
                source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
                observed_at=now, context_id="ctx-inst-001"
            )
        ]
        deal_data = [
            InstitutionalDeal(
                symbol="RELIANCE.NS", exchange="NSE", deal_type=DealType.BULK,
                participant="MOCK_PARTICIPANT", buy_sell="BUY", quantity=1000, price=3000.0,
                value=3000000.0, trade_date=now, source="MOCK",
                source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL, context_id="ctx-inst-001"
            )
        ]
        
        fund_data = {}
        news_data = {}

    ctx = MarketContext(
        context_id="ctx-inst-001",
        symbol="RELIANCE.NS",
        data_timestamp=now,
        provider="Mock",
        current_price=3000.0,
        institutional_data=inst_data,
        ownership_data=own_data,
        deal_data=deal_data,
        delivery_data=del_data,
        fundamental_data=fund_data,
        news_data=news_data
    )
    return ctx

def _make_llm_response():
    return _InstitutionalLLMResponse(
        institutional_regime=InstitutionalRegime.ACCUMULATION,
        institutional_strength=InstitutionalStrength.STRONG,
        fii_regime=FIIRegime.BULLISH,
        dii_regime=DIIRegime.BEARISH,
        ownership_regime=OwnershipRegime.IMPROVING,
        promoter_risk=PromoterRisk.LOW,
        catalysts=["Strong FII buying"],
        headwinds=[],
        risks=["DII selling pressure"],
        assumptions=["FII flows will persist"],
        invalidation_conditions=["FII net turns negative"],
        conclusion="Strong institutional accumulation driven by FIIs.",
        confidence=0.9
    )

class TestInstitutionalSpecialist(unittest.IsolatedAsyncioTestCase):
    
    async def test_1_creation(self):
        spec = InstitutionalSpecialist()
        self.assertEqual(spec.name, "InstitutionalSpecialist")

    async def test_2_registry(self):
        reg = AgentRegistry()
        spec = InstitutionalSpecialist()
        reg.register(spec)
        self.assertIn("InstitutionalSpecialist", reg.list_agents())

    async def test_3_valid_execution(self):
        llm = MockLLMClient(fixed_response=_make_llm_response())
        spec = InstitutionalSpecialist(llm)
        inp = AgentInput(symbol="RELIANCE.NS", market_context=_make_context())
        out = await spec.execute(inp)
        
        self.assertEqual(out.status, AgentState.SUCCESS)
        payload = InstitutionalPayload(**out.raw_data)
        self.assertEqual(payload.institutional_regime, InstitutionalRegime.ACCUMULATION)

    async def test_4_deterministic_flows(self):
        llm = MockLLMClient(fixed_response=_make_llm_response())
        spec = InstitutionalSpecialist(llm)
        out = await spec.execute(AgentInput(symbol="RELIANCE.NS", market_context=_make_context()))
        payload = InstitutionalPayload(**out.raw_data)
        
        self.assertEqual(payload.fii_net_flow, 100.0)
        self.assertEqual(payload.dii_net_flow, -40.0)
        self.assertEqual(payload.combined_net_flow, 60.0)
        
    async def test_7_ownership_change(self):
        llm = MockLLMClient(fixed_response=_make_llm_response())
        spec = InstitutionalSpecialist(llm)
        out = await spec.execute(AgentInput(symbol="RELIANCE.NS", market_context=_make_context()))
        payload = InstitutionalPayload(**out.raw_data)
        
        self.assertEqual(payload.promoter_ownership, 51.2)
        self.assertEqual(round(payload.promoter_ownership_change, 4), 0.5)

    async def test_9_delivery_evidence(self):
        llm = MockLLMClient(fixed_response=_make_llm_response())
        spec = InstitutionalSpecialist(llm)
        out = await spec.execute(AgentInput(symbol="RELIANCE.NS", market_context=_make_context()))
        payload = InstitutionalPayload(**out.raw_data)
        
        self.assertEqual(payload.delivery_percentage, 62.0)
        
    async def test_10_bulk_deal_evidence(self):
        llm = MockLLMClient(fixed_response=_make_llm_response())
        spec = InstitutionalSpecialist(llm)
        out = await spec.execute(AgentInput(symbol="RELIANCE.NS", market_context=_make_context()))
        payload = InstitutionalPayload(**out.raw_data)
        
        self.assertEqual(payload.bulk_deal_count, 1)

    async def test_16_context_id_propagation(self):
        llm = MockLLMClient(fixed_response=_make_llm_response())
        spec = InstitutionalSpecialist(llm)
        out = await spec.execute(AgentInput(symbol="RELIANCE.NS", market_context=_make_context()))
        payload = InstitutionalPayload(**out.raw_data)
        
        for ev in payload.evidence:
            self.assertEqual(ev.context_id, "ctx-inst-001")

    async def test_17_missing_data(self):
        llm = MockLLMClient(fixed_response=_make_llm_response())
        spec = InstitutionalSpecialist(llm)
        out = await spec.execute(AgentInput(symbol="RELIANCE.NS", market_context=_make_context(empty=True)))
        
        self.assertEqual(out.status, AgentState.DEGRADED)
        payload = InstitutionalPayload(**out.raw_data)
        self.assertEqual(payload.institutional_regime, InstitutionalRegime.UNKNOWN)

    async def test_20_llm_parse_error(self):
        from backend.infrastructure.llm import LLMParseError
        llm = MockLLMClient(should_raise=LLMParseError("Bad JSON"))
        spec = InstitutionalSpecialist(llm)
        out = await spec.execute(AgentInput(symbol="RELIANCE.NS", market_context=_make_context()))
        self.assertEqual(out.status, AgentState.FAILED)

    async def test_23_nine_way_parallel_orchestration(self):
        ctx = _make_context()
        now = ctx.data_timestamp
        llm = MockLLMClient()
        
        tech = TechnicalSpecialist(llm)
        mom = MomentumSpecialist(llm)
        quant = QuantSpecialist(llm)
        fund = FundamentalSpecialist(llm)
        
        tech.execute = AsyncMock(return_value=AgentOutput(agent_name="TechnicalSpecialist", version="1", model="mock", status=AgentState.SUCCESS, context=ctx, raw_data={}, summary="OK", data_timestamp=now, confidence=0.9, conclusion="OK"))
        mom.execute = AsyncMock(return_value=AgentOutput(agent_name="MomentumSpecialist", version="1", model="mock", status=AgentState.SUCCESS, context=ctx, raw_data={}, summary="OK", data_timestamp=now, confidence=0.9, conclusion="OK"))
        quant.execute = AsyncMock(return_value=AgentOutput(agent_name="QuantSpecialist", version="1", model="mock", status=AgentState.SUCCESS, context=ctx, raw_data={}, summary="OK", data_timestamp=now, confidence=0.9, conclusion="OK"))
        fund.execute = AsyncMock(return_value=AgentOutput(agent_name="FundamentalSpecialist", version="1", model="mock", status=AgentState.SUCCESS, context=ctx, raw_data={}, summary="OK", data_timestamp=now, confidence=0.9, conclusion="OK"))
        
        val = ValuationSpecialist(llm_client=MockLLMClient())
        val.execute = AsyncMock(return_value=AgentOutput(agent_name="ValuationSpecialist", version="1", model="mock", status=AgentState.SUCCESS, context=ctx, raw_data={}, summary="OK", data_timestamp=now, confidence=0.9, conclusion="OK"))
        
        sec = SectorSpecialist(llm_client=MockLLMClient())
        sec.execute = AsyncMock(return_value=AgentOutput(agent_name="SectorSpecialist", version="1", model="mock", status=AgentState.SUCCESS, context=ctx, raw_data={}, summary="OK", data_timestamp=now, confidence=0.9, conclusion="OK"))
        
        macro = MacroSpecialist(llm_client=MockLLMClient())
        macro.execute = AsyncMock(return_value=AgentOutput(agent_name="MacroSpecialist", version="1", model="mock", status=AgentState.SUCCESS, context=ctx, raw_data={}, summary="OK", data_timestamp=now, confidence=0.9, conclusion="OK"))
        
        news = NewsSpecialist(llm_client=MockLLMClient())
        news.execute = AsyncMock(return_value=AgentOutput(agent_name="NewsSpecialist", version="1", model="mock", status=AgentState.SUCCESS, context=ctx, raw_data={}, summary="OK", data_timestamp=now, confidence=0.9, conclusion="OK"))
        
        inst = InstitutionalSpecialist(llm_client=MockLLMClient(fixed_response=_make_llm_response()))

        orchestrator = SpecialistOrchestrator(
            max_concurrency=9,
            agent_timeout_seconds=5.0,
            retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0),
        )
        
        results = await orchestrator.run(
            [tech, mom, quant, fund, val, sec, macro, news, inst],
            ctx
        )
        self.assertEqual(results.total_agents, 9)
        self.assertTrue(all(r.status in [AgentState.SUCCESS, AgentState.DEGRADED] for r in results.records))

if __name__ == "__main__":
    unittest.main()
