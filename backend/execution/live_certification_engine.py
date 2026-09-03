from datetime import datetime, timezone
from typing import List
import logging

from backend.domain.certification_schemas import (
    EnvironmentType,
    CertificationStatus,
    CertificationCategoryEnum,
    CertificationCheck,
    LiveReadinessMatrix
)
from backend.config.app_config import get_app_config
from backend.execution.safety_engine import global_kill_switch

logger = logging.getLogger(__name__)

class LiveCertificationEngine:
    def __init__(self):
        pass
        
    def evaluate_certification(self, environment: EnvironmentType) -> LiveReadinessMatrix:
        checks: List[CertificationCheck] = []
        blocking_failures: List[str] = []
        
        config = get_app_config()
        
        # 1. Configuration Validation
        is_live_safe = not config.live_execution_enabled
        checks.append(CertificationCheck(
            check_id="CFG-001",
            category=CertificationCategoryEnum.CONFIGURATION,
            description="LIVE_EXECUTION_ENABLED is safely disabled",
            passed=is_live_safe,
            details="Configuration is safe" if is_live_safe else "LIVE_EXECUTION_ENABLED must be false"
        ))
        if not is_live_safe:
            blocking_failures.append("LIVE_EXECUTION_ENABLED is dangerously set to True.")
            
        # 2. Safety Validation
        ks_active = global_kill_switch.is_active()
        checks.append(CertificationCheck(
            check_id="SFT-001",
            category=CertificationCategoryEnum.SAFETY,
            description="Emergency Kill Switch is NOT active",
            passed=not ks_active,
            details="Kill Switch is disengaged" if not ks_active else "Kill Switch is currently ACTIVE"
        ))
        if ks_active:
            blocking_failures.append("Emergency Kill Switch is currently active.")
            
        # 3. Broker Connectivity
        bad_endpoints = ["api.zerodha.com", "api.alpaca.markets", "api.upstox.com"]
        is_endpoint_safe = all(be not in config.dhan_api_base_url for be in bad_endpoints)
        checks.append(CertificationCheck(
            check_id="BRK-001",
            category=CertificationCategoryEnum.BROKER_CONNECTIVITY,
            description="Broker endpoint is not a known production real-money URL",
            passed=is_endpoint_safe,
            details="Endpoint is safe" if is_endpoint_safe else "Production endpoint detected"
        ))
        if not is_endpoint_safe:
            blocking_failures.append("Broker endpoint is a blocked production URL.")
            
        # 4. Runtime Integrity
        is_env_safe = environment not in (EnvironmentType.CONTROLLED_LIVE, EnvironmentType.PRODUCTION)
        checks.append(CertificationCheck(
            check_id="INT-001",
            category=CertificationCategoryEnum.RUNTIME_INTEGRITY,
            description="Environment is restricted from live real-money execution",
            passed=is_env_safe,
            details="Environment is valid for Phase 36" if is_env_safe else "CONTROLLED_LIVE and PRODUCTION are permanently locked."
        ))
        if not is_env_safe:
            blocking_failures.append("Environment type CONTROLLED_LIVE or PRODUCTION is locked in this phase.")

        # Determine Overall Status
        overall_status = CertificationStatus.NOT_CERTIFIED
        
        if len(blocking_failures) == 0:
            overall_status = CertificationStatus.CERTIFIED_SANDBOX
            
        if overall_status == CertificationStatus.CERTIFIED_FOR_CONTROLLED_LIVE:
            overall_status = CertificationStatus.NOT_CERTIFIED
            blocking_failures.append("FATAL: Attempted to reach CERTIFIED_FOR_CONTROLLED_LIVE in a restricted phase.")
            
        return LiveReadinessMatrix(
            environment=environment,
            overall_status=overall_status,
            checks=checks,
            evaluated_at=datetime.now(timezone.utc),
            blocking_failures=blocking_failures
        )

global_live_certification_engine = LiveCertificationEngine()
