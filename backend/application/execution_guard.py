"""
Phase 13 — Deterministic Execution Guard

Gatekeeper ensuring that no order can be routed to any broker adapter without
authoritative Pre-Flight verification, deterministic Risk clearance, whole-share
position sizing validation, and operator kill switch compliance.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, Optional

from backend.domain.broker_schemas import GuardValidationOutcome
from backend.domain.paper_broker_schemas import (
    PaperExecutionResult,
    PaperOrder,
    PaperOrderStatus,
)
from backend.domain.preflight_schemas import (
    ExecutionAuthorizationSnapshot,
    PreflightSide,
)
from backend.domain.schemas import MarketContext
from backend.domain.telemetry_schemas import EventSeverity, ExecutionEventType

logger = logging.getLogger(__name__)


class ExecutionGuard:
    """
    Authoritative safety guard intercepting all broker submission attempts.
    Guarantees the strict pipeline execution chain:
    Opportunity -> Evidence -> Debate -> Committee -> Conviction -> Regime ->
    Portfolio -> Scenario -> Risk -> Sizing -> Pre-Flight -> [ExecutionGuard] -> Broker Adapter
    """

    def __init__(self, telemetry_engine: Optional[Any] = None) -> None:
        self.telemetry_engine = telemetry_engine

    def validate_authorization(
        self,
        authorization: Any,
        target_adapter_is_live: bool = False,
    ) -> GuardValidationOutcome:
        """
        Deterministically validate an execution authorization before any broker submission.
        """
        now = datetime.now(timezone.utc)

        # 0. Operator Kill Switch Check
        if self.telemetry_engine and self.telemetry_engine.is_kill_switch_triggered():
            return GuardValidationOutcome(
                is_authorized=False,
                rejection_reason="KILL_SWITCH_ACTIVE: Operator emergency kill switch is active.",
                risk_cleared=True,
                sizing_cleared=True,
                preflight_cleared=True,
                idempotency_cleared=True,
                broker_mode_cleared=False,
                evaluated_at=now,
            )

        # 1. Prevent Live Broker Execution
        if target_adapter_is_live:
            return GuardValidationOutcome(
                is_authorized=False,
                rejection_reason="LIVE_BROKER_PROHIBITED: Live real-money order routing is blocked by ExecutionGuard.",
                broker_mode_cleared=False,
                evaluated_at=now,
            )

        # 2. Type and Snapshot Integrity Check
        if not isinstance(authorization, ExecutionAuthorizationSnapshot):
            return GuardValidationOutcome(
                is_authorized=False,
                rejection_reason="INVALID_AUTHORIZATION: Payload is not an ExecutionAuthorizationSnapshot instance.",
                evaluated_at=now,
            )

        if not authorization.authorization_id or not authorization.decision_id:
            return GuardValidationOutcome(
                is_authorized=False,
                rejection_reason="MISSING_IDENTIFIERS: authorization_id and decision_id are required.",
                evaluated_at=now,
            )

        # 3. Risk Engine Clearance Check
        risk_state = authorization.risk_state or {}
        if risk_state.get("veto_applied", False):
            return GuardValidationOutcome(
                is_authorized=False,
                rejection_reason=f"RISK_VETO_ACTIVE: {risk_state.get('reason', 'Active risk veto detected.')}",
                risk_cleared=False,
                evaluated_at=now,
            )

        # 4. Position Sizing Check (Discrete whole shares > 0)
        qty = authorization.approved_quantity
        if qty <= 0:
            return GuardValidationOutcome(
                is_authorized=False,
                rejection_reason=f"INVALID_POSITION_SIZE: Approved quantity {qty} must be > 0.",
                risk_cleared=True,
                sizing_cleared=False,
                evaluated_at=now,
            )

        if not isinstance(qty, int) or isinstance(qty, bool):
            return GuardValidationOutcome(
                is_authorized=False,
                rejection_reason=f"FRACTIONAL_SHARES_PROHIBITED: Quantity {qty} must be an integer.",
                risk_cleared=True,
                sizing_cleared=False,
                evaluated_at=now,
            )

        # 5. Pre-Flight Gatekeeper Clearance Check
        if getattr(authorization, "circuit_limit_checked", True) is False or getattr(authorization, "preflight_approved", True) is False:
            return GuardValidationOutcome(
                is_authorized=False,
                rejection_reason="PREFLIGHT_BYPASS_ATTEMPT: Circuit limits were not checked by Pre-Flight.",
                risk_cleared=True,
                sizing_cleared=True,
                preflight_cleared=False,
                evaluated_at=now,
            )

        if getattr(authorization, "data_freshness", "FRESH") != "FRESH" or getattr(authorization, "stale_quote_rejected", False) is True:
            return GuardValidationOutcome(
                is_authorized=False,
                rejection_reason="PREFLIGHT_REJECTION: Order rejected due to stale market quote.",
                risk_cleared=True,
                sizing_cleared=True,
                preflight_cleared=False,
                evaluated_at=now,
            )

        # 6. Idempotency Token
        if not authorization.idempotency_token:
            return GuardValidationOutcome(
                is_authorized=False,
                rejection_reason="MISSING_IDEMPOTENCY_TOKEN: idempotency_token is required.",
                risk_cleared=True,
                sizing_cleared=True,
                preflight_cleared=True,
                idempotency_cleared=False,
                evaluated_at=now,
            )

        return GuardValidationOutcome(
            is_authorized=True,
            risk_cleared=True,
            sizing_cleared=True,
            preflight_cleared=True,
            idempotency_cleared=True,
            broker_mode_cleared=True,
            evaluated_at=now,
        )

    def guard_submission(
        self,
        target_adapter: Any,
        authorization: Any,
        market_context: Optional[MarketContext] = None,
        evaluation_timestamp: Optional[datetime] = None,
    ) -> PaperExecutionResult:
        """
        Intercept order submission, validate all safety boundaries, and route exclusively
        if all safety invariants are satisfied.
        """
        now = evaluation_timestamp or datetime.now(timezone.utc)
        capabilities = getattr(target_adapter, "get_capabilities", lambda: None)()
        is_live = getattr(capabilities, "is_live", False)

        outcome = self.validate_authorization(
            authorization=authorization,
            target_adapter_is_live=is_live,
        )

        if not outcome.is_authorized:
            reason = outcome.rejection_reason or "EXECUTION_GUARD_REJECTION"
            logger.warning(f"[ExecutionGuard] Vetoed order submission: {reason}")

            # Emit audit telemetry if engine available
            if self.telemetry_engine:
                self.telemetry_engine.record_event(
                    event_type=ExecutionEventType.PREFLIGHT_REJECTED,
                    execution_id="EXECUTION-GUARD",
                    symbol=getattr(authorization, "symbol", "UNKNOWN"),
                    reason=reason,
                    severity=EventSeverity.WARNING,
                    metadata={"guard": "ExecutionGuard", "rejection_reason": reason},
                )

            # Construct rejected PaperOrder and result
            rejected_order = PaperOrder(
                order_id=f"guard-rej-{getattr(authorization, 'symbol', 'NONE')}",
                authorization_id=getattr(authorization, "authorization_id", "NONE"),
                decision_id=getattr(authorization, "decision_id", "NONE"),
                symbol=getattr(authorization, "symbol", "UNKNOWN"),
                side=getattr(authorization, "side", PreflightSide.BUY),
                requested_quantity=max(0, getattr(authorization, "approved_quantity", 0)),
                remaining_quantity=0,
                status=PaperOrderStatus.REJECTED,
                created_at=now,
                updated_at=now,
                idempotency_token=getattr(authorization, "idempotency_token", "none"),
                rejection_reason=reason,
            )
            return PaperExecutionResult(
                order=rejected_order,
                status=PaperOrderStatus.REJECTED,
                new_fills=[],
                account_snapshot={},
                message=reason,
            )

        # All guards cleared: route to target adapter
        return target_adapter.submit_order(
            authorization=authorization,
            market_context=market_context,
            evaluation_timestamp=now,
        )

    def get_status_summary(self) -> Dict[str, Any]:
        """Return operational status summary for health monitors and auditors."""
        ks_active = False
        if self.telemetry_engine and hasattr(self.telemetry_engine, "is_kill_switch_triggered"):
            ks_active = self.telemetry_engine.is_kill_switch_triggered()
        return {
            "guard_name": "ExecutionGuard",
            "kill_switch_triggered": ks_active,
            "live_broker_blocked": True,
        }


# Global singleton instance for system-wide execution protection
global_execution_guard = ExecutionGuard()
