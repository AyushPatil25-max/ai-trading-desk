import pytest
from datetime import datetime, timezone
import asyncio

from backend.domain.stock_comparison_schemas import StockComparisonRequest, StockComparisonResult
from backend.application.stock_comparison_engine import StockComparisonEngine
from backend.application.context_service import ContextService
from backend.domain.schemas import MarketContext, DataQualityStatus

class MockContextService(ContextService):
    def __init__(self):
        pass
        
    async def get_market_context(self, symbol: str, window=None) -> MarketContext:
        kw = dict(
            symbol=symbol,
            context_id=f"ctx-{symbol}",
            generated_at=datetime.now(timezone.utc),
            data_timestamp=datetime.now(timezone.utc),
            provider="MOCK",
            current_price=100.0,
            quality_status=DataQualityStatus.OK
        )
        
        if symbol == "TCS.NS":
            kw.update(
                current_price=3500.0,
                technical_indicators={"rsi_14": 55.0, "sma_200": 3400.0},
                fundamental_data={"pe_ratio": 25.0, "roe": 40.0}
            )
        elif symbol == "INFY.NS":
            kw.update(
                current_price=1500.0,
                technical_indicators={"rsi_14": 30.0, "sma_200": 1600.0},
                fundamental_data={"pe_ratio": 22.0, "roe": 30.0}
            )
        elif symbol == "STALE.NS":
            kw.update(current_price=100.0, quality_status=DataQualityStatus.DEGRADED)
        elif symbol == "BROKEN.NS":
            kw.update(current_price=0.0, quality_status=DataQualityStatus.CRITICAL_FAILURE)
            
        return MarketContext(**kw)

@pytest.fixture
def comp_engine():
    return StockComparisonEngine(context_service=MockContextService())

@pytest.mark.asyncio
async def test_two_stock_comparison(comp_engine):
    req = StockComparisonRequest(
        symbols=["TCS.NS", "INFY.NS"],
        metrics=["current_price", "fundamental.pe_ratio"]
    )
    
    resp = await comp_engine.compare_securities(req)
    
    assert len(resp.comparisons) == 2
    assert len(resp.relative_observations) == 2
    
    # Verify TCS price
    tcs = next(c for c in resp.comparisons if c.symbol == "TCS.NS")
    assert tcs.metrics["current_price"].value == 3500.0
    assert tcs.metrics["fundamental.pe_ratio"].value == 25.0
    
    # Verify INFY price
    infy = next(c for c in resp.comparisons if c.symbol == "INFY.NS")
    assert infy.metrics["current_price"].value == 1500.0
    
    # Verify relative observation
    price_obs = next(o for o in resp.relative_observations if o.metric == "current_price")
    assert price_obs.is_comparable is True
    assert price_obs.winner_symbol == "TCS.NS"
    assert "2000.00" in price_obs.observation

@pytest.mark.asyncio
async def test_comparison_unavailable_metric(comp_engine):
    req = StockComparisonRequest(
        symbols=["TCS.NS", "INFY.NS"],
        metrics=["fundamental.unknown_metric"]
    )
    resp = await comp_engine.compare_securities(req)
    
    for comp in resp.comparisons:
        assert comp.metrics["fundamental.unknown_metric"].is_available is False
        assert comp.metrics["fundamental.unknown_metric"].value is None
        
    obs = resp.relative_observations[0]
    assert obs.is_comparable is False
    assert "Incomparable" in obs.observation

@pytest.mark.asyncio
async def test_comparison_critical_failure(comp_engine):
    req = StockComparisonRequest(
        symbols=["TCS.NS", "BROKEN.NS"],
        metrics=["current_price"]
    )
    resp = await comp_engine.compare_securities(req)
    
    broken = next(c for c in resp.comparisons if c.symbol == "BROKEN.NS")
    assert broken.data_quality == DataQualityStatus.CRITICAL_FAILURE
    assert broken.metrics["current_price"].is_available is False
    
    tcs = next(c for c in resp.comparisons if c.symbol == "TCS.NS")
    assert tcs.metrics["current_price"].is_available is True
    
    # Observation should be incomparable since only one valid value
    obs = resp.relative_observations[0]
    assert obs.is_comparable is False

@pytest.mark.asyncio
async def test_empty_request(comp_engine):
    with pytest.raises(ValueError):
        req = StockComparisonRequest(symbols=[], metrics=["current_price"])
        await comp_engine.compare_securities(req)

@pytest.mark.asyncio
async def test_excessive_request(comp_engine):
    with pytest.raises(ValueError):
        req = StockComparisonRequest(symbols=["SYM1"] * 11, metrics=["current_price"])
        await comp_engine.compare_securities(req)
