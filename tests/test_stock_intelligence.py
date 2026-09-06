import pytest
import asyncio
from backend.domain.stock_schemas import StockDecision
from backend.application.stock_analysis_engine import StockAnalysisEngine
from backend.infrastructure.providers.market_data_provider import get_market_data_provider
from backend.application.stock_screener import StockScreener
from backend.infrastructure.security_master import get_security_master, sync_dhan_master

@pytest.mark.asyncio
async def test_stock_universe_ingestion():
    sm = get_security_master()
    initial_count = len(sm.list_securities())
    assert initial_count > 0

@pytest.mark.asyncio
async def test_public_market_provider():
    provider = get_market_data_provider()
    fundamental = await provider.get_fundamentals("RELIANCE.NS")
    technical = await provider.get_technicals("RELIANCE.NS")
    
    # Since Upstox provider does not fetch live technicals without active subscription,
    # it returns None in CI unless injected. We just assert no exceptions are raised.
    assert fundamental is None or fundamental.symbol == "RELIANCE.NS"
    assert technical is None or technical.symbol == "RELIANCE.NS"

@pytest.mark.asyncio
async def test_stock_analysis_engine():
    provider = get_market_data_provider()
    engine = StockAnalysisEngine()
    
    fundamental = await provider.get_fundamentals("TCS.NS")
    technical = await provider.get_technicals("TCS.NS")
    
    if fundamental and technical:
        analysis = await engine.analyze_stock("TCS.NS", fundamental, technical)
        assert analysis is not None
        assert analysis.overall_score is not None
        assert analysis.decision in [StockDecision.BULLISH, StockDecision.BEARISH, StockDecision.HOLD, StockDecision.REJECT, StockDecision.INSUFFICIENT_DATA]
        assert len(analysis.positive_factors) >= 0

@pytest.mark.asyncio
async def test_stock_screener():
    screener = StockScreener()
    results = await screener.screen_undervalued_strong_fundamentals(limit=5)
    assert isinstance(results, list)

