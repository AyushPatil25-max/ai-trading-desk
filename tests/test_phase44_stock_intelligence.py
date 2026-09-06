import pytest
import asyncio
import pandas as pd
import numpy as np
from backend.domain.stock_schemas import StockDecision, StockFundamentalData, StockTechnicalData, StockAnalysisResult
from backend.application.stock_analysis_engine import StockAnalysisEngine
from backend.infrastructure.providers.market_data_provider import UpstoxMarketDataProvider
from backend.infrastructure.providers.technical_indicators import (
    calc_sma, calc_ema, calc_rsi, calc_macd, calc_atr, calc_adx,
    calc_bollinger_bands, calc_supertrend, calc_pivot_points
)

@pytest.fixture
def sample_ohlcv():
    dates = pd.date_range(start="2023-01-01", periods=100)
    
    # Generate deterministic synthetic data
    close = np.linspace(100, 200, 100)
    high = close + 5
    low = close - 5
    volume = np.linspace(1000, 5000, 100)
    
    df = pd.DataFrame({
        "Date": dates,
        "Close": close,
        "High": high,
        "Low": low,
        "Volume": volume
    })
    return df

@pytest.mark.asyncio
async def test_stock_analysis_missing_data():
    engine = StockAnalysisEngine()
    result = await engine.analyze_stock("UNKNOWN", None, None)
    
    assert result.decision == StockDecision.INSUFFICIENT_DATA
    assert result.data_status == "INSUFFICIENT"

@pytest.mark.asyncio
async def test_stock_analysis_with_data():
    engine = StockAnalysisEngine()
    
    fundamental = StockFundamentalData(symbol="RELIANCE.NS", pe=12.0, pb=1.5, roe=25.0)
    technical = StockTechnicalData(
        symbol="RELIANCE.NS", 
        current_price=100.0, 
        sma_200=90.0,
        sma_50=95.0,
        rsi_14=50.0, 
        macd=1.0, 
        macd_signal=0.5,
        macd_histogram=0.5,
        adx=30.0,
        plus_di=25.0,
        minus_di=15.0,
        supertrend=80.0
    )
    
    result = await engine.analyze_stock("RELIANCE.NS", fundamental, technical)
    
    assert result.decision != StockDecision.INSUFFICIENT_DATA
    assert result.fundamental_score > 0
    assert result.technical_score > 0
    assert result.trend_score > 0
    assert result.data_status == "COMPLETE"

def test_deterministic_sma(sample_ohlcv):
    sma_20 = calc_sma(sample_ohlcv["Close"], 20)
    assert not pd.isna(sma_20.iloc[-1])
    # Average of last 20 elements of linspace(100, 200, 100)
    # 100th element is 200. Elements are 191 to 200... actually 181 to 200
    assert np.isclose(sma_20.iloc[-1], np.mean(sample_ohlcv["Close"].iloc[-20:]))

def test_deterministic_rsi(sample_ohlcv):
    rsi = calc_rsi(sample_ohlcv["Close"], 14)
    # Since prices constantly go up, RSI should be 100
    assert np.isclose(rsi.iloc[-1], 100.0)

def test_deterministic_macd(sample_ohlcv):
    macd, signal, hist = calc_macd(sample_ohlcv["Close"])
    assert not pd.isna(macd.iloc[-1])
    assert not pd.isna(signal.iloc[-1])
    assert not pd.isna(hist.iloc[-1])
    
def test_deterministic_atr(sample_ohlcv):
    atr = calc_atr(sample_ohlcv["High"], sample_ohlcv["Low"], sample_ohlcv["Close"], 14)
    assert not pd.isna(atr.iloc[-1])
    
def test_deterministic_adx(sample_ohlcv):
    adx, plus_di, minus_di = calc_adx(sample_ohlcv["High"], sample_ohlcv["Low"], sample_ohlcv["Close"], 14)
    assert not pd.isna(adx.iloc[-1])
    
def test_deterministic_bollinger(sample_ohlcv):
    upper, mid, lower = calc_bollinger_bands(sample_ohlcv["Close"], 20, 2)
    assert upper.iloc[-1] > mid.iloc[-1]
    assert lower.iloc[-1] < mid.iloc[-1]
    
def test_deterministic_supertrend(sample_ohlcv):
    st = calc_supertrend(sample_ohlcv["High"], sample_ohlcv["Low"], sample_ohlcv["Close"])
    assert not pd.isna(st.iloc[-1])

def test_pivot_points():
    pivots = calc_pivot_points(120, 100, 110)
    assert pivots["pivot"] == 110
    assert pivots["r1"] == 120
    assert pivots["s1"] == 100
    assert pivots["r2"] == 130
    assert pivots["s2"] == 90
    assert pivots["r3"] == 140
    assert pivots["s3"] == 80
