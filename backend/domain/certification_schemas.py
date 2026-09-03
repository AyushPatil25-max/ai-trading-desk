from enum import Enum
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List, Optional, Dict
from datetime import datetime
import uuid

# ================================
# PHASE 36 SCHEMAS
# ================================
class EnvironmentType(str, Enum):
    DEVELOPMENT = "DEVELOPMENT"
    TEST = "TEST"
    PAPER = "PAPER"
    SHADOW_LIVE = "SHADOW_LIVE"
    CONTROLLED_LIVE = "CONTROLLED_LIVE"
    PRODUCTION = "PRODUCTION"

class CertificationStatus(str, Enum):
    NOT_CERTIFIED = "NOT_CERTIFIED"
    CONDITIONALLY_CERTIFIED = "CONDITIONALLY_CERTIFIED"
    CERTIFIED_SANDBOX = "CERTIFIED_SANDBOX"
    CERTIFIED_FOR_CONTROLLED_LIVE = "CERTIFIED_FOR_CONTROLLED_LIVE"
    CERTIFIED_FOR_PAPER = "CERTIFIED_FOR_PAPER"
    CERTIFIED = "CERTIFIED"
    CERTIFIED_WITH_WARNINGS = "CERTIFIED_WITH_WARNINGS"
    BLOCKED = "BLOCKED"

class CertificationCategoryEnum(str, Enum):
    CONFIGURATION = "CONFIGURATION"
    SAFETY = "SAFETY"
    BROKER_CONNECTIVITY = "BROKER_CONNECTIVITY"
    RUNTIME_INTEGRITY = "RUNTIME_INTEGRITY"

class CertificationCheck(BaseModel):
    check_id: str
    category: CertificationCategoryEnum
    description: str
    passed: bool
    severity: str = "CRITICAL"
    details: Optional[str] = None

class LiveReadinessMatrix(BaseModel):
    environment: EnvironmentType
    overall_status: CertificationStatus
    checks: List[CertificationCheck] = Field(default_factory=list)
    evaluated_at: datetime
    blocking_failures: List[str] = Field(default_factory=list)

# ================================
# PREVIOUS PHASES SCHEMAS
# ================================
SYSTEM_CERTIFICATION_VERSION = "1.0.0"

