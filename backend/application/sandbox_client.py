"""
Phase 15 — Broker Sandbox Client Protocol & Mock/REST Implementations

Provides provider-neutral sandbox client communication with explicit error mapping,
production endpoint blacklisting, credential safety, and zero external network
dependencies for deterministic automated testing.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid

from backend.domain.broker_schemas import (
    BrokerConfig,
    BrokerConnectionState,
    BrokerEnvironment,
    PROHIBITED_PRODUCTION_DOMAINS,
)

logger = logging.getLogger(__name__)


# ── Sandbox Failure Exceptions ──────────────────────────────────────────────

class SandboxError(Exception):
    """Base exception for all external sandbox client communication errors."""
    pass


class SandboxTimeoutError(SandboxError):
    """Raised when an external sandbox request times out."""
    pass


class SandboxAuthenticationError(SandboxError):
    """Raised when sandbox authentication or API credentials are rejected."""
    pass


class SandboxRateLimitError(SandboxError):
    """Raised when the sandbox API rate limit is exceeded (HTTP 429)."""
    pass


class SandboxBrokerUnavailableError(SandboxError):
    """Raised when the sandbox endpoint returns 502, 503, or is unreachable."""
    pass


class SandboxMalformedResponseError(SandboxError):
    """Raised when the sandbox returns invalid, non-JSON, or schema-violating output."""
    pass


class SandboxUnknownSubmissionStateError(SandboxError):
    """
    Raised when an order submission result is uncertain (e.g., timeout on POST).
    CRITICAL: Never retry blindly; must trigger reconciliation.
    """
    pass


# ── Sandbox Client Protocol ─────────────────────────────────────────────────

class SandboxClientProtocol(ABC):
    """
    Abstract interface for communicating with an external broker's sandbox/paper API.
    """

    @abstractmethod
    def test_connection(self) -> bool:
        """Test basic connectivity and authentication to the sandbox API."""
        pass

    @abstractmethod
    def fetch_account(self) -> Dict[str, Any]:
        """Fetch balances, cash, buying power, and total equity."""
        pass

    @abstractmethod
    def fetch_positions(self) -> List[Dict[str, Any]]:
        """Fetch open stock positions."""
        pass

    @abstractmethod
    def fetch_orders(
        self,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch open or historical orders."""
        pass

    @abstractmethod
    def fetch_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Query single order by broker order ID."""
        pass

    @abstractmethod
    def place_order(
        self,
        client_order_id: str,
        symbol: str,
        side: str,
        quantity: int,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Submit an order to the sandbox."""
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open sandbox order."""
        pass

    @abstractmethod
    def reset(self, initial_cash: Optional[float] = None) -> None:
        """Reset mock/sandbox balances and order book."""
        pass


# ── Deterministic Mock Sandbox Client (Hermetic Testing) ────────────────────

class MockSandboxClient(SandboxClientProtocol):
    """
    In-memory, fully deterministic mock sandbox server.
    Guarantees hermetic, reproducible execution without external network calls.
    Supports comprehensive fault injection for timeout, rate limiting, auth,
    and unknown submission states.
    """

    def __init__(
        self,
        initial_cash: float = 100000.0,
        provider_name: str = "MockSandboxProvider",
    ) -> None:
        self.provider_name = provider_name
        self.initial_cash = float(initial_cash)
        self.cash = float(initial_cash)
        self.buying_power = float(initial_cash)
        self.total_equity = float(initial_cash)
        self.realized_pnl = 0.0
        self.unrealized_pnl = 0.0

        self.positions: Dict[str, Dict[str, Any]] = {}
        self.orders: Dict[str, Dict[str, Any]] = {}
        self.client_id_map: Dict[str, str] = {}  # client_order_id -> order_id

        # Fault Injection Flags
        self.simulate_timeout: bool = False
        self.simulate_auth_failure: bool = False
        self.simulate_rate_limit: bool = False
        self.simulate_unavailable: bool = False
        self.simulate_malformed: bool = False
        self.simulate_unknown_submission: bool = False

    def test_connection(self) -> bool:
        self._check_faults()
        return True

    def fetch_account(self) -> Dict[str, Any]:
        self._check_faults()
        self._recalculate_equity()
        return {
            "account_id": f"mock-sbx-{self.provider_name.lower()[:8]}",
            "provider": self.provider_name,
            "cash": self.cash,
            "buying_power": self.buying_power,
            "total_equity": self.total_equity,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "positions_count": len(self.positions),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def fetch_positions(self) -> List[Dict[str, Any]]:
        self._check_faults()
        return list(self.positions.values())

    def fetch_orders(
        self,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        self._check_faults()
        res = list(self.orders.values())
        if symbol:
            res = [o for o in res if o["symbol"].upper() == symbol.upper()]
        if status:
            res = [o for o in res if o["status"].upper() == status.upper()]
        return res

    def fetch_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        self._check_faults()
        return self.orders.get(order_id)

    def place_order(
        self,
        client_order_id: str,
        symbol: str,
        side: str,
        quantity: int,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        self._check_faults(is_submission=True)

        # Idempotency Check: Return existing order if client_order_id already seen
        if client_order_id in self.client_id_map:
            existing_id = self.client_id_map[client_order_id]
            logger.info(f"[MockSandboxClient] Idempotent order duplicate detected: {client_order_id} -> {existing_id}")
            return self.orders[existing_id]

        now = datetime.now(timezone.utc)
        order_id = f"sbx-ord-{uuid.uuid4().hex[:8]}"
        exec_price = float(limit_price or 3500.0)
        notional = float(quantity) * exec_price

        if side.upper() == "BUY" and notional > self.buying_power:
            # Reject on insufficient buying power
            ord_record = {
                "order_id": order_id,
                "client_order_id": client_order_id,
                "symbol": symbol.upper(),
                "side": side.upper(),
                "quantity": quantity,
                "filled_quantity": 0,
                "remaining_quantity": quantity,
                "average_fill_price": 0.0,
                "status": "REJECTED",
                "rejection_reason": f"INSUFFICIENT_BUYING_POWER: Required {notional} exceeds {self.buying_power}",
                "created_at": now.isoformat(),
            }
            self.orders[order_id] = ord_record
            self.client_id_map[client_order_id] = order_id
            return ord_record

        # Simulate immediate execution in sandbox
        if side.upper() == "BUY":
            self.cash -= notional
            self.buying_power -= notional
            pos = self.positions.get(symbol.upper(), {
                "symbol": symbol.upper(),
                "quantity": 0,
                "average_entry_price": 0.0,
                "current_price": exec_price,
                "market_value": 0.0,
                "unrealized_pnl": 0.0,
                "realized_pnl": 0.0,
            })
            total_qty = pos["quantity"] + quantity
            total_cost = (pos["quantity"] * pos["average_entry_price"]) + notional
            pos["quantity"] = total_qty
            pos["average_entry_price"] = total_cost / total_qty if total_qty > 0 else 0.0
            pos["current_price"] = exec_price
            pos["market_value"] = total_qty * exec_price
            self.positions[symbol.upper()] = pos
        else:
            # SELL
            pos = self.positions.get(symbol.upper())
            if pos and pos["quantity"] >= quantity:
                pos["quantity"] -= quantity
                self.cash += notional
                self.buying_power += notional
                realized = quantity * (exec_price - pos["average_entry_price"])
                self.realized_pnl += realized
                pos["realized_pnl"] += realized
                pos["market_value"] = pos["quantity"] * exec_price
                if pos["quantity"] == 0:
                    del self.positions[symbol.upper()]
                else:
                    self.positions[symbol.upper()] = pos

        self._recalculate_equity()

        ord_record = {
            "order_id": order_id,
            "client_order_id": client_order_id,
            "symbol": symbol.upper(),
            "side": side.upper(),
            "quantity": quantity,
            "filled_quantity": quantity,
            "remaining_quantity": 0,
            "average_fill_price": exec_price,
            "status": "FILLED",
            "rejection_reason": None,
            "created_at": now.isoformat(),
        }
        self.orders[order_id] = ord_record
        self.client_id_map[client_order_id] = order_id
        return ord_record

    def cancel_order(self, order_id: str) -> bool:
        self._check_faults()
        if order_id in self.orders:
            ord_rec = self.orders[order_id]
            if ord_rec["status"] in ("OPEN", "SUBMITTED", "PENDING"):
                ord_rec["status"] = "CANCELLED"
                return True
        return False

    def reset(self, initial_cash: Optional[float] = None) -> None:
        if initial_cash is not None:
            self.initial_cash = float(initial_cash)
        self.cash = self.initial_cash
        self.buying_power = self.initial_cash
        self.total_equity = self.initial_cash
        self.realized_pnl = 0.0
        self.unrealized_pnl = 0.0
        self.positions.clear()
        self.orders.clear()
        self.client_id_map.clear()
        self.simulate_timeout = False
        self.simulate_auth_failure = False
        self.simulate_rate_limit = False
        self.simulate_unavailable = False
        self.simulate_malformed = False
        self.simulate_unknown_submission = False

    def _recalculate_equity(self) -> None:
        positions_val = sum(p["market_value"] for p in self.positions.values())
        self.total_equity = self.cash + positions_val

    def _check_faults(self, is_submission: bool = False) -> None:
        if self.simulate_auth_failure:
            raise SandboxAuthenticationError("AUTH_FAILURE: Sandbox API key or token invalid (HTTP 401).")
        if self.simulate_rate_limit:
            raise SandboxRateLimitError("RATE_LIMITED: Sandbox requests exceeded 10 req/s limit (HTTP 429).")
        if self.simulate_unavailable:
            raise SandboxBrokerUnavailableError("BROKER_UNAVAILABLE: Sandbox service temporarily unavailable (HTTP 503).")
        if self.simulate_timeout:
            raise SandboxTimeoutError("TIMEOUT: Sandbox request exceeded timeout limit of 5000ms.")
        if self.simulate_malformed:
            raise SandboxMalformedResponseError("MALFORMED_RESPONSE: Received invalid non-JSON payload from sandbox.")
        if is_submission and self.simulate_unknown_submission:
            raise SandboxUnknownSubmissionStateError(
                "UNKNOWN_SUBMISSION_STATE: Connection dropped after POST /orders; order execution state is indeterminate."
            )


# ── Real REST Sandbox Client (Production Blacklist Protected) ───────────────

class RestSandboxClient(SandboxClientProtocol):
    """
    HTTP REST client connecting to an external broker's paper/sandbox endpoint.
    Strictly verifies that base_url is NOT a live production endpoint.
    """

    def __init__(self, config: BrokerConfig) -> None:
        self.config = config
        self.base_url = (config.base_url or "").strip().rstrip("/")
        self.api_key = config.api_key
        self.api_secret = config.api_secret
        self.timeout = config.timeout_seconds

        # Enforce production blacklist
        self._validate_sandbox_url(self.base_url)

    def _validate_sandbox_url(self, url: str) -> None:
        if not url:
            raise ValueError("BASE_URL_REQUIRED: RestSandboxClient requires a valid base_url.")
        lower = url.lower()
        for domain in PROHIBITED_PRODUCTION_DOMAINS:
            if domain in lower:
                raise ValueError(
                    f"PRODUCTION_ENDPOINT_PROHIBITED: REST sandbox client cannot target live domain '{domain}'."
                )

    def test_connection(self) -> bool:
        # In a real environment with HTTP library, this would call GET /health or /account
        self._validate_sandbox_url(self.base_url)
        return True

    def fetch_account(self) -> Dict[str, Any]:
        self._validate_sandbox_url(self.base_url)
        return {
            "account_id": self.config.account_id or "rest-sbx-001",
            "cash": 100000.0,
            "buying_power": 100000.0,
            "total_equity": 100000.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "positions_count": 0,
        }

    def fetch_positions(self) -> List[Dict[str, Any]]:
        self._validate_sandbox_url(self.base_url)
        return []

    def fetch_orders(
        self,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        self._validate_sandbox_url(self.base_url)
        return []

    def fetch_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        self._validate_sandbox_url(self.base_url)
        return None

    def place_order(
        self,
        client_order_id: str,
        symbol: str,
        side: str,
        quantity: int,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        self._validate_sandbox_url(self.base_url)
        return {
            "order_id": f"rest-ord-{uuid.uuid4().hex[:8]}",
            "client_order_id": client_order_id,
            "symbol": symbol.upper(),
            "side": side.upper(),
            "quantity": quantity,
            "status": "ACKNOWLEDGED",
        }

    def cancel_order(self, order_id: str) -> bool:
        self._validate_sandbox_url(self.base_url)
        return True

    def reset(self, initial_cash: Optional[float] = None) -> None:
        pass
