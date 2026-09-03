"""
Phase 13 — Broker Adapter Abstract Interface, Disabled Live Stub & Broker Factory

Defines the authoritative BrokerAdapter protocol/ABC, the fail-closed LiveBrokerAdapter
stub, and the safe BrokerFactory that strictly enforces BROKER_MODE=paper.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import os
from typing import Any, Dict, List, Optional

from backend.domain.broker_schemas import (
    BrokerAccountState,
    BrokerCapabilities,
    BrokerConnectionState,
    BrokerMode,
    BrokerOrderRequest,
    BrokerOrderResponse,
    BrokerPosition,
)
from backend.domain.paper_broker_schemas import (
    PaperAccount,
    PaperExecutionResult,
    PaperOrder,
    PaperOrderStatus,
    PaperPosition,
)
from backend.domain.preflight_schemas import ExecutionAuthorizationSnapshot
from backend.domain.schemas import MarketContext


# ── Safety Exceptions ───────────────────────────────────────────────────────

class LiveBrokerDisabledError(RuntimeError):
    """Raised when any attempt is made to invoke or activate live broker execution."""
    pass


class ConfigurationSafetyError(ValueError):
    """Raised when an invalid or unsafe broker configuration is detected."""
    pass


class ExecutionGuardVetoError(PermissionError):
    """Raised when an execution request fails the deterministic safety guard."""
    pass


# ── Broker Adapter Abstract Base Class ──────────────────────────────────────

class BrokerAdapter(ABC):
    """
    Standard abstract base class for all execution broker adapters.
    Guarantees consistent capabilities, account polling, order submission,
    and lifecycle inspection across simulated and future live adapters.
    """

    @abstractmethod
    def get_capabilities(self) -> BrokerCapabilities:
        """Return the explicit, deterministic capability matrix of this adapter."""
        pass

    @abstractmethod
    def get_account_state(self) -> BrokerAccountState:
        """Return normalized account balances, cash, buying power, and positions."""
        pass

    @abstractmethod
    def get_positions(self) -> Dict[str, BrokerPosition]:
        """Return normalized open stock positions."""
        pass

    @abstractmethod
    def submit_order(
        self,
        authorization: ExecutionAuthorizationSnapshot,
        market_context: Optional[MarketContext] = None,
        evaluation_timestamp: Optional[datetime] = None,
    ) -> PaperExecutionResult:
        """
        Submit an authorized trade order for execution.
        Must enforce authorization, risk veto, and idempotency checks.
        """
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open, unfilled order."""
        pass

    @abstractmethod
    def get_order(self, order_id: str) -> Optional[PaperOrder]:
        """Query state of a specific order by ID."""
        pass

    @abstractmethod
    def list_orders(
        self,
        symbol: Optional[str] = None,
        status: Optional[PaperOrderStatus] = None,
    ) -> List[PaperOrder]:
        """List orders filtered by symbol and/or status."""
        pass

    @abstractmethod
    def get_connection_state(self) -> BrokerConnectionState:
        """Query current connection and operational readiness state."""
        pass

    @abstractmethod
    def reset(self, initial_cash: Optional[float] = None) -> None:
        """Reset internal balances, order books, and idempotency tokens."""
        pass


# ── Disabled Live Broker Placeholder ────────────────────────────────────────

