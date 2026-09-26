import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock

from backend.main import app

client = TestClient(app)

@pytest.fixture
def mock_yfinance_history():
    # Just mock historical data from YFinanceProvider so we don't hit the network in CI
    mock_bars = []
    base_time = datetime(2023, 1, 1, tzinfo=timezone.utc)
    for i in range(100):
        mock_bars.append({
            "timestamp": base_time.isoformat(),
            "open": 100 + i,
            "high": 105 + i,
            "low": 95 + i,
            "close": 102 + i,
            "volume": 1000000
        })
        from datetime import timedelta
        base_time += timedelta(days=1)
        
    with patch(
        'backend.infrastructure.providers.yfinance_provider.YFinanceProvider.get_historical_data',
        new_callable=AsyncMock,
        return_value=type('ProviderResult', (), {
            'status': 'SUCCESS',
            'data': {'ohlcv': mock_bars}
        })
    ) as m:
        yield m
    
@pytest.fixture
def mock_yfinance_fundamentals():
    with patch(
        'backend.infrastructure.providers.yfinance_provider.YFinanceProvider.get_fundamentals',
        new_callable=AsyncMock,
        return_value=type('ProviderResult', (), {
            'status': 'SUCCESS',
            'data': {'pe_ratio': 15.0}
        })
    ) as m:
        yield m

def test_historical_research_run(mock_yfinance_history, mock_yfinance_fundamentals):
    payload = {
        "symbol": "RELIANCE.NS",
        "as_of": "2023-02-15T00:00:00Z",
        "config": {
            "mode": "SINGLE_DECISION",
            "holding_period_bars": 5
        }
    }
    
    response = client.post("/api/historical-research/run", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    assert "backtest_id" in data
    assert "primary_outcome" in data
    assert "decision_snapshot" in data
    
    snapshot = data["decision_snapshot"]
    assert snapshot["symbol"] == "RELIANCE.NS"
    # Ensure point-in-time check is done correctly
    # The evaluation_timestamp should match the request
    assert "2023-02-15" in snapshot["evaluation_timestamp"]
    
def test_historical_research_results():
    response = client.get("/api/historical-research/results")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
