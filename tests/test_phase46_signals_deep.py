import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
import pandas as pd
from backend.application.opportunity_scanner_engine import OpportunityScannerEngine
from backend.domain.opportunity_scanner_schemas import (
    MarketDataState, OpportunityType, BreakoutStatus, ReversalStatus, VolumeStatus, GapStatus, TrendClassification, OpportunityDirection, MultiTimeframeAlignment
)
from backend.application.stock_analysis_engine import StrategyScore

def make_ohlcv(length=260, base=100.0, trend=0.0):
    # Generates a simple dataframe
    dates = pd.date_range(start='2020-01-01', periods=length, freq='B')
    return pd.DataFrame({
        'Open': [float(base + i*trend) for i in range(length)],
        'High': [float(base + i*trend + 2.0) for i in range(length)],
        'Low': [float(base + i*trend - 2.0) for i in range(length)],
        'Close': [float(base + i*trend + 1.0) for i in range(length)],
        'Volume': [1000.0 for _ in range(length)]
    }, dtype=float, index=dates)

@pytest.fixture
def engine():
    e = OpportunityScannerEngine()
    e.provider = MagicMock()
    e.provider.get_fundamentals = AsyncMock(return_value=None)
    
    # Mock fundamental stock analysis
    e.stock_engine = MagicMock()
    e.stock_engine._analyze_fundamental.return_value = StrategyScore(score=80.0, confidence=0.8, reasons=[])
    e.stock_engine._analyze_valuation.return_value = (StrategyScore(score=70.0, confidence=0.7, reasons=[]), "OK")
    
    e.gateway = MagicMock()
    e.gateway.get_latest_quote.return_value = None
    e.integrity_engine = MagicMock()
    e.integrity_engine.fail_closed_check.return_value = False
    return e

@pytest.mark.asyncio
async def test_historical_only(engine):
    # No live quote
    df = make_ohlcv()
    engine.provider.get_historical_ohlcv = AsyncMock(return_value=df)
    res = await engine.scan_single("TEST")
    assert res.market.data_quality == MarketDataState.HISTORICAL

@pytest.mark.asyncio
async def test_fresh_live_quote(engine):
    df = make_ohlcv()
    engine.provider.get_historical_ohlcv = AsyncMock(return_value=df)
    engine.gateway.get_latest_quote.return_value = {"last_traded_price": 105.0, "volume": 1000}
    engine.integrity_engine.fail_closed_check.return_value = True
    res = await engine.scan_single("TEST")
    assert res.market.data_quality == MarketDataState.LIVE
    assert res.market.ltp == 105.0

@pytest.mark.asyncio
async def test_stale_live_quote(engine):
    df = make_ohlcv()
    engine.provider.get_historical_ohlcv = AsyncMock(return_value=df)
    engine.gateway.get_latest_quote.return_value = {"last_traded_price": 105.0}
    engine.integrity_engine.fail_closed_check.return_value = False
    res = await engine.scan_single("TEST")
    assert res.market.data_quality == MarketDataState.STALE

@pytest.mark.asyncio
async def test_confirmed_breakout(engine):
    df = make_ohlcv()
    # High volume current tick, LTP > bollinger band
    engine.provider.get_historical_ohlcv = AsyncMock(return_value=df)
    engine.gateway.get_latest_quote.return_value = {"last_traded_price": 200.0, "volume": 5000}
    engine.integrity_engine.fail_closed_check.return_value = True
    res = await engine.scan_single("TEST")
    assert res.signals.breakout_signal == BreakoutStatus.CONFIRMED_BREAKOUT

@pytest.mark.asyncio
async def test_potential_breakout(engine):
    df = make_ohlcv()
    # Normal volume, LTP > bollinger band
    engine.provider.get_historical_ohlcv = AsyncMock(return_value=df)
    engine.gateway.get_latest_quote.return_value = {"last_traded_price": 200.0, "volume": 1000}
    engine.integrity_engine.fail_closed_check.return_value = True
    res = await engine.scan_single("TEST")
    assert res.signals.breakout_signal == BreakoutStatus.POTENTIAL_BREAKOUT

@pytest.mark.asyncio
async def test_failed_breakout(engine):
    df = make_ohlcv()
    # Intraday high > BB, but close/LTP < BB
    df.loc[df.index[-1], 'High'] = 300.0 
    df.loc[df.index[-1], 'Close'] = 100.0 
    engine.provider.get_historical_ohlcv = AsyncMock(return_value=df)
    res = await engine.scan_single("TEST")
    assert res.signals.breakout_signal == BreakoutStatus.FAILED_BREAKOUT

@pytest.mark.asyncio
async def test_gap_down(engine):
    df = make_ohlcv()
    df.loc[df.index[-1], 'Open'] = df.loc[df.index[-2], 'Close'] * 0.90
    engine.provider.get_historical_ohlcv = AsyncMock(return_value=df)
    res = await engine.scan_single("TEST")
    assert res.signals.gap_signal == GapStatus.LARGE_GAP
    assert res.signals.gap_direction == OpportunityDirection.BEARISH

@pytest.mark.asyncio
async def test_52w_high_shifted(engine):
    df = make_ohlcv(260)
    # The previous 252 days should have a max high. The current LTP breaks it.
    df['High'] = 100.0
    df.loc[df.index[100], 'High'] = 150.0 # Old 52w high
    df.loc[df.index[-1], 'High'] = 160.0
    df.loc[df.index[-1], 'Close'] = 155.0
    engine.provider.get_historical_ohlcv = AsyncMock(return_value=df)
    res = await engine.scan_single("TEST")
    assert res.signals.fifty_two_week_high_signal is True

@pytest.mark.asyncio
async def test_strong_uptrend(engine):
    df = make_ohlcv(260, trend=1.0) # strong trend
    engine.provider.get_historical_ohlcv = AsyncMock(return_value=df)
    res = await engine.scan_single("TEST")
    # In this dataset, LTP > EMA20 > SMA50 > SMA200
    assert res.technical.trend == TrendClassification.STRONG_UPTREND

@pytest.mark.asyncio
async def test_risk_reward(engine):
    df = make_ohlcv()
    engine.provider.get_historical_ohlcv = AsyncMock(return_value=df)
    res = await engine.scan_single("TEST")
    # Should calculate risk_reward since we generate pivot support/resistance
    if res.risk.stop_loss_reference and res.risk.target_reference:
        assert res.risk.risk_reward is not None

@pytest.mark.asyncio
async def test_mtf_alignment(engine):
    df = make_ohlcv(260, trend=1.0)
    engine.provider.get_historical_ohlcv = AsyncMock(return_value=df)
    res = await engine.scan_single("TEST")
    assert res.signals.multi_timeframe_alignment == MultiTimeframeAlignment.ALIGNED_BULLISH

@pytest.mark.asyncio
async def test_score_and_confidence(engine):
    df = make_ohlcv(260, trend=1.0)
    engine.provider.get_historical_ohlcv = AsyncMock(return_value=df)
    res = await engine.scan_single("TEST")
    assert res.opportunity.confidence > 0.0
    assert res.opportunity.opportunity_score > 0.0
    
    # Missing fundamental lowers score
    engine.stock_engine._analyze_fundamental.return_value = StrategyScore(score=0.0, confidence=0.0, reasons=[])
    res_no_f = await engine.scan_single("TEST")
    assert res_no_f.opportunity.opportunity_score < res.opportunity.opportunity_score
    assert res_no_f.opportunity.confidence < res.opportunity.confidence
