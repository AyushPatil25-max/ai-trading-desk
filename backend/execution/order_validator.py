"""
Order Validator — Phase 5.1

Pure-Python deterministic validation engine for trade orders against risk limits,
portfolio state, data freshness, and Investment Committee decisions.
"""

from datetime import datetime, timezone
import json
import os
from typing import List, Optional

from backend.domain.execution_schemas import (
    ExecutionDecision,
    OrderRequest,
    OrderSide,
    OrderValidationResult,
    PortfolioState,
    RejectionReason,
    RiskLimits,
)
from backend.domain.investment_committee_schemas import (
    InvestmentDecision,
    InvestmentDecisionState,
)
from backend.domain.schemas import DataQualityStatus, MarketContext

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "execution_risk_config.json")


class OrderValidator:
    """
    Evaluates order requests against deterministic risk boundaries and market context.
    """

    def __init__(self, risk_limits: Optional[RiskLimits] = None, config_path: str = CONFIG_PATH) -> None:
        if risk_limits is not None:
            self.risk_limits = risk_limits
        else:
            self.risk_limits = self._load_risk_limits(config_path)

    def _load_risk_limits(self, config_path: str) -> RiskLimits:
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return RiskLimits(**data.get("risk_limits", {}))
            except Exception:
                pass
        return RiskLimits()

    def validate(
        self,
        order: OrderRequest,
        portfolio_state: PortfolioState,
        market_context: Optional[MarketContext] = None,
        decision: Optional[InvestmentDecision] = None,
    ) -> OrderValidationResult:
        """
        Run complete deterministic validation sequence.
        """
        rejection_reasons: List[RejectionReason] = []
        rejection_details: List[str] = []
        checks_passed: List[str] = []
        checks_failed: List[str] = []
        requires_revalidation = False

        # 1. Symbol Validation
        if not order.symbol or not isinstance(order.symbol, str) or len(order.symbol.strip()) == 0:
            rejection_reasons.append(RejectionReason.UNKNOWN)
            rejection_details.append("Invalid or empty symbol")
            checks_failed.append("Symbol validation")
        else:
            checks_passed.append("Symbol validation")

        # 2. Quantity & Price Validation
        if order.quantity <= 0 or not isinstance(order.quantity, (int, float)):
            rejection_reasons.append(RejectionReason.INVALID_QUANTITY)
            rejection_details.append(f"Quantity must be > 0, got {order.quantity}")
            checks_failed.append("Quantity validation")
        else:
            checks_passed.append("Quantity validation")

        if order.price <= 0 or not isinstance(order.price, (int, float)):
            rejection_reasons.append(RejectionReason.INVALID_PRICE)
            rejection_details.append(f"Price must be > 0, got {order.price}")
            checks_failed.append("Price validation")
        else:
            checks_passed.append("Price validation")

        # 3. Context ID and Provenance
        if not order.context_id or len(order.context_id.strip()) == 0:
            rejection_reasons.append(RejectionReason.UNKNOWN)
            rejection_details.append("Missing context_id in order request")
            checks_failed.append("Context ID check")
        elif market_context and order.context_id != market_context.context_id:
            rejection_reasons.append(RejectionReason.UNKNOWN)
            rejection_details.append(
                f"Order context_id '{order.context_id}' mismatch with MarketContext '{market_context.context_id}'"
            )
            checks_failed.append("Context ID check")
        else:
            checks_passed.append("Context ID check")

        # 4. Committee Decision Checks
        if decision is not None:
            if decision.state == InvestmentDecisionState.RISK_VETO:
                rejection_reasons.append(RejectionReason.RISK_VETO)
                rejection_details.append("Investment Committee triggered RISK_VETO")
                checks_failed.append("Committee decision state")
            elif decision.state == InvestmentDecisionState.DATA_QUALITY_VETO:
                rejection_reasons.append(RejectionReason.DATA_QUALITY)
                rejection_details.append("Investment Committee triggered DATA_QUALITY_VETO")
                checks_failed.append("Committee decision state")
            elif decision.state == InvestmentDecisionState.INSUFFICIENT_EVIDENCE:
                rejection_reasons.append(RejectionReason.INSUFFICIENT_EVIDENCE)
                rejection_details.append("Investment Committee marked INSUFFICIENT_EVIDENCE")
                checks_failed.append("Committee decision state")
            elif decision.state == InvestmentDecisionState.REJECT:
                rejection_reasons.append(RejectionReason.COMMITTEE_REJECT)
                rejection_details.append("Investment Committee marked REJECT")
                checks_failed.append("Committee decision state")
            elif decision.state == InvestmentDecisionState.HOLD:
                rejection_reasons.append(RejectionReason.COMMITTEE_REJECT)
                rejection_details.append("Investment Committee marked HOLD (non-executable)")
                checks_failed.append("Committee decision state")
            elif decision.state == InvestmentDecisionState.APPROVE:
                checks_passed.append("Committee decision state")
            else:
                rejection_reasons.append(RejectionReason.COMMITTEE_REJECT)
                rejection_details.append(f"Non-executable decision state '{decision.state}'")
                checks_failed.append("Committee decision state")

            # Confidence check
            if decision.confidence < self.risk_limits.minimum_confidence:
                rejection_reasons.append(RejectionReason.RISK_LIMIT)
                rejection_details.append(
                    f"Decision confidence {decision.confidence:.2f} below threshold {self.risk_limits.minimum_confidence:.2f}"
                )
                checks_failed.append("Minimum confidence check")
            else:
                checks_passed.append("Minimum confidence check")

        # 5. Market Context Data Quality and Freshness
        if market_context is not None:
            if market_context.quality_status == DataQualityStatus.CRITICAL_FAILURE:
                rejection_reasons.append(RejectionReason.DATA_QUALITY)
                rejection_details.append("MarketContext quality_status is CRITICAL_FAILURE")
                checks_failed.append("Market data quality")
            else:
                checks_passed.append("Market data quality")

            # Staleness check
            ref = order.created_at or datetime.now(timezone.utc)
            norm_ref = ref.replace(tzinfo=timezone.utc) if not ref.tzinfo else ref
            data_ts = market_context.data_timestamp
            norm_data_ts = data_ts.replace(tzinfo=timezone.utc) if not data_ts.tzinfo else data_ts
            context_age = (norm_ref - norm_data_ts).total_seconds()
            if context_age > self.risk_limits.maximum_context_age_seconds:
                rejection_reasons.append(RejectionReason.STALE_DATA)
                rejection_details.append(
                    f"MarketContext data is stale (age {context_age:.1f}s > max {self.risk_limits.maximum_context_age_seconds:.1f}s)"
                )
                checks_failed.append("Context freshness check")
                requires_revalidation = True
            else:
                checks_passed.append("Context freshness check")

        # 6. Daily Loss Limit Check
        if portfolio_state.daily_realized_pnl < -abs(self.risk_limits.max_daily_loss):
            rejection_reasons.append(RejectionReason.DAILY_LOSS_LIMIT)
            rejection_details.append(
                f"Daily loss limit breached: {portfolio_state.daily_realized_pnl:.2f} < -{self.risk_limits.max_daily_loss:.2f}"
            )
            checks_failed.append("Daily loss limit")
        else:
            checks_passed.append("Daily loss limit")

        # 7. Order Value Limits
        order_value = order.quantity * order.price
        if order_value > self.risk_limits.max_order_value:
            rejection_reasons.append(RejectionReason.RISK_LIMIT)
            rejection_details.append(
                f"Order value {order_value:.2f} exceeds max_order_value {self.risk_limits.max_order_value:.2f}"
            )
            checks_failed.append("Max order value check")
        else:
            checks_passed.append("Max order value check")

        # 8. Side-Specific Checks (BUY vs SELL)
        current_pos = portfolio_state.positions.get(order.symbol)
        current_pos_qty = current_pos.quantity if current_pos else 0.0
        current_pos_val = current_pos.market_value if current_pos else 0.0

        if order.side == OrderSide.BUY:
            # Cash sufficiency
            if order_value > portfolio_state.available_cash:
                rejection_reasons.append(RejectionReason.INSUFFICIENT_CASH)
                rejection_details.append(
                    f"Insufficient cash: required {order_value:.2f} > available {portfolio_state.available_cash:.2f}"
                )
                checks_failed.append("Cash sufficiency check")
            else:
                checks_passed.append("Cash sufficiency check")

            # Position Value Limit
            new_pos_value = current_pos_val + order_value
            if new_pos_value > self.risk_limits.max_position_value:
                rejection_reasons.append(RejectionReason.POSITION_LIMIT)
                rejection_details.append(
                    f"Projected position value {new_pos_value:.2f} exceeds max_position_value {self.risk_limits.max_position_value:.2f}"
                )
                checks_failed.append("Position value limit check")
            else:
                checks_passed.append("Position value limit check")

            # Single Symbol Exposure Limit
            total_equity = portfolio_state.total_equity if portfolio_state.total_equity > 0 else portfolio_state.cash
            if total_equity > 0:
                symbol_exposure = new_pos_value / total_equity
                if symbol_exposure > self.risk_limits.max_single_symbol_exposure:
                    rejection_reasons.append(RejectionReason.POSITION_LIMIT)
                    rejection_details.append(
                        f"Projected symbol exposure {symbol_exposure:.1%} exceeds max {self.risk_limits.max_single_symbol_exposure:.1%}"
                    )
                    checks_failed.append("Single symbol exposure check")
                else:
                    checks_passed.append("Single symbol exposure check")

            # Total Portfolio Exposure Limit
            new_total_market_val = portfolio_state.total_market_value + order_value
            if total_equity > 0:
                portfolio_exposure = new_total_market_val / total_equity
                if portfolio_exposure > self.risk_limits.max_portfolio_exposure:
                    rejection_reasons.append(RejectionReason.RISK_LIMIT)
                    rejection_details.append(
                        f"Projected portfolio exposure {portfolio_exposure:.1%} exceeds max {self.risk_limits.max_portfolio_exposure:.1%}"
                    )
                    checks_failed.append("Portfolio exposure check")
                else:
                    checks_passed.append("Portfolio exposure check")

        elif order.side == OrderSide.SELL:
            # Position sufficiency (long-only validation)
            if order.quantity > current_pos_qty:
                rejection_reasons.append(RejectionReason.INSUFFICIENT_POSITION)
                rejection_details.append(
                    f"Insufficient position to sell: required {order.quantity} > owned {current_pos_qty}"
                )
                checks_failed.append("Position sufficiency check")
            else:
                checks_passed.append("Position sufficiency check")

        # 9. Final Decision Assembly
        is_valid = len(rejection_reasons) == 0
        if is_valid:
            decision_enum = ExecutionDecision.ALLOWED
        elif requires_revalidation:
            decision_enum = ExecutionDecision.REQUIRES_REVALIDATION
        else:
            decision_enum = ExecutionDecision.BLOCKED

        return OrderValidationResult(
            is_valid=is_valid,
            decision=decision_enum,
            rejection_reasons=rejection_reasons,
            rejection_details=rejection_details,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
            validated_at=datetime.now(timezone.utc),
        )
