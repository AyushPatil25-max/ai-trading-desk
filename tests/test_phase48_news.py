import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

from backend.main import app
from backend.application.news_engine import NewsEngine
from backend.domain.news_schemas import (
    NewsCategory, SentimentState, ImportanceLevel, NewsDataState,
    AlertRule, AlertState, ProviderResponseState, NewsItem, NewsProvenance, NewsResponse
)

client = TestClient(app)

@pytest.fixture
def news_engine():
    engine = NewsEngine()
    engine.orchestrator = MagicMock()
    return engine

@pytest.mark.asyncio
async def test_get_company_news_normal(news_engine):
    mock_res = MagicMock()
    mock_res.success = True
    mock_res.data = [
        {"title": "Company reports record Q1 earnings and beats estimates", "link": "http://test1", "publisher": "TestProv"},
        {"title": "Stock plunges on regulatory fears", "link": "http://test2", "pubDate": "2020-01-01T00:00:00Z"},
        {"title": "Company reports record Q1 earnings and beats estimates", "link": "http://test1"} # Duplicate
    ]
    news_engine.orchestrator.get_news = AsyncMock(return_value=mock_res)
    
    resp = await news_engine.get_company_news("RELIANCE")
    news = resp.data
    assert resp.state == ProviderResponseState.SUCCESS_WITH_DATA
    assert len(news) == 2 
    
    q1 = next(n for n in news if "Q1" in n.headline)
    assert q1.category == NewsCategory.RESULTS
    assert q1.importance == ImportanceLevel.CRITICAL
    assert q1.sentiment == SentimentState.POSITIVE
    assert q1.provenance.source_name == "TestProv"
    assert q1.published_at is None
    assert q1.ai_analysis is None
    assert q1.rule_sentiment is not None
    assert q1.rule_sentiment.methodology == "RULE-BASED SENTIMENT"
    
    plunge = next(n for n in news if "plunges" in n.headline)
    assert plunge.sentiment == SentimentState.NEGATIVE
    assert plunge.data_state == NewsDataState.STALE
    assert plunge.category == NewsCategory.COMPANY
    assert plunge.published_at == "2020-01-01T00:00:00Z"

@pytest.mark.asyncio
async def test_get_corporate_actions(news_engine):
    mock_res = MagicMock()
    mock_res.success = True
    mock_res.data = {
        "Dividends": [
            {"Date": "2023-05-15 00:00:00-04:00", "Dividends": 10.0}
        ],
        "Stock Splits": [
            {"Date": "2023-06-01 00:00:00-04:00", "Stock Splits": 2.0}
        ],
        "MissingDate": [
            {"Dividends": 5.0}
        ]
    }
    news_engine.orchestrator.get_corporate_actions = AsyncMock(return_value=mock_res)
    
    resp = await news_engine.get_corporate_actions("RELIANCE")
    events = resp.data
    assert resp.state == ProviderResponseState.SUCCESS_WITH_DATA
    assert len(events) == 3
    
    div = next(e for e in events if e.event_type.value == "DIVIDEND" and e.scheduled_time is not None)
    assert div.status == "COMPLETED"
    
    split = next(e for e in events if e.event_type.value == "SPLIT")
    assert split.status == "COMPLETED"
    assert split.provenance.source_name == "Yahoo Finance"
    
    missing = next(e for e in events if e.scheduled_time is None)
    assert missing.status == "UNKNOWN"

@pytest.mark.asyncio
async def test_alert_engine_evaluation(news_engine):
    rule = AlertRule(
        id="test-rule",
        symbol="RELIANCE",
        state=AlertState.ACTIVE,
        created_at="2023-01-01T00:00:00Z",
        cooldown_minutes=60
    )
    news_engine.create_alert_rule(rule)
    
    item1 = NewsItem(
        id="n1",
        headline="Title",
        source_name="Prov",
        source_type="API",
        fetched_at="2023-01-01T00:00:00Z",
        symbols=["RELIANCE"],
        category=NewsCategory.COMPANY,
        sentiment=SentimentState.POSITIVE,
        importance=ImportanceLevel.HIGH,
        content_hash="h1",
        provenance=NewsProvenance(source_name="Prov", source_type="API", fetched_at="ts")
    )
    
    news_engine.evaluate_news_alerts([item1])
    assert len(news_engine.alert_events) == 1
    assert news_engine.alert_events[0].rule_id == "test-rule"
    assert news_engine.alert_events[0].trigger_event_id == "n1"
    
    # Check cooldown logic - sending same trigger or within 60 mins won't add duplicate
    item2 = NewsItem(
        id="n2",
        headline="Title 2",
        source_name="Prov",
        source_type="API",
        fetched_at="2023-01-01T00:00:00Z",
        symbols=["RELIANCE"],
        category=NewsCategory.COMPANY,
        sentiment=SentimentState.POSITIVE,
        importance=ImportanceLevel.HIGH,
        content_hash="h2",
        provenance=NewsProvenance(source_name="Prov", source_type="API", fetched_at="ts")
    )
    
    news_engine.evaluate_news_alerts([item2])
    # Cooldown prevents n2 from triggering
    assert len(news_engine.alert_events) == 1

def test_api_news_endpoints():
    with patch('backend.application.news_routes.get_news_engine') as mock_get_engine:
        mock_engine = MagicMock()
        mock_resp = NewsResponse(state=ProviderResponseState.SUCCESS_EMPTY, data=[])
        mock_engine.get_company_news = AsyncMock(return_value=mock_resp)
        mock_get_engine.return_value = mock_engine
        
        response = client.get("/api/v1/news/RELIANCE?limit=10")
        assert response.status_code == 200
        assert response.json()["state"] == "SUCCESS_EMPTY"
        
        response2 = client.get("/api/v1/news")
        assert response2.status_code == 200

def test_api_alerts_endpoints():
    with patch('backend.application.news_routes.get_news_engine') as mock_get_engine:
        mock_engine = MagicMock()
        
        def mock_create(r): return r
        def mock_update(id, u): return AlertRule(id=id, created_at="", state=u.get("state", "ACTIVE"))
        def mock_delete(id): return True
            
        mock_engine.create_alert_rule.side_effect = mock_create
        mock_engine.update_alert_rule.side_effect = mock_update
        mock_engine.delete_alert_rule.side_effect = mock_delete
        mock_get_engine.return_value = mock_engine
        
        payload = {
            "id": "r1",
            "symbol": "RELIANCE",
            "state": "ACTIVE",
            "created_at": "",
            "cooldown_minutes": 60
        }
        res = client.post("/api/v1/alerts", json=payload)
        assert res.status_code == 200
        
        res2 = client.patch("/api/v1/alerts/r1", json={"state": "DISABLED"})
        assert res2.status_code == 200
        assert res2.json()["state"] == "DISABLED"
        
        res3 = client.delete("/api/v1/alerts/r1")
        assert res3.status_code == 200

@pytest.mark.asyncio
async def test_news_provider_failure(news_engine):
    mock_res = MagicMock()
    mock_res.success = False
    mock_res.data = None
    mock_res.error_message = "API Timeout"
    news_engine.orchestrator.get_news = AsyncMock(return_value=mock_res)
    
    resp = await news_engine.get_company_news("RELIANCE")
    assert resp.state == ProviderResponseState.ERROR
    assert resp.error_message == "API Timeout"
    assert len(resp.data) == 0
