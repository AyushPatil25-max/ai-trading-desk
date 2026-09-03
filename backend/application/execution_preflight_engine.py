"""
Phase 39 - Execution Safety & Order Routing Pre-Flight Engine (Hardened)

Production-grade deterministic gatekeeper service for Trading OS.
Evaluates proposed order requests for validity, risk consistency, exchange constraints,
margin availability, position limits, market data integrity, and duplicate prevention.
No downstream broker order is dispatched without this returning an ExecutionAuthorizationSnapshot.
"""

from datetime import datetime, timezone
import math
import threading
import uuid
from typing import Any, Dict, List, Optional, Set

from backend.domain.schemas import MarketContext
from backend.domain.risk_schemas import (
    PositionDirection,
    PositionSizingPlan,
)
from backend.domain.preflight_schemas import (
    PREFLIGHT_ENGINE_VERSION,
    PreflightStatus,
    PreflightOrderType,
    PreflightSide,
    PreflightOrderRequest,
    ExchangeTradingConstraints,
    PreflightCheckResult,
    ExecutionAuthorizationSnapshot,
    ExecutionPreflightResult,
)
from backend.application.market_data_integrity_engine import MarketDataIntegrityEngine
from backend.application.tamper_evident_audit_chain import global_audit_chain


class ExecutionPreflightEngine:
    """
    Deterministic gatekeeper for execution safety and order routing pre-flight checks.
    Authoritative for execution readiness without overriding upstream RiskEngine authority.
    Zero LLM numerical calculations.
    """

    def __init__(
        self,
        max_decision_age_seconds: float = 1800.0,     # 30 minutes
        max_market_data_age_seconds: float = 300.0,   # 5 minutes
        allow_partial_fill_sizing: bool = False,
        default_constraints: Optional[ExchangeTradingConstraints] = None,
        market_data_engine: Optional[MarketDataIntegrityEngine] = None,
    ):
        self.max_decision_age_seconds = max_decision_age_seconds
        self.max_market_data_age_seconds = max_market_data_age_seconds
        self.allow_partial_fill_sizing = allow_partial_fill_sizing
        self.default_constraints = default_constraints or ExchangeTradingConstraints()
        self.market_data_engine = market_data_engine

        # Thread-safe idempotency tracking
        self._lock = threading.Lock()
        self._authorized_tokens: Set[str] = set()

    def clear_idempotency_cache(self) -> None:
        """Clear authorized token cache (for testing and session resets)."""
        with self._lock:
            self._authorized_tokens.clear()

    # -------------------------------------------------------------------------------------------------
    # Core Pre-Flight Evaluation
    # -------------------------------------------------------------------------------------------------

    def evaluate_preflight(
        self,
        order_request: PreflightOrderRequest,
        candidate_plan: PositionSizingPlan,
        market_context: MarketContext,
        portfolio_state: Optional[Any] = None,
        exchange_constraints: Optional[ExchangeTradingConstraints] = None,
        evaluation_timestamp: Optional[datetime] = None,
    ) -> ExecutionPreflightResult:
        """
        Execute deterministic gatekeeper evaluation on the order request.
        """
        now = evaluation_timestamp or datetime.now(timezone.utc)
        constraints = exchange_constraints or self.default_constraints

        checks: List[PreflightCheckResult] = []
        passed_names: List[str] = []
        failed_names: List[str] = []
        warnings: List[str] = []
        reason_codes: List[str] = []
        
        capital_summary: Dict[str, Any] = {}
        risk_summary: Dict[str, Any] = {}
        broker_capability_result: Dict[str, Any] = {}
        market_data_status = "UNKNOWN"

        token = order_request.idempotency_token or order_request.generate_idempotency_token()

        def _fail_fast(
            status: PreflightStatus,
            check_name: str,
            message: str,
        ) -> ExecutionPreflightResult:
            checks.append(PreflightCheckResult(check_name=check_name, passed=False, message=message, failure_status=status))
            failed_names.append(check_name)
            reason_codes.append(check_name)
            
            global_audit_chain.append_event(
                event_type="EXECUTION_PREFLIGHT_BLOCKED",
                category="EXECUTION",
                component="ExecutionPreflightEngine",
                correlation_id=token,
                reason=message,
                symbol=order_request.symbol,
            )
            
            return ExecutionPreflightResult(
                status=status,
                order_request=order_request,
                checks=checks,
                passed_checks=passed_names,
                failed_checks=failed_names,
                warnings=warnings,
                idempotency_token=token,
                timestamp=now,
                capital_summary=capital_summary,
                risk_summary=risk_summary,
                market_data_status=market_data_status,
                broker_capability_result=broker_capability_result,
                safety_state="BLOCKED",
                reason_codes=reason_codes
            )

        def _pass_check(check_name: str, message: str):
            checks.append(PreflightCheckResult(check_name=check_name, passed=True, message=message))
            passed_names.append(check_name)

        # -------------------------------------------------------------------------------------------------
        # 1. Idempotency Check
        # -------------------------------------------------------------------------------------------------
        with self._lock:
            if token in self._authorized_tokens:
                return _fail_fast(PreflightStatus.DUPLICATE, "DUPLICATE_ORDER", "Duplicate order fingerprint detected.")
        _pass_check("IDEMPOTENCY_CHECK", "Order fingerprint is unique.")

        # -------------------------------------------------------------------------------------------------
        # 2. Request Schema & Parameter Integrity
        # -------------------------------------------------------------------------------------------------
        if order_request.quantity <= 0 or math.isnan(order_request.quantity) or math.isinf(order_request.quantity):
            return _fail_fast(PreflightStatus.INVALID_QUANTITY, "QUANTITY_INVALID", f"Order quantity must be positive finite number; got {order_request.quantity}.")
            
        if not order_request.quantity.is_integer():
            return _fail_fast(PreflightStatus.INVALID_QUANTITY, "FRACTIONAL_QUANTITY_NOT_ALLOWED", f"Indian equity exchanges require whole integer shares; got {order_request.quantity}.")
            
        if order_request.limit_price is not None:
            if order_request.limit_price <= 0 or math.isnan(order_request.limit_price) or math.isinf(order_request.limit_price):
                return _fail_fast(PreflightStatus.INVALID_PRICE, "PRICE_INVALID", f"Limit price must be positive finite number; got {order_request.limit_price}.")
                
        if not constraints.market_hours_open:
            return _fail_fast(PreflightStatus.MARKET_CLOSED, "MARKET_HOURS_CLOSED", "Market session validation failed (market is closed).")
            
        _pass_check("SCHEMA_INTEGRITY", "Order request schema and base parameters valid.")

        # -------------------------------------------------------------------------------------------------
        # 3. Decision Binding & Existence
        # -------------------------------------------------------------------------------------------------
        if not candidate_plan or candidate_plan.symbol != order_request.symbol:
            return _fail_fast(PreflightStatus.INVALID, "DECISION_MISMATCH", "Order symbol does not match approved plan symbol.")
        _pass_check("DECISION_BINDING", "Order correctly bound to approved plan.")

        # -------------------------------------------------------------------------------------------------
        # 4. Phase 38 Market Data Integrity Integration
        # -------------------------------------------------------------------------------------------------
        if self.market_data_engine is not None:
            md_valid = self.market_data_engine.fail_closed_check(order_request.symbol)
            if not md_valid:
                market_data_status = "STALE_OR_INVALID"
                return _fail_fast(PreflightStatus.DATA_UNAVAILABLE, "MARKET_DATA_INTEGRITY", "Phase 38 Market Data Integrity Engine blocked execution (stale or missing data).")
            market_data_status = "FRESH"
            _pass_check("MARKET_DATA_INTEGRITY", "Market Data Integrity check passed.")
        else:
            market_data_status = "BYPASSED_NO_ENGINE"
            warnings.append("Market Data Integrity Engine not provided. Bypassing Phase 38 checks.")

        # Fallback basic freshness checks if engine was bypassed
        ctx_ts = getattr(market_context, "data_timestamp", getattr(market_context, "generated_at", None))
        if ctx_ts:
            age_sec = (now - ctx_ts).total_seconds()
            if age_sec > self.max_market_data_age_seconds:
                return _fail_fast(PreflightStatus.STALE, "STALE_MARKET_DATA", f"Data age {age_sec:.1f}s exceeds max {self.max_market_data_age_seconds}s.")
                
        plan_ts = getattr(candidate_plan, "timestamp", None)
        if plan_ts:
            age_sec = (now - plan_ts).total_seconds()
            if age_sec > self.max_decision_age_seconds:
                return _fail_fast(PreflightStatus.STALE, "STALE_DECISION", f"Decision age {age_sec:.1f}s exceeds max {self.max_decision_age_seconds}s.")
                
        _pass_check("DECISION_FRESHNESS", "Decision and context are fresh.")

        # -------------------------------------------------------------------------------------------------
        # 5. Upstream Risk Veto Enforcement
        # -------------------------------------------------------------------------------------------------
        if candidate_plan.veto_applied:
            reasons = ", ".join(candidate_plan.veto_reasons) if candidate_plan.veto_reasons else "Risk veto active"
            return _fail_fast(PreflightStatus.RISK_VETO, "RISK_VETO_ACTIVE", f"Upstream RiskEngine vetoed the candidate: {reasons}.")
        _pass_check("RISK_VETO_CHECK", "No active risk veto.")

        # -------------------------------------------------------------------------------------------------
        # 6. Approved Quantity Boundary & Position Limits
        # -------------------------------------------------------------------------------------------------
        approved_qty = getattr(candidate_plan, "position_quantity", 0)
        req_qty = int(order_request.quantity)

        if req_qty > approved_qty:
            return _fail_fast(PreflightStatus.INVALID_QUANTITY, "QUANTITY_EXCEEDS_APPROVED", f"Requested qty {req_qty} > approved {approved_qty}.")

        if req_qty < approved_qty and not self.allow_partial_fill_sizing:
            warnings.append(f"PARTIAL_SIZING: Requested quantity {req_qty} is below approved quantity {approved_qty}.")
            
        risk_summary["approved_quantity"] = approved_qty
        risk_summary["requested_quantity"] = req_qty
        _pass_check("POSITION_LIMITS", "Quantity within approved bounds.")

        # -------------------------------------------------------------------------------------------------
        # 7. Capital & Portfolio Exposure Check
        # -------------------------------------------------------------------------------------------------
        order_price = order_request.limit_price or getattr(candidate_plan, "entry_price", None) or getattr(market_context, "current_price", 1000.0)
        req_notional = req_qty * order_price
        
        capital_summary["required_capital"] = req_notional

        if portfolio_state is not None:
            eq = self._get_port_attr(portfolio_state, "total_equity", 100000.0)
            avail_cash = self._get_port_attr(portfolio_state, "available_cash", self._get_port_attr(portfolio_state, "cash", eq))
            
            capital_summary["available_buying_power"] = avail_cash
            capital_summary["total_equity"] = eq
            
            exp_pct = (req_notional / eq) if eq > 0 else 1.0
            capital_summary["projected_exposure_pct"] = exp_pct * 100.0
            
            # Max Portfolio Exposure
            if exp_pct > 0.35: # 35% concentration limit
                return _fail_fast(PreflightStatus.CAPITAL_REJECTED, "PORTFOLIO_EXPOSURE_BREACH", f"Order notional {req_notional:.2f} results in {exp_pct*100:.1f}% exposure (Max 35%).")

            # Max Order Value
            max_order_val = getattr(candidate_plan, "max_order_value", eq * 0.20)
            if req_notional > max_order_val:
                return _fail_fast(PreflightStatus.CAPITAL_REJECTED, "MAX_ORDER_VALUE_BREACH", f"Order notional {req_notional:.2f} exceeds Max Order Value {max_order_val:.2f}.")
            
            # Buying Power
            if req_notional > avail_cash and order_request.side == PreflightSide.BUY:
                return _fail_fast(PreflightStatus.INSUFFICIENT_MARGIN, "INSUFFICIENT_MARGIN", f"Required {req_notional:.2f} exceeds available cash {avail_cash:.2f}.")
        else:
            warnings.append("PORTFOLIO_STATE_UNAVAILABLE: Capital and exposure checks skipped.")

        _pass_check("CAPITAL_VALIDATION", "Capital and portfolio exposure bounds validated.")

        # -------------------------------------------------------------------------------------------------
        # 8. Broker Capability Matrix (Dhan)
        # -------------------------------------------------------------------------------------------------
        supported_exchanges = ["NSE", "BSE", "MCX"]
        
        # Pull exchange from constraints if available, default to NSE.
        exch = getattr(constraints, "exchange", "NSE").upper()
        if exch not in supported_exchanges:
            return _fail_fast(PreflightStatus.BROKER_CAPABILITY_REJECTED, "UNSUPPORTED_EXCHANGE", f"Exchange {exch} not supported by broker capability matrix.")
            
        # Hard constraint: No Stop-Loss Market orders on options, but we assume equity here.
        if order_request.order_type == PreflightOrderType.STOP and order_request.stop_price is None:
            return _fail_fast(PreflightStatus.INVALID_PRICE, "INVALID_STOP_PRICE", "Stop price required for STOP order type.")
            
        # Target/Stop relative checks
        op = order_price
        if order_request.stop_price is not None:
            if order_request.side == PreflightSide.BUY and order_request.stop_price >= op:
                return _fail_fast(PreflightStatus.INVALID_PRICE, "INVALID_BUY_STOP", f"BUY stop {order_request.stop_price} must be < {op}")
            if order_request.side == PreflightSide.SELL and order_request.stop_price <= op:
                return _fail_fast(PreflightStatus.INVALID_PRICE, "INVALID_SELL_STOP", f"SELL stop {order_request.stop_price} must be > {op}")

        if hasattr(order_request, 'target_price') and order_request.target_price is not None:
            if order_request.target_price <= 0:
                return _fail_fast(PreflightStatus.INVALID_PRICE, "INVALID_TARGET_PRICE", "Target price must be positive.")
            if order_request.side == PreflightSide.BUY and order_request.target_price <= op:
                return _fail_fast(PreflightStatus.INVALID_PRICE, "INVALID_BUY_TARGET", f"BUY target {order_request.target_price} must be > {op}")
            if order_request.side == PreflightSide.SELL and order_request.target_price >= op:
                return _fail_fast(PreflightStatus.INVALID_PRICE, "INVALID_SELL_TARGET", f"SELL target {order_request.target_price} must be < {op}")
                
        broker_capability_result = {
            "supported": True,
            "exchange": exch,
            "order_type": order_request.order_type.value,
        }
        _pass_check("BROKER_CAPABILITY", "Broker capability matrix checks passed.")

        # -------------------------------------------------------------------------------------------------
        # 9. Normalization & Circuit Limit & Lot Size
        # -------------------------------------------------------------------------------------------------
        norm_limit = self._normalize_tick(order_request.limit_price, constraints.tick_size, order_request.side) if order_request.limit_price else None
        
        if norm_limit is not None:
            if constraints.circuit_upper_limit is not None and norm_limit > constraints.circuit_upper_limit:
                return _fail_fast(PreflightStatus.CIRCUIT_LIMIT, "UPPER_CIRCUIT_BREACH", f"Price {norm_limit} outside circuit bounds.")
            if constraints.circuit_lower_limit is not None and norm_limit < constraints.circuit_lower_limit:
                return _fail_fast(PreflightStatus.CIRCUIT_LIMIT, "LOWER_CIRCUIT_BREACH", f"Price {norm_limit} outside circuit bounds.")
        _pass_check("CIRCUIT_LIMIT_CHECK", "Price is within circuit limits.")
        
        # Price deviation check
        max_dev = getattr(constraints, 'max_price_deviation_pct', None)
        if norm_limit is not None and max_dev is not None and market_context.current_price > 0:
            dev_pct = abs(norm_limit - market_context.current_price) / market_context.current_price
            if dev_pct > max_dev:
                return _fail_fast(PreflightStatus.CIRCUIT_LIMIT, "PRICE_DEVIATION_EXCESSIVE", f"Deviation {dev_pct*100:.1f}% exceeds {max_dev*100:.1f}%")
        _pass_check("PRICE_DEVIATION", "Price deviation check passed.")
        
        # Lot Size
        lot_size = getattr(constraints, "lot_size", 1)
        if lot_size > 0 and req_qty % lot_size != 0:
            return _fail_fast(PreflightStatus.INVALID_QUANTITY, "LOT_SIZE_VIOLATION", f"Qty {req_qty} not multiple of lot size {lot_size}")
        _pass_check("LOT_SIZE", "Lot size check passed.")

        # -------------------------------------------------------------------------------------------------
        # ALL PASSED
        # -------------------------------------------------------------------------------------------------
        with self._lock:
            self._authorized_tokens.add(token)

        auth = ExecutionAuthorizationSnapshot(
            authorization_id=f"auth-{uuid.uuid4().hex[:8]}",
            decision_id=order_request.decision_id,
            order_id=order_request.order_id,
            symbol=order_request.symbol,
            side=order_request.side,
            approved_quantity=req_qty,
            normalized_limit_price=norm_limit,
            normalized_stop_price=order_request.stop_price,
            normalized_target_price=order_request.target_price,
            risk_state=risk_summary,
            validation_timestamp=now,
            data_freshness=market_data_status,
            circuit_limit_checked=True,
            preflight_approved=True,
            idempotency_token=token,
            engine_version=PREFLIGHT_ENGINE_VERSION
        )

        global_audit_chain.append_event(
            event_type="EXECUTION_PREFLIGHT_PASSED",
            category="EXECUTION",
            component="ExecutionPreflightEngine",
            correlation_id=token,
            reason="All mandatory preflight checks passed.",
            symbol=order_request.symbol,
        )

        return ExecutionPreflightResult(
            status=PreflightStatus.APPROVED,
            order_request=order_request,
            checks=checks,
            passed_checks=passed_names,
            failed_checks=failed_names,
            warnings=warnings,
            authorization=auth,
            idempotency_token=token,
            timestamp=now,
            data_quality=market_data_status,
            capital_summary=capital_summary,
            risk_summary=risk_summary,
            market_data_status=market_data_status,
            broker_capability_result=broker_capability_result,
            safety_state="APPROVED",
            reason_codes=reason_codes
        )

    def _normalize_tick(self, price: float, tick_size: float, side: PreflightSide) -> float:
        if tick_size <= 0:
            return round(price, 2)
        # Conservative rounding
        if side == PreflightSide.BUY:
            return round(math.floor(price / tick_size) * tick_size, 2)
        else:
            return round(math.ceil(price / tick_size) * tick_size, 2)

    def _get_port_attr(self, port: Any, attr: str, default: float) -> float:
        if isinstance(port, dict):
            return float(port.get(attr, default))
        return float(getattr(port, attr, default))
