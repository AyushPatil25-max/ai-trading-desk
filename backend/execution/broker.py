"""
Broker Interface — Phase 5.1

Abstract base class for all broker implementations (paper broker and future live broker adapters).
Ensures clear separation between execution logic and specific broker APIs.
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional

from backend.domain.execution_schemas import (
    ExecutionResult,
    OrderRequest,
    OrderStatus,
    PortfolioState,
    Position,
)


class BrokerInterface(ABC):
    """
    Abstract interface for broker adapters.
    """

    @abstractmethod
    def submit_order(self, order: OrderRequest) -> ExecutionResult:
        """Submit an order for execution."""
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        pass

    @abstractmethod
    def get_order_status(self, order_id: str) -> Optional[OrderStatus]:
        """Query current status of an order."""
        pass

    @abstractmethod
    def get_positions(self) -> Dict[str, Position]:
        """Return current portfolio positions."""
        pass

    @abstractmethod
    def get_account_state(self) -> PortfolioState:
        """Return full portfolio and cash state."""
        pass
