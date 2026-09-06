import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
import pandas as pd
from backend.application.opportunity_scanner_engine import OpportunityScannerEngine
from backend.domain.opportunity_scanner_schemas import (
    MarketDataState, OpportunityType, BreakoutStatus, ReversalStatus, VolumeStatus, GapStatus, TrendClassification, OpportunityDirection
)

def make_ohlcv(length=60, base=100.0, trend=0.0):
    return pd.DataFrame({
        'Open': [float(base + i*trend) for i in range(length)],
        'High': [float(base + i*trend + 2.0) for i in range(length)],
        'Low': [float(base + i*trend - 2.0) for i in range(length)],
        'Close': [float(base + i*trend + 1.0) for i in range(length)],
        'Volume': [1000.0 for _ in range(length)]
    }, dtype=float)

@pytest.fixture
def engine():
    e = OpportunityScannerEngine()
    e.provider = MagicMock()
    e.provider.get_fundamentals = AsyncMock(return_value=None)
    e.gateway = MagicMock()
    e.gateway.get_latest_quote.return_value = None
    e.integrity_engine = MagicMock()
    e.integrity_engine.fail_closed_check.return_value = False
    return e

@pytest.mark.asyncio
async def test_insufficient_data(engine):
    engine.provider.get_historical_ohlcv = AsyncMock(return_value=make_ohlcv(10))
    res = await engine.scan_single("TEST")
    assert res.market.data_quality == MarketDataState.INSUFFICIENT_DATA

@pytest.mark.asyncio
async def test_trend_uptrend(engine):
    df = make_ohlcv(210, trend=1.0)
    # the last close is ~309. SMA50 is approx 285. SMA200 is approx 210.
    # So LTP > SMA50 > SMA200, which is UPTREND
    engine.provider.get_historical_ohlcv = AsyncMock(return_value=df)
    res = await engine.scan_single("TEST")
    assert res.technical.trend == TrendClassification.STRONG_UPTREND
    

@pytest.mark.asyncio
async def test_volume_spike(engine):
    df = make_ohlcv(60)
    df.loc[59, 'Volume'] = 5000.0
    engine.provider.get_historical_ohlcv = AsyncMock(return_value=df)
    res = await engine.scan_single("TEST")
    assert res.signals.volume_spike_signal == VolumeStatus.EXTREME

@pytest.mark.asyncio
async def test_gap_up(engine):
    df = make_ohlcv(60)
    df.loc[59, 'Open'] = df.loc[58, 'Close'] * 1.05
    engine.provider.get_historical_ohlcv = AsyncMock(return_value=df)
    res = await engine.scan_single("TEST")
    assert res.signals.gap_signal == GapStatus.LARGE_GAP
    assert res.signals.gap_direction == OpportunityDirection.BULLISH

@pytest.mark.asyncio
async def test_52w_high(engine):
    df = make_ohlcv(260)
    df.loc[259, 'High'] = 200.0
    df.loc[259, 'Close'] = 199.0
    engine.provider.get_historical_ohlcv = AsyncMock(return_value=df)
    res = await engine.scan_single("TEST")
    assert res.signals.fifty_two_week_high_signal is True

@pytest.mark.asyncio
async def test_live_data_gateway(engine):
    df = make_ohlcv(60)
    engine.provider.get_historical_ohlcv = AsyncMock(return_value=df)
    engine.gateway.get_latest_quote.return_value = {"last_traded_price": 105.0}
    engine.integrity_engine.fail_closed_check.return_value = True
    res = await engine.scan_single("TEST")
    assert res.market.data_quality == MarketDataState.LIVE
    assert res.market.ltp == 105.0

@pytest.mark.asyncio
async def test_stale_data_gateway(engine):
    df = make_ohlcv(60)
    engine.provider.get_historical_ohlcv = AsyncMock(return_value=df)
    engine.gateway.get_latest_quote.return_value = {"last_traded_price": 105.0}
    engine.integrity_engine.fail_closed_check.return_value = False
    res = await engine.scan_single("TEST")
    assert res.market.data_quality == MarketDataState.STALE
