"""
Execution Package — Phase 5.1

Paper trading, deterministic execution safety, risk controls, and portfolio tracking.
"""

from backend.domain.execution_schemas import (
    ExecutionAuditRecord,
    ExecutionDecision,
    ExecutionResult,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    OrderValidationResult,
    PortfolioState,
    Position,
    RejectionReason,
    RiskLimits,
)
from backend.execution.audit import ExecutionAuditManager
from backend.execution.broker import BrokerInterface
from backend.execution.order_validator import OrderValidator
from backend.execution.paper_broker import PaperBroker
from backend.execution.portfolio import PaperPortfolio
from backend.execution.safety_engine import (
    DuplicateTracker,
    ExecutionSafetyEngine,
    KillSwitch,
)

__all__ = [
    "BrokerInterface",
    "DuplicateTracker",
    "ExecutionAuditManager",
    "ExecutionAuditRecord",
    "ExecutionDecision",
    "ExecutionResult",
    "ExecutionSafetyEngine",
    "KillSwitch",
    "OrderRequest",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "OrderValidationResult",
    "OrderValidator",
    "PaperBroker",
    "PaperPortfolio",
    "PortfolioState",
    "Position",
    "RejectionReason",
    "RiskLimits",
]