class ExecutionMode(str, Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"
    BACKTEST = "BACKTEST"
    FORWARD_SIMULATION = "FORWARD_SIMULATION"
    RESEARCH = "RESEARCH"
    SHADOW = "SHADOW"

class HealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"

class SystemOperationalState(str, Enum):
    STARTING = "STARTING"
    READY = "READY"
    DRAINING = "DRAINING"
    SHUTTING_DOWN = "SHUTTING_DOWN"
    SHUTDOWN = "SHUTDOWN"
    STOPPED = "STOPPED"
    DEGRADED = "DEGRADED"
    ERROR = "ERROR"

class CheckpointIntegrityStatus(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"

class ComponentHealth(BaseModel):
    name: str
    status: HealthStatus
    latency_ms: Optional[float] = 0.0
    error_message: Optional[str] = None

class ProductionConfig(BaseModel):
    environment: str = "PAPER"
    mode: ExecutionMode = ExecutionMode.PAPER
    initial_capital: float = 100000.0
    max_order_value: float = 50000.0
    allowed_symbols: List[str] = Field(default_factory=lambda: ["RELIANCE.NS"])
    data_poll_interval_seconds: int = 1
    audit_log_capacity: int = 1000
    require_audit_chain: bool = True
    api_key_redacted: str = "***REDACTED***"
    configuration_fingerprint: str = Field(default_factory=lambda: "a"*64)

    @field_validator("mode", mode="before")
    @classmethod
    def prevent_live(cls, v):
        if v == "LIVE" or v == ExecutionMode.LIVE:
            raise ValueError("LIVE not permitted")
        return v

class SystemStateCheckpoint(BaseModel):
    checkpoint_id: Optional[str] = None
    state: Optional[SystemOperationalState] = None
    active_symbols: Optional[List[str]] = None
    accounting_snapshot: Optional[Dict[str, float]] = None
    last_audit_hash: Optional[str] = None
    revision: Optional[int] = None
    checksum: Optional[str] = None
    timestamp: Optional[datetime] = None
    state_data: Optional[Dict] = None
    operational_state: Optional[SystemOperationalState] = None

    @model_validator(mode='after')
    def sync_state(self):
        if self.state is not None and self.operational_state is None:
            self.operational_state = self.state
        elif self.operational_state is not None and self.state is None:
            self.state = self.operational_state
        return self
    payload_checksum: Optional[str] = None
    audit_event_count: Optional[int] = None

    def compute_checksum(self) -> str:
        import hashlib
        import json
        payload = {
            "checkpoint_id": self.checkpoint_id,
            "active_symbols": self.active_symbols or [],
            "accounting_snapshot": self.accounting_snapshot or {},
            "hash": self.last_audit_hash or ""
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    version: Optional[str] = "1.0.0"

    def verify_checksum(self) -> bool:
        return self.payload_checksum == self.compute_checksum()

class SystemHealthReport(BaseModel):
    liveness: bool
    readiness: bool
    overall_health: HealthStatus
    operational_state: SystemOperationalState
    dependency_health: Dict[str, ComponentHealth] = Field(default_factory=dict)
    subsystem_health: Dict[str, ComponentHealth] = Field(default_factory=dict)
    safety_health: ComponentHealth
    active_workers_count: Optional[int] = None
    memory_usage_mb: Optional[float] = None
    status: Optional[HealthStatus] = None
    safety: Optional[bool] = None

class CertificationScenario(str, Enum):
    VALID_PAPER = "VALID_PAPER"
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
    LIVE_NOT_ARMED = "LIVE_NOT_ARMED"
    STRATEGY_REJECTION = "STRATEGY_REJECTION"
    CORRUPTED_CONFIGURATION = "CORRUPTED_CONFIGURATION"
    BROKER_AUTH_FAILURE = "BROKER_AUTH_FAILURE"
    STALE_MARKET_DATA = "STALE_MARKET_DATA"
    RESTART_LIVE_ARM_CLEARED = "RESTART_LIVE_ARM_CLEARED"
    DUPLICATE_WORKER = "DUPLICATE_WORKER"

class DryRunAssertionResult(BaseModel):
    assertion_name: str
    passed: bool
    details: Optional[str] = None

class CertificationScenarioResult(BaseModel):
    scenario: CertificationScenario
    passed: bool
    final_execution_state: str
    broker_interaction_count: int
    retry_count: int
    reconciliation_required: bool
    assertions: List[DryRunAssertionResult] = Field(default_factory=list)
    error_message: Optional[str] = None
    execution_latency_ms: float

class CertificationCategory(BaseModel):
    category_name: str
    score: float
    passed: bool
    status: CertificationStatus
    evidence: str
    blockers: List[str] = Field(default_factory=list)

class SystemCertificationReport(BaseModel):
    overall_status: Optional[CertificationStatus] = None
    overall_score: Optional[float] = None
    operational_state: Optional[SystemOperationalState] = None
    categories: List[CertificationCategory] = Field(default_factory=list)
    blockers: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    strongest_evidence: List[str] = Field(default_factory=list)
    configuration_fingerprint: Optional[str] = None
    audit_chain_status: Optional[str] = None
    
    report_id: str = Field(default_factory=lambda: "cert-rep-" + uuid.uuid4().hex[:8])
    scenarios_executed: Optional[int] = None
    scenarios_passed: Optional[int] = None
    total_broker_calls_simulated: Optional[int] = None
    blocked_execution_count: Optional[int] = None
    reconciliation_events_triggered: Optional[int] = None
    scenario_results: List[CertificationScenarioResult] = Field(default_factory=list)
    final_certification_status: Optional[CertificationStatus] = None
    tier_4_live_real_money_locked: Optional[bool] = True
    system_version: str = "Phase 33"
    safety_invariants_preserved: bool = True