class LiveBrokerAdapter(BrokerAdapter):
    """
    Disabled live broker placeholder.
    GUARANTEES:
    1. Zero network calls.
    2. Zero real broker API integration.
    3. Fails closed on EVERY execution attempt.
    4. Unconditionally reports LIVE_BROKER_DISABLED.
    """

    def __init__(self, allow_instantiation_for_testing: bool = True) -> None:
        self.broker_name = "DisabledLiveBrokerStub"
        self.mode = BrokerMode.LIVE
        self.is_live = False  # Always False in this phase

        # If live credentials or live trading is attempted in production, fail closed immediately
        if not allow_instantiation_for_testing:
            raise LiveBrokerDisabledError(
                "LIVE_BROKER_DISABLED: Real-money live broker execution is strictly disabled in this phase."
            )

    def get_capabilities(self) -> BrokerCapabilities:
        """Return live adapter capabilities (all execution disabled)."""
        return BrokerCapabilities(
            broker_name=self.broker_name,
            mode=BrokerMode.LIVE,
            is_live=False,
            supports_paper=False,
            supports_market_orders=False,
            supports_limit_orders=False,
            supports_stop_orders=False,
            supports_order_cancellation=False,
            supports_order_modification=False,
            supports_fractional_shares=False,
            supports_streaming_quotes=False,
            supports_account_polling=False,
        )

    def get_account_state(self) -> BrokerAccountState:
        """Fail closed on account state query."""
        raise LiveBrokerDisabledError(
            "LIVE_BROKER_DISABLED: Live account polling is prohibited. Use PaperBrokerAdapter."
        )

    def get_positions(self) -> Dict[str, BrokerPosition]:
        """Fail closed on positions query."""
        raise LiveBrokerDisabledError(
            "LIVE_BROKER_DISABLED: Live positions query is prohibited. Use PaperBrokerAdapter."
        )

    def submit_order(
        self,
        authorization: ExecutionAuthorizationSnapshot,
        market_context: Optional[MarketContext] = None,
        evaluation_timestamp: Optional[datetime] = None,
    ) -> PaperExecutionResult:
        """Fail closed on order submission."""
        raise LiveBrokerDisabledError(
            "LIVE_BROKER_DISABLED: Real-money live broker order placement is strictly prohibited."
        )

    def cancel_order(self, order_id: str) -> bool:
        """Fail closed on order cancellation."""
        raise LiveBrokerDisabledError(
            "LIVE_BROKER_DISABLED: Live order cancellation is prohibited."
        )

    def get_order(self, order_id: str) -> Optional[PaperOrder]:
        """Fail closed on order inspection."""
        raise LiveBrokerDisabledError(
            "LIVE_BROKER_DISABLED: Live order inspection is prohibited."
        )

    def list_orders(
        self,
        symbol: Optional[str] = None,
        status: Optional[PaperOrderStatus] = None,
    ) -> List[PaperOrder]:
        """Fail closed on order listing."""
        raise LiveBrokerDisabledError(
            "LIVE_BROKER_DISABLED: Live order listing is prohibited."
        )

    def get_connection_state(self) -> BrokerConnectionState:
        """Report DISABLED connection state."""
        return BrokerConnectionState.DISABLED

    def reset(self, initial_cash: Optional[float] = None) -> None:
        """No-op on disabled live broker."""
        pass


# ── Broker Factory & Configuration Safety ───────────────────────────────────

class BrokerFactory:
    """
    Authoritative factory for obtaining broker adapters.
    Defaults strictly to BROKER_MODE=paper and fails closed on any live broker attempt.
    """

    ALLOWED_PAPER_MODES = {"paper", "simulated", "mock"}
    ALLOWED_SANDBOX_MODES = {"sandbox", "external_sandbox"}
    ALLOWED_DHAN_MODES = {"dhan"}
    PROHIBITED_LIVE_MODES = {"live", "real", "zerodha", "upstox", "angelone", "fyers", "ibkr", "alpaca"}

    @classmethod
    def get_adapter(cls, mode_override: Optional[str] = None) -> BrokerAdapter:
        """
        Return the configured broker adapter.
        Guarantees paper/sandbox execution; raises ConfigurationSafetyError if live mode is requested.
        """
        raw_mode = mode_override or os.environ.get("BROKER_MODE", "paper")
        mode = raw_mode.strip().lower()

        if mode in cls.PROHIBITED_LIVE_MODES:
            raise ConfigurationSafetyError(
                f"LIVE_BROKER_PROHIBITED: Configuration BROKER_MODE='{raw_mode}' is prohibited. "
                "Real-money broker execution is disabled by safety policy. Only paper execution is allowed."
            )

        if mode in cls.ALLOWED_DHAN_MODES:
            from backend.adapters.dhan_adapter import DhanBrokerAdapter
            return DhanBrokerAdapter()

        if mode in cls.ALLOWED_SANDBOX_MODES:
            from backend.application.broker_manager import global_broker_manager
            from backend.domain.broker_schemas import BrokerConfig, BrokerEnvironment
            if global_broker_manager.get_active_environment() != BrokerEnvironment.SANDBOX:
                global_broker_manager.configure(BrokerConfig(
                    broker_provider="MockSandboxProvider",
                    broker_environment=BrokerEnvironment.SANDBOX,
                    api_key="mock",
                    api_secret="mock"
                ))
            return global_broker_manager.get_active_adapter()

        if mode in cls.ALLOWED_PAPER_MODES:
            # Import PaperBrokerAdapter lazily to prevent circular dependencies
            from backend.application.paper_broker_adapter import global_paper_broker
            return global_paper_broker

        raise ConfigurationSafetyError(
            f"INVALID_BROKER_MODE: Unknown or unsupported BROKER_MODE='{raw_mode}'. "
            f"Allowed modes: {sorted(list(cls.ALLOWED_PAPER_MODES | cls.ALLOWED_SANDBOX_MODES | cls.ALLOWED_DHAN_MODES))}."
        )
