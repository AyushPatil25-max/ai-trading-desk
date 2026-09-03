"""
Phase 21 — Market Data Provider Health & Resilience API Routes

Exposes REST endpoints for inspecting provider health scorecards,
latency percentiles (p50/p95/p99), circuit breaker states, fallback levels,
and manual circuit breaker resets.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException

from backend.domain.provider_schemas import ProviderOrchestratorStatus
from backend.infrastructure.provider_orchestrator import ResilientProviderOrchestrator

provider_router = APIRouter(prefix="/api/providers", tags=["Data Providers"])


def get_orchestrator() -> ResilientProviderOrchestrator:
    """Dependency resolver for ResilientProviderOrchestrator singleton."""
    from backend.main import get_provider_orchestrator as global_get
    return global_get()


@provider_router.get("/health", response_model=ProviderOrchestratorStatus)
async def get_providers_health(
    orchestrator: ResilientProviderOrchestrator = Depends(get_orchestrator),
) -> ProviderOrchestratorStatus:
    """
    Retrieve comprehensive health metrics, circuit states, and latency percentiles
    across all registered market data providers.
    """
    try:
        return orchestrator.get_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve provider health: {e}")


@provider_router.get("/status")
async def get_providers_compact_status(
    orchestrator: ResilientProviderOrchestrator = Depends(get_orchestrator),
) -> Dict[str, Any]:
    """Compact status endpoint for high-frequency dashboard polling."""
    status = orchestrator.get_status()
    return {
        "system_status": status.system_status.value,
        "primary_provider": status.primary_provider,
        "active_provider": status.active_provider,
        "fallback_level": status.fallback_level,
        "is_fallback_active": status.is_fallback_active,
        "degraded_warning": status.degraded_warning,
        "timestamp": status.evaluated_at.isoformat(),
    }


@provider_router.post("/circuits/reset")
async def reset_circuits(
    orchestrator: ResilientProviderOrchestrator = Depends(get_orchestrator),
) -> Dict[str, Any]:
    """Operator endpoint to manually reset tripped circuit breakers back to CLOSED."""
    try:
        orchestrator.reset_circuits()
        status = orchestrator.get_status()
        return {
            "status": "RESET_SUCCESSFUL",
            "message": "All data provider circuit breakers have been reset to CLOSED.",
            "active_provider": status.active_provider,
            "fallback_level": status.fallback_level,
            "reset_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reset circuit breakers: {e}")
