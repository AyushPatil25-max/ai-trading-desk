import time
from typing import List
from datetime import datetime, timezone
import os

from backend.domain.production_intelligence_schemas import (
    ProductionReadiness,
    ServiceStatus,
    ComponentHealth,
    ProviderQuality,
    PipelineStatus
)

from backend.infrastructure.providers.yfinance_provider import YFinanceProvider
from backend.infrastructure.providers.market_data_provider import UpstoxMarketDataProvider
from backend.infrastructure.llm_provider_adapter import LLMAdapterFactory
from backend.execution.persistent_state_store import global_persistent_state_store

class ProductionIntelligenceService:
    async def get_readiness(self) -> ProductionReadiness:
        components = []
        providers = []
        pipelines = []
        warnings = []
        
        overall_ready = True
        
        # 1. Check Persistence
        start_t = time.time()
        try:
            # Just do a quick write/read check
            test_key = "health:ping"
            global_persistent_state_store.set(test_key, {"ts": time.time()})
            global_persistent_state_store.get(test_key)
            global_persistent_state_store.delete(test_key)
            latency = (time.time() - start_t) * 1000
            components.append(ComponentHealth(name="PersistentStateStore", status=ServiceStatus.HEALTHY, latency_ms=latency, details="Read/Write OK"))
        except Exception as e:
            overall_ready = False
            components.append(ComponentHealth(name="PersistentStateStore", status=ServiceStatus.UNAVAILABLE, details=str(e)))
            warnings.append("Persistence is unavailable.")

        # 2. Check Data Providers
        # YFinance
        start_t = time.time()
        try:
            yf = YFinanceProvider()
            # Minimal non-blocking check
            res = await yf.get_quote("RELIANCE.NS")
            if res.status == "SUCCESS":
                providers.append(ProviderQuality(
                    provider_name="YFinanceProvider",
                    status=ServiceStatus.HEALTHY,
                    freshness="REALTIME" if res.data.get('is_market_open') else "DELAYED",
                    completeness=1.0
                ))
            else:
                providers.append(ProviderQuality(
                    provider_name="YFinanceProvider",
                    status=ServiceStatus.DEGRADED,
                    quality_warnings=[res.error_message]
                ))
        except Exception as e:
            providers.append(ProviderQuality(provider_name="YFinanceProvider", status=ServiceStatus.UNAVAILABLE, quality_warnings=[str(e)]))

        # Upstox
        upstox_key = os.getenv("UPSTOX_API_KEY", "mock")
        if not upstox_key or upstox_key == "mock":
            providers.append(ProviderQuality(
                provider_name="MarketDataProvider (Upstox)",
                status=ServiceStatus.NOT_CONFIGURED,
                quality_warnings=["Using mock or unconfigured API key"]
            ))
        else:
            try:
                mdp = UpstoxMarketDataProvider(api_key=upstox_key)
                res = mdp.get_quote("NSE_EQ|INE002A01018")
                providers.append(ProviderQuality(
                    provider_name="MarketDataProvider (Upstox)",
                    status=ServiceStatus.HEALTHY,
                    completeness=1.0
                ))
            except Exception as e:
                providers.append(ProviderQuality(provider_name="MarketDataProvider (Upstox)", status=ServiceStatus.UNAVAILABLE, quality_warnings=[str(e)]))
        
        # 3. Check AI/Model Status
        start_t = time.time()
        try:
            llm = LLMAdapterFactory.create_client("gemini_flash")
            
            from pydantic import BaseModel
            class PingModel(BaseModel):
                reply: str
                
            # Do a tiny generation
            res = await llm.generate_structured("Ping", "Reply 'Pong'", PingModel)
            latency = (time.time() - start_t) * 1000
            components.append(ComponentHealth(
                name="AI/LLM (Gemini Flash)",
                status=ServiceStatus.HEALTHY if "pong" in res.reply.lower() else ServiceStatus.DEGRADED,
                latency_ms=latency,
                details="Model responded"
            ))
        except Exception as e:
            components.append(ComponentHealth(name="AI/LLM", status=ServiceStatus.UNAVAILABLE, details=str(e)))
            warnings.append("AI model unavailable.")
            overall_ready = False

        # 4. Pipeline Status (dummy check based on existing engines)
        pipelines.append(PipelineStatus(pipeline_name="Research Synthesis", status=ServiceStatus.HEALTHY))
        pipelines.append(PipelineStatus(pipeline_name="AI Quality Validation", status=ServiceStatus.HEALTHY))

        # 5. Check Safety Configurations
        live_execution = os.getenv("LIVE_EXECUTION_ENABLED", "false").lower() == "true"
        freeze_active = os.getenv("EXECUTION_FREEZE_ACTIVE", "true").lower() == "true"
        
        if live_execution or not freeze_active:
            warnings.append("CRITICAL WARNING: Live execution is enabled or freeze is disabled.")
        
        # Final evaluation
        overall_status = ServiceStatus.HEALTHY
        if any(c.status == ServiceStatus.UNAVAILABLE for c in components):
            overall_status = ServiceStatus.DEGRADED
        
        return ProductionReadiness(
            is_ready=overall_ready,
            live_execution_enabled=live_execution,
            execution_freeze_active=freeze_active,
            overall_status=overall_status,
            components=components,
            providers=providers,
            pipelines=pipelines,
            warnings=warnings
        )

global_production_intelligence_service = ProductionIntelligenceService()
