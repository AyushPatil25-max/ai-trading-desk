"""
Phase 15 — Provider-Neutral Broker Manager

Central coordinator managing execution environments (PAPER vs. SANDBOX vs. LIVE),
provider selection, deterministic order routing, and fail-closed safety enforcement.
Ensures zero silent fallbacks, zero real-money live broker calls, and strict ExecutionGuard compliance.
"""

from datetime import datetime, timezone
import logging
import os
import threading
from typing import Any, Dict, Optional

from backend.domain.broker_schemas import (
    BrokerAccountState,
    BrokerCapabilities,
    BrokerConfig,
    BrokerConnectionState,
    BrokerEnvironment,
    BrokerManagerStatus,
    BrokerMode,
    BrokerRoutingMode,
)
from backend.domain.paper_broker_schemas import PaperExecutionResult
from backend.domain.preflight_schemas import ExecutionAuthorizationSnapshot
from backend.domain.schemas import MarketContext
from backend.domain.telemetry_schemas import EventSeverity, ExecutionEventType
from backend.application.broker_interface import (
    BrokerAdapter,
    ConfigurationSafetyError,
    LiveBrokerDisabledError,
)
from backend.application.paper_broker_adapter import (
    PaperBrokerAdapter,
    global_paper_broker,
)
from backend.application.sandbox_broker_adapter import SandboxBrokerAdapter
from backend.application.sandbox_client import MockSandboxClient, RestSandboxClient
from backend.application.execution_guard import ExecutionGuard, global_execution_guard

logger = logging.getLogger(__name__)


