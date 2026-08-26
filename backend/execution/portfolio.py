"""
Paper Portfolio Engine — Phase 5.1

Deterministic tracking of simulated cash, positions, cost basis, realized/unrealized P&L,
and portfolio exposure.
"""

from datetime import datetime
from typing import Dict, Optional
import uuid

from backend.domain.execution_schemas import (
    ExecutionResult,
    OrderSide,
    OrderStatus,
    PortfolioState,
    Position,
)


class PaperPortfolio:
    """
    In-memory deterministic portfolio engine for paper trading.
    """

    def __init__(self, initial_cash: float = 100000.0, portfolio_id: Optional[str] = None) -> None:
        self.portfolio_id = portfolio_id or f"port-{uuid.uuid4().hex[:8]}"
        self.initial_cash = float(initial_cash)
        self.cash = float(initial_cash)
        self.positions: Dict[str, Position] = {}
        self.realized_pnl: float = 0.0
        self.daily_realized_pnl: float = 0.0
        self.updated_at: datetime = datetime.utcnow()

    def get_position(self, symbol: str) -> Optional[Position]:
        """Return the position for a given symbol, if open."""
        pos = self.positions.get(symbol)
        if pos and pos.quantity > 0:
            return pos
        return None

    def update_price(self, symbol: str, current_price: float) -> None:
        """Update market price for an existing position and recalculate metrics."""
        if symbol in self.positions and self.positions[symbol].quantity > 0:
            pos = self.positions[symbol]
            pos.current_price = float(current_price)
            pos.market_value = pos.quantity * pos.current_price
            pos.unrealized_pnl = (pos.current_price - pos.average_price) * pos.quantity
            pos.updated_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def apply_execution(self, execution: ExecutionResult) -> None:
        """
        Apply a confirmed execution result to the portfolio state deterministically.
        """
        if execution.status not in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
            return

        symbol = execution.symbol
        qty = float(execution.quantity_filled)
        price = float(execution.fill_price)
        commission = float(execution.commission)

        if execution.side == OrderSide.BUY:
            total_cost = (qty * price) + commission
            self.cash -= total_cost

            if symbol not in self.positions:
                self.positions[symbol] = Position(
                    symbol=symbol,
                    quantity=qty,
                    average_price=price,
                    current_price=price,
                    market_value=qty * price,
                    unrealized_pnl=0.0,
                    realized_pnl=0.0,
                    updated_at=datetime.utcnow(),
                )
            else:
                pos = self.positions[symbol]
                old_qty = pos.quantity
                old_cost = old_qty * pos.average_price
                new_qty = old_qty + qty
                new_cost = old_cost + (qty * price)
                new_avg_price = new_cost / new_qty if new_qty > 0 else 0.0

                pos.quantity = new_qty
                pos.average_price = new_avg_price
                pos.current_price = price
                pos.market_value = new_qty * price
                pos.unrealized_pnl = (price - new_avg_price) * new_qty
                pos.updated_at = datetime.utcnow()

        elif execution.side == OrderSide.SELL:
            proceeds = (qty * price) - commission
            self.cash += proceeds

            if symbol in self.positions:
                pos = self.positions[symbol]
                old_qty = pos.quantity
                sold_qty = min(old_qty, qty)
                trade_realized_pnl = (price - pos.average_price) * sold_qty - commission

                pos.realized_pnl += trade_realized_pnl
                self.realized_pnl += trade_realized_pnl
                self.daily_realized_pnl += trade_realized_pnl

                new_qty = max(0.0, old_qty - sold_qty)
                pos.quantity = new_qty
                pos.current_price = price
                pos.market_value = new_qty * price
                pos.unrealized_pnl = (price - pos.average_price) * new_qty if new_qty > 0 else 0.0
                pos.updated_at = datetime.utcnow()

                if new_qty == 0.0:
                    del self.positions[symbol]

        self.updated_at = datetime.utcnow()

    def get_state(self) -> PortfolioState:
        """Calculate and return the complete portfolio snapshot."""
        total_market_value = sum(
            p.market_value for p in self.positions.values() if p.quantity > 0
        )
        total_unrealized_pnl = sum(
            p.unrealized_pnl for p in self.positions.values() if p.quantity > 0
        )
        total_equity = self.cash + total_market_value
        exposure = (total_market_value / total_equity) if total_equity > 0 else 0.0

        return PortfolioState(
            portfolio_id=self.portfolio_id,
            initial_cash=self.initial_cash,
            cash=self.cash,
            available_cash=max(0.0, self.cash),
            positions={k: v.model_copy() for k, v in self.positions.items() if v.quantity > 0},
            total_market_value=total_market_value,
            total_equity=total_equity,
            realized_pnl=self.realized_pnl,
            unrealized_pnl=total_unrealized_pnl,
            total_exposure=exposure,
            daily_realized_pnl=self.daily_realized_pnl,
            updated_at=self.updated_at,
        )

    def reset(self, initial_cash: Optional[float] = None) -> None:
        """Reset the portfolio back to initial cash with no open positions."""
        if initial_cash is not None:
            self.initial_cash = float(initial_cash)
        self.cash = self.initial_cash
        self.positions.clear()
        self.realized_pnl = 0.0
        self.daily_realized_pnl = 0.0
        self.updated_at = datetime.utcnow()
