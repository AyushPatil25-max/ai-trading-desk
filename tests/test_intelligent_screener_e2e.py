import pytest
from datetime import datetime, timezone
import asyncio

from backend.domain.intelligent_screener_schemas import (
    ScreenerRequest, FilterGroup, FilterCriterion, LogicalOperator, ScreenerOperator
)
from backend.application.intelligent_screener_engine import IntelligentScreenerEngine
from backend.application.context_service import ContextService
from backend.domain.schemas import MarketContext, DataQualityStatus

# Mock Context Service
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

# Mock Universe Manager
class MockUniverse:
    def get_universe(self, utype):
        class MockConst:
            def __init__(self, symbol):
                self.symbol = symbol
        return [MockConst("TCS.NS"), MockConst("INFY.NS"), MockConst("STALE.NS"), MockConst("BROKEN.NS"), MockConst("MISSING.NS")]

class MockHistoricalUniverse:
    def get_universe_symbols(self, utype):
        if utype == "MOCK":
            return ["TCS.NS", "INFY.NS", "STALE.NS", "BROKEN.NS", "MISSING.NS"]
        return []

@pytest.fixture
def screener_engine():
    engine = IntelligentScreenerEngine(context_service=MockContextService())
    engine.universe_manager = MockUniverse()
    engine.historical_universe = MockHistoricalUniverse()
    return engine

@pytest.mark.asyncio
async def test_screener_basic_match(screener_engine):
    req = ScreenerRequest(
        universe_type="MOCK",
        filters=FilterGroup(
            logical_operator=LogicalOperator.AND,
            criteria=[
                FilterCriterion(field="current_price", operator=ScreenerOperator.GT, value=2000.0),
                FilterCriterion(field="fundamental.roe", operator=ScreenerOperator.GT, value=35.0)
            ]
        ),
        sort_by="current_price",
        sort_descending=True
    )
    
    resp = await screener_engine.execute_screen(req)
    assert resp.total_evaluated == 5
    assert resp.total_matches == 1
    assert resp.matches[0].symbol == "TCS.NS"
    assert resp.matches[0].rank_score == 3500.0

@pytest.mark.asyncio
async def test_screener_or_logic_and_missing_data(screener_engine):
    # INFY matches RSI < 40, TCS doesn't. Both should fail if we require ROE > 50 (which neither has)
    req = ScreenerRequest(
        universe_type="MOCK",
        filters=FilterGroup(
            logical_operator=LogicalOperator.OR,
            criteria=[
                FilterCriterion(field="technical.rsi_14", operator=ScreenerOperator.LT, value=40.0),
                FilterCriterion(field="fundamental.pe_ratio", operator=ScreenerOperator.LT, value=20.0)
            ]
        )
    )
    
    resp = await screener_engine.execute_screen(req)
    # INFY matches because RSI < 40 (30.0 < 40.0)
    assert resp.total_matches == 1
    assert resp.matches[0].symbol == "INFY.NS"
    assert len(resp.matches[0].matched_criteria) == 1
    
@pytest.mark.asyncio
async def test_screener_unavailable_metric(screener_engine):
    req = ScreenerRequest(
        universe_type="MOCK",
        filters=FilterGroup(
            logical_operator=LogicalOperator.AND,
            criteria=[
                FilterCriterion(field="fundamental.unknown_metric", operator=ScreenerOperator.GT, value=10.0)
            ]
        )
    )
    resp = await screener_engine.execute_screen(req)
    assert resp.total_matches == 0
    # Check that TCS.NS has unavailable criteria
    # But wait, execute_screen only returns MATCHES by default!
    # Let's adjust to check if we can inspect the raw result via _scan_symbol
    res = await screener_engine._scan_symbol("TCS.NS", req)
    assert res.is_match is False
    assert len(res.unavailable_criteria) == 1
    assert res.unavailable_criteria[0].field == "fundamental.unknown_metric"

@pytest.mark.asyncio
async def test_screener_critical_failure_exclusion(screener_engine):
    req = ScreenerRequest(
        universe_type="MOCK",
        filters=FilterGroup(
            logical_operator=LogicalOperator.AND,
            criteria=[
                FilterCriterion(field="current_price", operator=ScreenerOperator.GT, value=-1.0)
            ]
        )
    )
    resp = await screener_engine.execute_screen(req)
    # BROKEN.NS has CRITICAL_FAILURE, so it should be automatically skipped
    symbols = [m.symbol for m in resp.matches]
    assert "BROKEN.NS" not in symbols
    assert "TCS.NS" in symbols
    assert "INFY.NS" in symbols
    assert "STALE.NS" in symbols # STALE is evaluated but matched since current_price > -1.0
