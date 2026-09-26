from enum import Enum
from typing import List, Dict, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field

class ServiceStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"

class ComponentHealth(BaseModel):
    name: str
    status: ServiceStatus
    details: str = ""
    latency_ms: Optional[float] = None
    last_check: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ProviderQuality(BaseModel):
    provider_name: str
    status: ServiceStatus
    freshness: str = "UNKNOWN"
    completeness: float = 0.0
    quality_warnings: List[str] = Field(default_factory=list)

class PipelineStatus(BaseModel):
    pipeline_name: str
    status: ServiceStatus
    last_run: Optional[datetime] = None
    success_rate: float = 1.0

class ProductionReadiness(BaseModel):
    is_ready: bool
    live_execution_enabled: bool
    execution_freeze_active: bool
    overall_status: ServiceStatus
    components: List[ComponentHealth] = Field(default_factory=list)
    providers: List[ProviderQuality] = Field(default_factory=list)
    pipelines: List[PipelineStatus] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
