import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from backend.application.opportunity_scanner_engine import OpportunityScannerEngine
from backend.domain.opportunity_scanner_schemas import (
    MarketDataState, OpportunityType, BreakoutStatus
)

@pytest.mark.asyncio
async def test_scanner_insufficient_data():
    engine = OpportunityScannerEngine()
    engine.provider = MagicMock()
    # Mock short data
    engine.provider.get_historical_ohlcv = AsyncMock(return_value=None)
    engine.provider.get_technicals = AsyncMock(return_value=None)
    engine.provider.get_fundamentals = AsyncMock(return_value=None)
    
    result = await engine.scan_single("MISSING")
    assert result is not None
    assert result.market.data_quality == MarketDataState.INSUFFICIENT_DATA

@pytest.mark.asyncio
async def test_scanner_batch():
    engine = OpportunityScannerEngine()
    engine.provider = MagicMock()
    engine.provider.get_historical_ohlcv = AsyncMock(return_value=None)
    engine.provider.get_technicals = AsyncMock(return_value=None)
    engine.provider.get_fundamentals = AsyncMock(return_value=None)
    
    res = await engine.scan_symbols(["A", "B"])
    assert res.total_scanned == 2
    assert len(res.unavailable_symbols) == 0  # No exception, just INSUFFICIENT_DATA result
