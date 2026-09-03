"""
Paper Broker — Phase 5.1

Offline deterministic simulated broker for testing order execution, portfolio tracking,
and safety constraints without live broker connections or real money.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional
import uuid

from backend.domain.execution_schemas import (
    ExecutionDecision,
    ExecutionResult,
    OrderRequest,
    OrderSide,
    OrderStatus,
    PortfolioState,
    Position,
)
from backend.domain.investment_committee_schemas import InvestmentDecision
from backend.domain.schemas import MarketContext
from backend.execution.audit import ExecutionAuditManager
from backend.execution.broker import BrokerInterface
from backend.execution.portfolio import PaperPortfolio
from backend.execution.safety_engine import ExecutionSafetyEngine


class PaperBroker(BrokerInterface):
    """
    Simulated broker engine enforcing deterministic execution and safety rules.
    """

    DEFAULT_COMMISSION_RATE = 0.0003  # 0.03% standard Indian equity broker fee
    DEFAULT_SLIPPAGE_RATE = 0.0       # Configurable slippage rate

    def __init__(
        self,
        initial_cash: float = 100000.0,
        commission_rate: float = DEFAULT_COMMISSION_RATE,
        slippage_rate: float = DEFAULT_SLIPPAGE_RATE,
        transaction_fee_flat: float = 0.0,
        safety_engine: Optional[ExecutionSafetyEngine] = None,
        audit_manager: Optional[ExecutionAuditManager] = None,
        portfolio: Optional[PaperPortfolio] = None,
    ) -> None:
        self.commission_rate = float(commission_rate)
        self.slippage_rate = float(slippage_rate)
        self.transaction_fee_flat = float(transaction_fee_flat)
        self.portfolio = portfolio or PaperPortfolio(initial_cash=initial_cash)
        self.safety_engine = safety_engine or ExecutionSafetyEngine()
        self.audit_manager = audit_manager or ExecutionAuditManager()
        self._orders: Dict[str, OrderRequest] = {}
        self._executions: Dict[str, ExecutionResult] = {}

    def submit_order(
        self,
        order: OrderRequest,
        market_context: Optional[MarketContext] = None,
        decision: Optional[InvestmentDecision] = None,
    ) -> ExecutionResult:
        """
        Validate and execute an order request against the paper portfolio.
        """
        self._orders[order.order_id] = order
        current_state = self.portfolio.get_state()

        # Run safety evaluation
        validation = self.safety_engine.evaluate_order(
            order=order,
            portfolio_state=current_state,
            market_context=market_context,
            decision=decision,
        )

        exec_id = f"exec-{uuid.uuid4().hex[:8]}"

        if not validation.is_valid:
            # Order rejected by safety engine
            status = (
                OrderStatus.FAILED
                if validation.decision == ExecutionDecision.REQUIRES_REVALIDATION
                else OrderStatus.REJECTED
            )
            error_msg = "; ".join(validation.rejection_details)

            result = ExecutionResult(
                execution_id=exec_id,
                order_id=order.order_id,
                symbol=order.symbol,
                side=order.side,
                quantity_requested=order.quantity,
                quantity_filled=0.0,
                fill_price=0.0,
                status=status,
                executed_at=datetime.now(timezone.utc),
                total_cost=0.0,
                commission=0.0,
                context_id=order.context_id,
                run_id=order.run_id,
                error_message=error_msg,
            )

            self._executions[order.order_id] = result
            self.audit_manager.record(
                order=order,
                validation=validation,
                execution=result,
                kill_switch_active=self.safety_engine.kill_switch.is_active(),
            )
            return result

        # Deterministic fill simulation with slippage
        if order.side == OrderSide.BUY:
            fill_price = order.price * (1.0 + self.slippage_rate)
        else:
            fill_price = order.price * (1.0 - self.slippage_rate)

        commission = (order.quantity * fill_price * self.commission_rate) + self.transaction_fee_flat
        total_cost = (order.quantity * fill_price) + commission

        result = ExecutionResult(
            execution_id=exec_id,
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity_requested=order.quantity,
            quantity_filled=order.quantity,
            fill_price=fill_price,
            status=OrderStatus.FILLED,
            executed_at=datetime.now(timezone.utc),
            total_cost=total_cost,
            commission=commission,
            context_id=order.context_id,
            run_id=order.run_id,
            error_message=None,
        )

        self._executions[order.order_id] = result

        # Apply to portfolio
        self.portfolio.apply_execution(result)

        # Record in duplicate tracker to prevent identical re-execution
        self.safety_engine.duplicate_tracker.record_order(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            context_id=order.context_id,
            run_id=order.run_id,
        )

        # Log audit trail
        self.audit_manager.record(
            order=order,
            validation=validation,
            execution=result,
            kill_switch_active=self.safety_engine.kill_switch.is_active(),
        )

        return result

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order. In this simple market-order paper broker, orders fill instantly or reject."""
        if order_id in self._orders:
            exec_res = self._executions.get(order_id)
            if exec_res and exec_res.status == OrderStatus.SUBMITTED:
                exec_res.status = OrderStatus.CANCELLED
                return True
        return False

    def get_order_status(self, order_id: str) -> Optional[OrderStatus]:
        """Query status of a submitted order."""
        exec_res = self._executions.get(order_id)
        if exec_res:
            return exec_res.status
        return None

    def get_positions(self) -> Dict[str, Position]:
        """Get copy of all active open positions."""
        return self.portfolio.get_state().positions

    def get_account_state(self) -> PortfolioState:
        """Get full current account state."""
        return self.portfolio.get_state()

    def reset(self, initial_cash: Optional[float] = None) -> None:
        """Reset broker portfolio, duplicate tracker, and order history."""
        self.portfolio.reset(initial_cash=initial_cash)
        self.safety_engine.duplicate_tracker.clear()
        self._orders.clear()
        self._executions.clear()
