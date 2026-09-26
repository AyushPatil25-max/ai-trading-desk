import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from datetime import datetime, timezone
import uuid

from backend.main import app
from backend.application.earnings_engine import EarningsEngine
from backend.domain.earnings_schemas import EarningsEventStatus, EarningsEvent, EarningsResult, EarningsResponse
from backend.domain.schemas import QuarterlyStatement, ProvenanceRecord
from backend.domain.earnings_schemas import EarningsProvenance
from backend.infrastructure.providers.base import ProviderResult

client = TestClient(app)

@pytest.fixture
def earnings_engine():
    engine = EarningsEngine()
    engine.provider = MagicMock()
    engine.provider.name = "mock_provider"
    return engine

@pytest.mark.asyncio
async def test_get_earnings_calendar(earnings_engine):
    mock_res = ProviderResult(
        status="SUCCESS",
        data={
            "events": [
                {
                    "symbol": "RELIANCE",
                    "earnings_date": "2023-10-15T00:00:00Z",
                    "eps_estimate": 12.5,
                    "reported_eps": 13.0,
                    "surprise_pct": 4.0
                }
            ]
        },
        provenance=[]
    )
    earnings_engine.provider.get_earnings_calendar = AsyncMock(return_value=mock_res)
    
    res = await earnings_engine.get_earnings_calendar("RELIANCE")
    assert res.status == EarningsEventStatus.AVAILABLE
    assert len(res.events) == 1
    assert res.events[0].expected_report_date == "2023-10-15T00:00:00Z"

@pytest.mark.asyncio
async def test_get_earnings_results(earnings_engine):
    # Mock Calendar for Expectations
    mock_cal = ProviderResult(
        status="SUCCESS",
        data={
            "events": [
                {
                    "symbol": "RELIANCE",
                    "earnings_date": "2023-10-15T00:00:00Z",
                    "eps_estimate": 12.5,
                    "reported_eps": 13.0,
                    "surprise_pct": 4.0
                }
            ]
        },
        provenance=[]
    )
    earnings_engine.provider.get_earnings_calendar = AsyncMock(return_value=mock_cal)

    now = datetime(2023, 10, 15, tzinfo=timezone.utc)
    
    q1 = QuarterlyStatement(
        symbol="RELIANCE",
        period_end_date=datetime(2023, 9, 30, tzinfo=timezone.utc),
        revenue=1000.0,
        operating_profit=200.0,
        ebitda=250.0,
        net_income=150.0,
        eps=13.0
    )
    q2 = QuarterlyStatement(
        symbol="RELIANCE",
        period_end_date=datetime(2023, 6, 30, tzinfo=timezone.utc),
        revenue=900.0,
        operating_profit=180.0,
        ebitda=220.0,
        net_income=120.0,
        eps=10.0
    )
    
    mock_res = ProviderResult(
        status="SUCCESS",
        data={"statements": [q1, q2]},
        provenance=[]
    )
    earnings_engine.provider.get_quarterly_fundamentals = AsyncMock(return_value=mock_res)
    
    res = await earnings_engine.get_earnings_results("RELIANCE")
    assert res.status == EarningsEventStatus.AVAILABLE
    assert res.latest_result is not None
    assert len(res.historical_results) == 1
    
    latest = res.latest_result
    # Check normalization
    assert latest.revenue.actual == 1000.0
    # Check QoQ calculation: (1000 - 900)/900 = 11.11%
    assert latest.revenue.qoq_change_pct == 11.11
    
    # Check EPS expectation merged
    assert latest.eps.actual == 13.0
    assert latest.eps.expected == 12.5
    assert latest.eps.surprise_pct == 4.0

def test_api_endpoints():
    with patch('backend.application.earnings_routes.get_earnings_engine') as mock_get_engine:
        mock_engine = MagicMock()
        mock_engine.get_earnings_calendar = AsyncMock(return_value=EarningsResponse(symbol="RELIANCE", status=EarningsEventStatus.AVAILABLE))
        mock_engine.get_earnings_results = AsyncMock(return_value=EarningsResponse(symbol="RELIANCE", status=EarningsEventStatus.AVAILABLE))
        mock_get_engine.return_value = mock_engine
        
        response = client.get("/api/v1/earnings/RELIANCE/calendar")
        assert response.status_code == 200
        
        response2 = client.get("/api/v1/earnings/RELIANCE/results")
        assert response2.status_code == 200

@pytest.mark.asyncio
async def test_provider_failure(earnings_engine):
    mock_res = ProviderResult(status="ERROR", error="API Timeout")
    earnings_engine.provider.get_quarterly_fundamentals = AsyncMock(return_value=mock_res)
    
    res = await earnings_engine.get_earnings_results("RELIANCE")
    assert res.status == EarningsEventStatus.PROVIDER_ERROR
    assert res.error_message == "API Timeout"

@pytest.mark.asyncio
async def test_missing_data_normalization(earnings_engine):
    mock_cal = ProviderResult(status="SUCCESS_EMPTY", data={"events": []}, provenance=[])
    earnings_engine.provider.get_earnings_calendar = AsyncMock(return_value=mock_cal)

    q1 = QuarterlyStatement(
        symbol="RELIANCE",
        period_end_date=datetime(2023, 9, 30, tzinfo=timezone.utc),
        revenue=None,
        operating_profit=0,
        net_income=-50.0
    )
    
    mock_res = ProviderResult(
        status="SUCCESS",
        data={"statements": [q1]},
        provenance=[]
    )
    earnings_engine.provider.get_quarterly_fundamentals = AsyncMock(return_value=mock_res)
    
    res = await earnings_engine.get_earnings_results("RELIANCE")
    assert res.latest_result.revenue is None
    assert res.latest_result.operating_profit.actual == 0
    assert res.latest_result.net_income.actual == -50.0

@pytest.mark.asyncio
async def test_negative_sign_change_qoq(earnings_engine):
    mock_cal = ProviderResult(status="SUCCESS_EMPTY", data={"events": []}, provenance=[])
    earnings_engine.provider.get_earnings_calendar = AsyncMock(return_value=mock_cal)

    q1 = QuarterlyStatement(
        symbol="RELIANCE", period_end_date=datetime(2023, 9, 30, tzinfo=timezone.utc),
        net_income=50.0
    )
    q2 = QuarterlyStatement(
        symbol="RELIANCE", period_end_date=datetime(2023, 6, 30, tzinfo=timezone.utc),
        net_income=-100.0
    )
    
    mock_res = ProviderResult(status="SUCCESS", data={"statements": [q1, q2]}, provenance=[])
    earnings_engine.provider.get_quarterly_fundamentals = AsyncMock(return_value=mock_res)
    
    res = await earnings_engine.get_earnings_results("RELIANCE")
    # (50 - -100) / |-100| * 100 = 150 / 100 * 100 = 150%
    assert res.latest_result.net_income.qoq_change_pct == 150.0