class BrokerManager:
    """
    Authoritative broker manager implementing the provider-neutral adapter pattern.
    Guarantees:
    1. PAPER -> routes exclusively to PaperBrokerAdapter (Internal simulation).
    2. SANDBOX -> routes exclusively to SandboxBrokerAdapter (External sandbox).
    3. LIVE -> HARD REJECT (Fails closed unconditionally).
    4. Zero silent fallback between environments.
    """

    def __init__(
        self,
        config: Optional[BrokerConfig] = None,
        paper_adapter: Optional[PaperBrokerAdapter] = None,
        sandbox_adapter: Optional[SandboxBrokerAdapter] = None,
        execution_guard: Optional[ExecutionGuard] = None,
        telemetry_engine: Optional[Any] = None,
    ) -> None:
        self._lock = threading.Lock()
        self.telemetry_engine = telemetry_engine
        self.execution_guard = execution_guard or global_execution_guard
        self.paper_adapter: PaperBrokerAdapter = paper_adapter or global_paper_broker
        self.sandbox_adapter: Optional[SandboxBrokerAdapter] = sandbox_adapter

        # Default configuration: PAPER environment
        self.config: BrokerConfig = config or BrokerConfig(
            broker_provider="PaperBroker",
            broker_environment=BrokerEnvironment.PAPER,
        )

        if self.config.broker_environment == BrokerEnvironment.SANDBOX and not self.sandbox_adapter:
            self._init_sandbox_adapter(self.config)

    # ── Configuration Management ──────────────────────────────────────────────

    def configure(self, config: BrokerConfig) -> None:
        """
        Configure the broker manager environment and provider.
        Fails closed with LiveBrokerDisabledError if LIVE is requested.
        """
        with self._lock:
            # 1. Reject LIVE environment explicitly
            if config.broker_environment == BrokerEnvironment.LIVE:
                if self.telemetry_engine:
                    self.telemetry_engine.record_event(
                        event_type=ExecutionEventType.LIVE_EXECUTION_BLOCKED,
                        execution_id="CONFIG",
                        symbol="SYSTEM",
                        reason="Attempt to configure LIVE broker environment blocked by safety policy.",
                        severity=EventSeverity.CRITICAL,
                    )
                raise LiveBrokerDisabledError(
                    "LIVE_BROKER_PROHIBITED: Live real-money trading is strictly disabled. "
                    "Only PAPER and SANDBOX environments are permitted."
                )

            # 2. Configure SANDBOX environment
            if config.broker_environment == BrokerEnvironment.SANDBOX:
                self._init_sandbox_adapter(config)
                self.config = config
                logger.info(f"[BrokerManager] Configured SANDBOX environment with provider '{config.broker_provider}'.")
                return

            # 3. Configure PAPER environment
            if config.broker_environment == BrokerEnvironment.PAPER:
                self.config = config
                logger.info("[BrokerManager] Configured PAPER environment (internal deterministic simulation).")
                return

            raise ConfigurationSafetyError(
                f"INVALID_ENVIRONMENT: Unknown broker environment '{config.broker_environment}'."
            )

    def _init_sandbox_adapter(self, config: BrokerConfig) -> None:
        """Initialize the appropriate sandbox client and adapter."""
        if config.base_url:
            client = RestSandboxClient(config)
        else:
            client = MockSandboxClient(provider_name=config.broker_provider)

        self.sandbox_adapter = SandboxBrokerAdapter(
            client=client,
            provider_name=config.broker_provider,
            telemetry_engine=self.telemetry_engine,
        )

    # ── Active Environment & Adapter Resolution ───────────────────────────────

    def get_active_environment(self) -> BrokerEnvironment:
        with self._lock:
            return self.config.broker_environment

    def get_routing_mode(self) -> BrokerRoutingMode:
        with self._lock:
            if self.config.broker_environment == BrokerEnvironment.PAPER:
                return BrokerRoutingMode.INTERNAL_PAPER
            elif self.config.broker_environment == BrokerEnvironment.SANDBOX:
                return BrokerRoutingMode.EXTERNAL_SANDBOX
            else:
                return BrokerRoutingMode.LIVE

    def get_active_adapter(self) -> BrokerAdapter:
        with self._lock:
            env = self.config.broker_environment
            if env == BrokerEnvironment.PAPER:
                return self.paper_adapter
            elif env == BrokerEnvironment.SANDBOX:
                if not self.sandbox_adapter:
                    self._init_sandbox_adapter(self.config)
                return self.sandbox_adapter
            else:
                raise LiveBrokerDisabledError("LIVE_BROKER_PROHIBITED: Live adapter execution is strictly disabled.")

    # ── Deterministic Order Routing ───────────────────────────────────────────

    def route_order(
        self,
        authorization: ExecutionAuthorizationSnapshot,
        market_context: Optional[MarketContext] = None,
        evaluation_timestamp: Optional[datetime] = None,
    ) -> PaperExecutionResult:
        """
        Deterministically route an authorized order through ExecutionGuard to the active adapter.
        Guarantees NO silent fallback from sandbox to paper, and NO live execution.
        """
        adapter = self.get_active_adapter()
        caps = adapter.get_capabilities()

        # Guard execution intercept
        outcome = self.execution_guard.validate_authorization(
            authorization=authorization,
            target_adapter_is_live=caps.is_live,
        )

        if not outcome.is_authorized:
            reason = outcome.rejection_reason or "EXECUTION_GUARD_REJECTION"
            logger.warning(f"[BrokerManager] Order submission vetoed by ExecutionGuard: {reason}")
            return self.execution_guard.guard_submission(
                target_adapter=adapter,
                authorization=authorization,
                market_context=market_context,
                evaluation_timestamp=evaluation_timestamp,
            )

        # Route exclusively to active adapter (NO silent fallback)
        return adapter.submit_order(
            authorization=authorization,
            market_context=market_context,
            evaluation_timestamp=evaluation_timestamp,
        )

    # ── Operational Status Summary ────────────────────────────────────────────

    def get_status_summary(self) -> BrokerManagerStatus:
        adapter = self.get_active_adapter()
        caps = adapter.get_capabilities()
        acct = adapter.get_account_state()
        conn = adapter.get_connection_state()

        return BrokerManagerStatus(
            active_environment=self.config.broker_environment,
            routing_mode=self.get_routing_mode(),
            active_adapter_name=caps.broker_name,
            broker_provider=self.config.broker_provider,
            connection_state=conn,
            is_live_blocked=True,
            capabilities=caps,
            account_summary=acct,
            last_reconciliation=None,
        )

    def reset(self, initial_cash: Optional[float] = None) -> None:
        with self._lock:
            self.paper_adapter.reset(initial_cash)
            if self.sandbox_adapter:
                self.sandbox_adapter.reset(initial_cash)


# Global singleton instance for system-wide broker management
global_broker_manager = BrokerManager()
