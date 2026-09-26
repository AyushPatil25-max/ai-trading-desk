import pytest
import os
from unittest.mock import patch, AsyncMock
from backend.application.production_intelligence_service import ProductionIntelligenceService

@pytest.mark.asyncio
async def test_health_and_readiness_endpoints():
    from backend.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    
    resp = client.get("/api/production-intelligence/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    
    resp = client.get("/api/production-intelligence/readiness")
    assert resp.status_code == 200
    data = resp.json()
    assert "overall_status" in data
    assert "components" in data
    assert "providers" in data

@pytest.mark.asyncio
async def test_safety_invariants():
    service = ProductionIntelligenceService()
    res = await service.get_readiness()
    
    # Must preserve the safety invariants
    assert res.live_execution_enabled == (os.getenv("LIVE_EXECUTION_ENABLED", "false").lower() == "true")
    assert res.execution_freeze_active == (os.getenv("EXECUTION_FREEZE_ACTIVE", "true").lower() == "true")
    assert res.live_execution_enabled is False
    assert res.execution_freeze_active is True

@pytest.mark.asyncio
async def test_provider_status_visibility():
    service = ProductionIntelligenceService()
    res = await service.get_readiness()
    
    provider_names = [p.provider_name for p in res.providers]
    assert "YFinanceProvider" in provider_names
    assert "MarketDataProvider (Upstox)" in provider_names

@pytest.mark.asyncio
async def test_component_health_visibility():
    service = ProductionIntelligenceService()
    res = await service.get_readiness()
    
    comp_names = [c.name for c in res.components]
    assert "PersistentStateStore" in comp_names
    assert "AI/LLM (Gemini Flash)" in comp_names or "AI/LLM" in comp_names
    
    pipeline_names = [p.pipeline_name for p in res.pipelines]
    assert "Research Synthesis" in pipeline_names
    assert "AI Quality Validation" in pipeline_names
