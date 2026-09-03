import pytest
import asyncio
from backend.application.ipo_engine import IPOEngine
from backend.domain.ipo_schemas import IPOScoreVerdict

@pytest.mark.asyncio
async def test_ipo_engine_segmented_scores():
    engine = IPOEngine()
    await engine.trigger_refresh()
    
    # IPO_DEEPA_2026 is injected from the mock provider
    analysis = await engine.analyze_ipo("IPO_DEEPA_2026")
    
    assert analysis is not None
    assert analysis.verdict is not None
    assert analysis.fundamental_score >= 0 or analysis.fundamental_score < 0
    assert analysis.valuation_score >= 0 or analysis.valuation_score < 0
    assert analysis.gmp_score >= 0 or analysis.gmp_score < 0
    assert analysis.subscription_score >= 0 or analysis.subscription_score < 0

@pytest.mark.asyncio
async def test_ipo_engine_missing_data():
    engine = IPOEngine()
    await engine.trigger_refresh()
    
    # PRANAV is upcoming, might lack full data or GMP
    analysis = await engine.analyze_ipo("IPO_PRANAV_2026")
    
    assert analysis.verdict in [IPOScoreVerdict.INSUFFICIENT_DATA, IPOScoreVerdict.STRONG, IPOScoreVerdict.POSITIVE, IPOScoreVerdict.NEUTRAL, IPOScoreVerdict.WEAK, IPOScoreVerdict.AVOID]
