import pytest
from datetime import datetime, timezone
from backend.domain.schemas import MarketContext, EvidenceSummary, DataQualityStatus
from backend.domain.debate_schemas import DebateResult, BullCase, BearCase, RiskAssessment, DebateDecisionState
from backend.domain.research_synthesis_schemas import ResearchSynthesisResult
from backend.application.research_synthesis_engine import AIResearchSynthesisEngine
from backend.infrastructure.llm import MockLLMClient

@pytest.fixture
def mock_llm():
    fixed_res = ResearchSynthesisResult(
        symbol="TCS.NS",
        context_id="ctx-123",
        overall_summary="TCS shows strong margins but faces short-term headwinds.",
        bull_case_summary="Strong recurring revenue.",
        bear_case_summary="Margin compression risk.",
        risk_summary="Moderate risk.",
    )
    # The mock returns the exact model when generate_structured is called
    llm = MockLLMClient(fixed_response=fixed_res)
    return llm

@pytest.fixture
def engine(mock_llm):
    return AIResearchSynthesisEngine(llm_client=mock_llm)

@pytest.mark.asyncio
async def test_research_synthesis_generation_success(engine):
    ctx = MarketContext(symbol="TCS.NS", context_id="ctx-123", generated_at=datetime.now(timezone.utc), data_timestamp=datetime.now(timezone.utc), provider="MOCK", current_price=100.0, quality_status=DataQualityStatus.OK)
    ev_summary = EvidenceSummary(run_id="r1", context_id="ctx-123", symbol="TCS.NS")
    
    bull_case = BullCase(thesis_id="b1", context_id="ctx-123", symbol="TCS.NS", core_thesis="Bull thesis")
    bear_case = BearCase(thesis_id="be1", context_id="ctx-123", symbol="TCS.NS", attack_summary="Bear attack")
    risk_assessment = RiskAssessment(context_id="ctx-123", symbol="TCS.NS", risk_level="MODERATE")
    
    debate_res = DebateResult(debate_id="deb-1", context_id="ctx-123", symbol="TCS.NS", bull_case=bull_case, bear_case=bear_case, risk_assessment=risk_assessment)
    
    result = await engine.synthesize(ctx, ev_summary, debate_res)
    
    assert result.symbol == "TCS.NS"
    assert result.is_unavailable is False
    assert result.overall_summary == "TCS shows strong margins but faces short-term headwinds."

@pytest.mark.asyncio
async def test_missing_market_context(engine):
    ev_summary = EvidenceSummary(run_id="r1", context_id="ctx-123", symbol="TCS.NS")
    debate_res = DebateResult(debate_id="deb-1", context_id="ctx-123", symbol="TCS.NS")
    
    result = await engine.synthesize(None, ev_summary, debate_res)
    assert result.is_unavailable is True
    assert "MarketContext UNAVAILABLE" in result.data_limitations
    assert result.symbol == "UNKNOWN"

@pytest.mark.asyncio
async def test_unavailable_market_context(engine):
    ctx = MarketContext(symbol="TCS.NS", context_id="ctx-123", generated_at=datetime.now(timezone.utc), data_timestamp=datetime.now(timezone.utc), provider="MOCK", current_price=100.0, quality_status=DataQualityStatus.CRITICAL_FAILURE)
    ev_summary = EvidenceSummary(run_id="r1", context_id="ctx-123", symbol="TCS.NS")
    debate_res = DebateResult(debate_id="deb-1", context_id="ctx-123", symbol="TCS.NS")
    
    result = await engine.synthesize(ctx, ev_summary, debate_res)
    assert result.is_unavailable is True
    assert "MarketContext UNAVAILABLE" in result.data_limitations
    assert result.symbol == "TCS.NS"

@pytest.mark.asyncio
async def test_missing_data_stale_data_handled(mock_llm):
    # If the LLM throws an error
    from backend.infrastructure.llm import LLMClientError
    class ErrorLLMClient:
        async def generate_structured(self, *args, **kwargs):
            raise LLMClientError("Provider failure")
    
    error_engine = AIResearchSynthesisEngine(llm_client=ErrorLLMClient())
    ctx = MarketContext(symbol="TCS.NS", context_id="ctx-123", generated_at=datetime.now(timezone.utc), data_timestamp=datetime.now(timezone.utc), provider="MOCK", current_price=100.0, status="AVAILABLE")
    ev_summary = EvidenceSummary(run_id="r1", context_id="ctx-123", symbol="TCS.NS")
    debate_res = DebateResult(debate_id="deb-1", context_id="ctx-123", symbol="TCS.NS")
    
    result = await error_engine.synthesize(ctx, ev_summary, debate_res)
    assert result.is_unavailable is True
    assert any("LLM synthesis failed" in msg for msg in result.data_limitations)
