import pytest
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def test_portfolio_intelligence_endpoint():
    response = client.get("/api/v1/portfolio/intelligence")
    assert response.status_code == 200
    
    data = response.json()
    assert "portfolio_id" in data
    assert "total_equity" in data
    assert "positions" in data
    assert "aggregated_bullish_score" in data
    assert "aggregated_bearish_score" in data
    assert "overall_portfolio_risk_state" in data
