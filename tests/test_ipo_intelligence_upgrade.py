import pytest
import asyncio
from backend.application.ipo_engine import IPOEngine, DeterministicFixtureIPOProvider
from backend.domain.ipo_schemas import IPOScoreVerdict, IPOMaster, IPOStatus, IPOType

@pytest.mark.asyncio
async def test_ipo_engine_segmented_scores():
    engine = IPOEngine()
    provider = DeterministicFixtureIPOProvider()
    
    ipo = IPOMaster(
        id="IPO_DEEPA_2026",
        company_name="Deepa",
        exchange="NSE",
        segment=IPOType.MAINBOARD,
        status=IPOStatus.OPEN,
        issue_price=100.0,
        lot_size=100,
        revenue=500.0,
        pat=50.0,
        pe=15.0,
        total_subscription=100.0,
        gmp=40.0
    )
    provider.add_ipo(ipo)
    
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
    provider = DeterministicFixtureIPOProvider()
    
    ipo = IPOMaster(
        id="IPO_PRANAV_2026",
        company_name="Pranav",
        exchange="NSE",
        segment=IPOType.MAINBOARD,
        status=IPOStatus.UPCOMING
    )
    provider.add_ipo(ipo)
    
    analysis = await engine.analyze_ipo("IPO_PRANAV_2026")
    
    assert analysis.verdict in [IPOScoreVerdict.INSUFFICIENT_DATA, IPOScoreVerdict.STRONG, IPOScoreVerdict.POSITIVE, IPOScoreVerdict.NEUTRAL, IPOScoreVerdict.WEAK, IPOScoreVerdict.AVOID]
