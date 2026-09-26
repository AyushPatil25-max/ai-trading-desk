from fastapi import APIRouter
from backend.domain.production_intelligence_schemas import ProductionReadiness, ServiceStatus
from backend.application.production_intelligence_service import global_production_intelligence_service

production_intelligence_routes = APIRouter(prefix="/api/production-intelligence", tags=["Production Intelligence"])

@production_intelligence_routes.get("/health", response_model=dict)
async def get_health():
    return {"status": "ok", "service": "production-intelligence"}

@production_intelligence_routes.get("/readiness", response_model=ProductionReadiness)
async def get_readiness():
    return await global_production_intelligence_service.get_readiness()

@production_intelligence_routes.get("/status", response_model=dict)
async def get_status():
    readiness = await global_production_intelligence_service.get_readiness()
    return {
        "overall_status": readiness.overall_status.value,
        "is_ready": readiness.is_ready,
        "safety": {
            "live_execution_enabled": readiness.live_execution_enabled,
            "execution_freeze_active": readiness.execution_freeze_active
        }
    }
