import pytest
import asyncio
import pandas as pd
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from datetime import datetime, timezone

from backend.main import app
from backend.application.chart_service import ChartService
from backend.domain.chart_schemas import ChartDataState, ChartMultiTimeframeAlignment, ChartDataQuality

client = TestClient(app)

def make_ohlcv(length=100, base=100.0, trend=0.1):
    dates = pd.date_range(start='2020-01-01', periods=length, freq='B')
    return pd.DataFrame({
        'Open': [float(base + i*trend) for i in range(length)],
        'High': [float(base + i*trend + 2.0) for i in range(length)],
        'Low': [float(base + i*trend - 2.0) for i in range(length)],
        'Close': [float(base + i*trend + 1.0) for i in range(length)],
        'Volume': [1000.0 for _ in range(length)]
    }, dtype=float, index=dates)

@pytest.fixture
def chart_service():
    srv = ChartService()
    srv.gateway = MagicMock()
    srv.gateway.get_latest_quote.return_value = None
    srv.integrity_engine = MagicMock()
    srv.integrity_engine.fail_closed_check.return_value = False
    return srv

@pytest.mark.asyncio
async def test_historical_data_with_indicators(chart_service):
    df = make_ohlcv(100, trend=0.1)
    with patch('yfinance.Ticker') as mock_ticker:
        mock_tkr_instance = MagicMock()
        mock_tkr_instance.history.return_value = df
        mock_ticker.return_value = mock_tkr_instance
        
        res = await chart_service.get_chart_data("RELIANCE", "1D")
        assert res.data_state == ChartDataState.HISTORICAL
        assert res.data_quality == ChartDataQuality.COMPLETE
        assert len(res.candles) == 100
        
        last_candle = res.candles[-1]
        assert last_candle.indicators.sma20 is not None
        assert last_candle.indicators.sma50 is not None
        assert last_candle.indicators.sma200 is None
        assert last_candle.indicators.rsi14 is not None
        assert last_candle.indicators.macd is not None
        assert last_candle.vwap is not None
        assert res.historical_source == "yfinance"
        assert res.live_source is None

@pytest.mark.asyncio
async def test_live_data_update(chart_service):
    df = make_ohlcv(50)
    with patch('yfinance.Ticker') as mock_ticker:
        mock_tkr_instance = MagicMock()
        mock_tkr_instance.history.return_value = df
        mock_ticker.return_value = mock_tkr_instance
        
        # Inject live quote matching today's date so it updates the last candle
        chart_service.gateway.get_latest_quote.return_value = {"last_traded_price": 200.0, "volume": 5000, "timestamp": 1700000000}
        chart_service.integrity_engine.fail_closed_check.return_value = True
        
        with patch('backend.application.chart_service.datetime') as mock_dt:
            # mock datetime.now to match the last candle's date
            mock_dt.now.return_value.date.return_value = df.index[-1].date()
            mock_dt.now.return_value.isoformat.return_value = "2020-03-10T00:00:00Z"
            mock_dt.fromtimestamp = datetime.fromtimestamp # allow real fromtimestamp parsing
            
            res = await chart_service.get_chart_data("RELIANCE", "1D")
            assert res.data_state == ChartDataState.LIVE
            assert res.live_source == "Upstox"
            
            last_candle = res.candles[-1]
            assert last_candle.close == 200.0
            assert last_candle.volume == 5000.0

@pytest.mark.asyncio
async def test_stale_data_no_update(chart_service):
    df = make_ohlcv(50)
    original_close = df['Close'].iloc[-1]
    
    with patch('yfinance.Ticker') as mock_ticker:
        mock_tkr_instance = MagicMock()
        mock_tkr_instance.history.return_value = df.copy()
        mock_ticker.return_value = mock_tkr_instance
        
        # Inject stale quote
        chart_service.gateway.get_latest_quote.return_value = {"last_traded_price": 999.0}
        chart_service.integrity_engine.fail_closed_check.return_value = False
        
        with patch('backend.application.chart_service.datetime') as mock_dt:
            mock_dt.now.return_value.date.return_value = df.index[-1].date()
            mock_dt.now.return_value.isoformat.return_value = "2020-03-10T00:00:00Z"
            
            res = await chart_service.get_chart_data("RELIANCE", "1D")
            assert res.data_state == ChartDataState.STALE
            
            last_candle = res.candles[-1]
            assert last_candle.close == original_close  # did not overwrite
            assert last_candle.close != 999.0

@pytest.mark.asyncio
async def test_invalid_candle_removal(chart_service):
    df = make_ohlcv(10)
    # create invalid candles
    df.iloc[0, df.columns.get_loc('High')] = 50.0
    df.iloc[0, df.columns.get_loc('Low')] = 60.0 # High < Low
    df.iloc[1, df.columns.get_loc('Volume')] = -100 # Neg volume
    
    with patch('yfinance.Ticker') as mock_ticker:
        mock_tkr_instance = MagicMock()
        mock_tkr_instance.history.return_value = df
        mock_ticker.return_value = mock_tkr_instance
        
        res = await chart_service.get_chart_data("RELIANCE", "1D")
        assert res.data_quality == ChartDataQuality.PARTIAL
        assert len(res.candles) == 8 # 2 removed

@pytest.mark.asyncio
async def test_intraday_vwap_reset(chart_service):
    df = make_ohlcv(20)
    # Make them on 2 different days
    df.index = pd.date_range(start='2020-01-01 09:00', periods=20, freq='h')
    
    with patch('yfinance.Ticker') as mock_ticker:
        mock_tkr_instance = MagicMock()
        mock_tkr_instance.history.return_value = df
        mock_ticker.return_value = mock_tkr_instance
        
        res = await chart_service.get_chart_data("RELIANCE", "1h")
        
        # First day's first vwap should equal its close
        assert res.candles[0].vwap == res.candles[0].close
        # Find next day index
        first_date = df.index[0].date()
        next_day_idx = 0
        for i, dt in enumerate(df.index):
            if dt.date() != first_date:
                next_day_idx = i
                break
                
        if next_day_idx > 0:
            assert res.candles[next_day_idx].vwap == res.candles[next_day_idx].close

def test_chart_api_validation():
    # Valid timeframe mock
    with patch('backend.application.chart_routes.ChartService.get_chart_data') as mock_srv:
        mock_srv.return_value = {
            "symbol": "TEST", "exchange": "NSE", "timeframe": "1D", 
            "data_state": "HISTORICAL", "data_quality": "COMPLETE", 
            "candles": [], "mtf_alignment": "INSUFFICIENT_DATA", 
            "historical_source": "test", "live_source": None, "generated_at": "2020-01-01T00:00:00Z"
        }
        response = client.get("/api/v1/charts/TEST?timeframe=1D")
        assert response.status_code == 200

    # Invalid timeframe
    response = client.get("/api/v1/charts/TEST?timeframe=1Y")
    assert response.status_code == 400
    assert "Invalid timeframe" in response.json()['detail']
