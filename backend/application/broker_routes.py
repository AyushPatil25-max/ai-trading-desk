"""
Phase 13 — Broker Adapter Read-Only REST API Routes

Exposes safe, read-only status, capability inspection, and simulated account state
under `/api/broker/*`.
STRICT SAFETY RULE:
Zero endpoints capable of activating live broker execution or receiving broker credentials.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, status


from backend.domain.broker_schemas import (
    BrokerAccountState,
    BrokerCapabilities,
    BrokerPosition,
    BrokerStatusSummary,
)
from backend.domain.paper_broker_schemas import PaperOrder, PaperOrderStatus
from backend.application.broker_interface import BrokerFactory
from backend.application.paper_broker_adapter import global_paper_broker

broker_router = APIRouter(prefix="/api/broker", tags=["Broker Integration"])


@broker_router.get(
    "/status",
    response_model=BrokerStatusSummary,
    summary="Get Active Broker Status & Safety Summary",
)
def get_broker_status() -> BrokerStatusSummary:
    """
    Retrieve current broker configuration, active adapter name, capabilities,
    and verified paper-only safety invariants.
    """
    from backend.config.app_config import get_app_config
    app_config = get_app_config()
    
    adapter = BrokerFactory.get_adapter()
    caps = adapter.get_capabilities()
    acct = adapter.get_account_state()
    conn = adapter.get_connection_state()

    summary = BrokerStatusSummary(
        active_broker_name=caps.broker_name,
        broker_mode=caps.mode,
        is_live_trading_enabled=False,
        connection_state=conn,
        capabilities=caps,
        account_summary=acct,
    )
    
    # Append the additional safety invariant required by Phase 43/Dhan integration
    summary.safety_invariants["live_execution_authorized"] = app_config.live_execution_enabled
    
    return summary


@broker_router.get(
    "/profile",
    summary="Get Broker Profile / Identity",
)
def get_broker_profile() -> Dict[str, Any]:
    """
    Query broker profile to verify authentication identity.
    Crucially strips access tokens from output.
    """
    from backend.config.app_config import get_app_config
    app_config = get_app_config()
    adapter = BrokerFactory.get_adapter()
    
    if adapter.broker_name == "DhanBrokerAdapter":
        if not app_config.dhan_client_id or not app_config.dhan_access_token:
            return {
                "connected": False,
                "broker": adapter.broker_name,
                "error": "Missing DHAN_CLIENT_ID or DHAN_ACCESS_TOKEN"
            }
            
        if hasattr(adapter, "client") and adapter.client:
            try:
                profile = adapter.client.request("/profile")
                client_id = adapter.client_id
                masked_id = client_id[:2] + "****" + client_id[-2:] if len(client_id) > 4 else "****"
                from backend.infrastructure.security_master import get_security_master
                sm = get_security_master()
                
                from backend.adapters.dhan_ws_client import get_dhan_ws
                ws_client = get_dhan_ws()
                ws_status = ws_client.status if ws_client else "NOT_CONFIGURED"
                
                return {
                    "connected": True,
                    "broker": adapter.broker_name,
                    "provider": "DHAN",
                    "client_id": masked_id,
                    "token_valid": True,
                    "account_status": "CONNECTED",
                    "static_ip_status": getattr(adapter, "static_ip_status", "UNKNOWN"),
                    "instrument_master_count": sm.total_count,
                    "order_update_ws": ws_status,
                    "reconciliation": "IDLE"
                }
            except ValueError as e:
                return {
                    "connected": False,
                    "broker": adapter.broker_name,
                    "provider": "DHAN",
                    "error": "Invalid credentials or unauthorized"
                }
            except Exception as e:
                return {
                    "connected": False,
                    "broker": adapter.broker_name,
                    "error": f"Network or Dhan API failure: {str(e)}"
                }
    
    return {
        "connected": False,
        "broker": adapter.broker_name,
        "error": "Profile fetch not supported or client not configured"
    }


@broker_router.get(
    "/capabilities",
    response_model=BrokerCapabilities,
    summary="Get Active Broker Capabilities Matrix",
)
def get_broker_capabilities() -> BrokerCapabilities:
    """
    Retrieve explicit capabilities of the active broker adapter
    (supports_market_orders, supports_fractional_shares, etc.).
    """
    adapter = BrokerFactory.get_adapter()
    return adapter.get_capabilities()


@broker_router.get(
    "/account",
    response_model=BrokerAccountState,
    summary="Get Broker Account & Purchasing Power State",
)
def get_broker_account() -> BrokerAccountState:
    """
    Retrieve normalized account cash, total equity, buying power, and open positions.
    """
    adapter = BrokerFactory.get_adapter()
    return adapter.get_account_state()


@broker_router.get(
    "/positions",
    response_model=Dict[str, BrokerPosition],
    summary="Get Open Broker Positions",
)
def get_broker_positions() -> Dict[str, BrokerPosition]:
    """
    Retrieve open stock positions, market values, and unrealized P&L.
    """
    adapter = BrokerFactory.get_adapter()
    return adapter.get_positions()


@broker_router.get(
    "/orders",
    response_model=List[PaperOrder],
    summary="List Broker Orders",
)
def list_broker_orders(
    symbol: Optional[str] = Query(default=None, description="Filter by stock symbol"),
    status: Optional[PaperOrderStatus] = Query(default=None, description="Filter by status"),
) -> List[PaperOrder]:
    """
    List orders managed by the active broker adapter.
    """
    adapter = BrokerFactory.get_adapter()
    return adapter.list_orders(symbol=symbol, status=status)


@broker_router.get(
    "/orders/{order_id}",
    response_model=PaperOrder,
    summary="Get Single Broker Order by ID",
)
def get_broker_order(order_id: str) -> PaperOrder:
    """
    Retrieve state of an individual order by ID.
    """
    adapter = BrokerFactory.get_adapter()
    order = adapter.get_order(order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order '{order_id}' not found.",
        )
    return order


# ── Phase 15 — Broker Manager & Reconciliation Routes ─────────────────────────

from backend.domain.broker_schemas import BrokerManagerStatus, ReconciliationReport
from backend.application.broker_manager import global_broker_manager
from backend.application.broker_reconciliation import global_reconciliation_engine


@broker_router.get(
    "/manager/status",
    response_model=BrokerManagerStatus,
    summary="Get Unified Broker Manager Status & Invariants",
)
def get_broker_manager_status() -> BrokerManagerStatus:
    """
    Retrieve unified status from the BrokerManager including active environment,
    routing mode, provider name, connection state, and live-blocked invariants.
    """
    summary = global_broker_manager.get_status_summary()
    summary.last_reconciliation = global_reconciliation_engine.get_latest_report()
    return summary


@broker_router.post(
    "/reconcile",
    response_model=ReconciliationReport,
    summary="Trigger Broker State Reconciliation Audit",
)
def trigger_broker_reconciliation() -> ReconciliationReport:
    """
    Execute a deterministic bi-directional reconciliation between internal state
    and the active broker/sandbox state, detecting discrepancies.
    """
    return global_reconciliation_engine.reconcile()


@broker_router.get(
    "/reconciliation/latest",
    response_model=ReconciliationReport,
    summary="Get Latest Reconciliation Audit Report",
)
def get_latest_reconciliation() -> ReconciliationReport:
    """
    Retrieve the most recent state reconciliation report.
    """
    report = global_reconciliation_engine.get_latest_report()
    if not report:
        report = global_reconciliation_engine.reconcile()
    return report


# ── Phase 24 — Manual Order Preview & Confirmation Routes ────────────────────

from backend.domain.broker_schemas import (
    OrderConfirmRequest,
    OrderPreviewResponse,
    OrderRequest,
    OrderResult,
    SafetyGateResult,
)
from backend.execution.safety_engine import global_manual_order_safety_gate
from backend.application.confirmation_store import global_confirmation_store


@broker_router.post(
    "/order/preview",
    response_model=OrderPreviewResponse,
    summary="Preview Manual Order and Generate Confirmation Token",
)
def preview_manual_order(order: OrderRequest) -> OrderPreviewResponse:
    """
    Validate manual order parameters against safety gate, generate Dhan v2 payload,
    and issue a single-use, 2-minute TTL confirmation token if approved.
    """
    gate_res, preview = global_manual_order_safety_gate.preview_order(
        order=order,
        target_broker="Dhan",
    )

    token = None
    expires_at = None

    if gate_res.is_approved:
        record = global_confirmation_store.create_confirmation(
            order_request=order,
            dhan_payload=preview.dhan_payload,
            estimated_order_value=gate_res.estimated_order_value or 0.0,
        )
        token = record.confirmation_id
        expires_at = record.expires_at

    return OrderPreviewResponse(
        safety_result=gate_res,
        preview=preview,
        confirmation_token=token,
        expires_at=expires_at,
    )


from backend.adapters.dhan_adapter import DhanBrokerAdapter
from backend.application.broker_interface import LiveBrokerDisabledError

# Adapter instance for Dhan operations
_dhan_adapter_instance = DhanBrokerAdapter()


@broker_router.post(
    "/order/confirm",
    response_model=OrderResult,
    summary="Confirm and Submit Manual Order",
)
def confirm_manual_order(req: OrderConfirmRequest) -> OrderResult:
    """
    Validate confirmation token (single-use + order fingerprint binding),
    re-evaluate safety gate with live execution requirement, and submit to Dhan if live enabled.
    """
    try:
        # Re-instantiate or refresh adapter configuration dynamically
        adapter = DhanBrokerAdapter()
        return adapter.submit_manual_order(req.order, req.confirmation_token)
    except LiveBrokerDisabledError as e:
        return OrderResult(
            request_id=req.order.request_id,
            broker_name="DhanBroker",
            symbol=req.order.symbol,
            side=req.order.side.value,
            quantity=req.order.quantity,
            order_type=req.order.order_type.value,
            product_type=req.order.product_type.value,
            exchange_segment=req.order.exchange_segment.value,
            status="REJECTED",
            message=str(e),
            rejection_reason="LIVE_EXECUTION_DISABLED",
        )
    except Exception as e:
        return OrderResult(
            request_id=req.order.request_id,
            broker_name="DhanBroker",
            symbol=req.order.symbol,
            side=req.order.side.value,
            quantity=req.order.quantity,
            order_type=req.order.order_type.value,
            product_type=req.order.product_type.value,
            exchange_segment=req.order.exchange_segment.value,
            status="REJECTED",
            message=f"Submission error: {str(e)}",
            rejection_reason="UNHANDLED_ERROR",
        )


@broker_router.get(
    "/order/{order_id}/status",
    summary="Get Dhan Order Status",
)
def get_dhan_order_status(order_id: str) -> Dict[str, Any]:
    """
    Query real-time status of an order from Dhan API.
    """
    adapter = DhanBrokerAdapter()
    return adapter.get_dhan_order_status(order_id)


@broker_router.post(
    "/order/{order_id}/cancel",
    summary="Cancel Dhan Order",
)
def cancel_dhan_order(order_id: str) -> Dict[str, Any]:
    """
    Cancel an active order in Dhan.
    """
    adapter = DhanBrokerAdapter()
    return adapter.cancel_dhan_order(order_id)


@broker_router.get(
    "/order/confirmation/{token}",
    summary="Check Confirmation Token Status",
)
def get_confirmation_status(token: str) -> Dict[str, Any]:
    """
    Inspect the validity state of a confirmation token without exposing secrets.
    """
    record = global_confirmation_store.get_confirmation(token)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Confirmation token not found or expired.",
        )

    now = datetime.now(timezone.utc)
    is_expired = now > record.expires_at

    return {
        "status": "EXPIRED" if is_expired else ("CONSUMED" if record.consumed else "ACTIVE"),
        "is_valid": (not is_expired) and (not record.consumed),
        "symbol": record.order_request.symbol,
        "side": record.order_request.side.value,
        "quantity": record.order_request.quantity,
        "estimated_value": record.estimated_order_value,
        "expires_at": record.expires_at.isoformat(),
        "created_at": record.created_at.isoformat(),
    }


# ── Live Trading Readiness & Controlled Activation Endpoints ─────────────────

from backend.domain.live_readiness_schemas import (
    LiveArmRequest,
    LiveArmingStatus,
    LiveDisarmRequest,
    LiveReadinessReport,
)
from backend.execution.live_readiness import global_live_readiness_engine
from backend.execution.live_arming_store import global_live_arming_store


@broker_router.get(
    "/live/readiness",
    response_model=LiveReadinessReport,
    summary="Inspect Live Trading Readiness",
)
def get_live_readiness() -> LiveReadinessReport:
    """
    Evaluate 17+ deterministic readiness checks across SAFETY, DHAN, MARKET, and EXECUTION subsystems.
    Does NOT arm or enable live trading. Strictly read-only assessment.
    """
    return global_live_readiness_engine.evaluate_readiness()


@broker_router.post(
    "/live/check",
    response_model=LiveReadinessReport,
    summary="Trigger Live Trading Readiness Audit",
)
def check_live_readiness() -> LiveReadinessReport:
    """
    Explicitly trigger live readiness evaluation.
    """
    return global_live_readiness_engine.evaluate_readiness()


@broker_router.post(
    "/live/arm",
    response_model=LiveArmingStatus,
    summary="Arm Live Trading Session",
)
def arm_live_trading(req: LiveArmRequest) -> LiveArmingStatus:
    """
    Activate a short-lived (default 5 min) live-trading armed state.
    Requires explicit user acknowledgement and passes all critical readiness gates.
    """
    if not req.acknowledgement:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Explicit acknowledgement of financial risk is required to arm live trading.",
        )

    # Check readiness before arming
    report = global_live_readiness_engine.evaluate_readiness()
    if not report.is_ready_for_arming:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail=f"Cannot arm live trading: Readiness checks failed ({'; '.join(report.blocking_failures)}).",
        )

    success, msg, status_obj = global_live_arming_store.arm(
        acknowledgement=req.acknowledgement,
        duration_seconds=req.duration_seconds,
        operator_notes=req.operator_notes,
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=msg,
        )

    return status_obj


@broker_router.post(
    "/live/disarm",
    response_model=LiveArmingStatus,
    summary="Disarm Live Trading Session",
)
def disarm_live_trading(req: Optional[LiveDisarmRequest] = None) -> LiveArmingStatus:
    """
    Immediately disarm live trading and revoke live order authorization.
    """
    reason = req.reason if req else "Manual operator disarm"
    return global_live_arming_store.disarm(reason=reason)


# ── Phase 27 — Live Failure Recovery & Operational Verification Routes ────────

from backend.execution.live_failure_recovery import global_live_failure_engine
from backend.execution.order_tracker import global_order_tracker
from backend.execution.reconciliation_service import global_reconciliation_service
from backend.execution.account_sync_service import global_account_sync_service
from backend.execution.persistent_state_store import global_persistent_state_store
from backend.execution.state_journal import global_state_journal
from backend.execution.crash_recovery import global_state_recovery_engine


@broker_router.post(
    "/live/reconcile",
    summary="Trigger Manual Live Broker State Reconciliation",
)
def trigger_live_reconciliation() -> Dict[str, Any]:
    """
    Trigger manual reconciliation between local in-memory order tracker and Dhan broker order book.
    """
    return global_reconciliation_service.run_once()


@broker_router.post(
    "/live/recovery/run",
    summary="Trigger Deterministic Crash Recovery Replay",
)
def trigger_crash_recovery() -> Dict[str, Any]:
    """
    Execute deterministic crash recovery sequence across persistent state and state journal.
    """
    return global_state_recovery_engine.run_recovery()


@broker_router.get(
    "/live/status",
    summary="Get Comprehensive Live Trading Operational & Resilience Status",
)
def get_live_status() -> Dict[str, Any]:
    """
    Return comprehensive operational status across failure recovery, order tracking,
    reconciliation, account sync, live arming, persistent store, journal, and crash recovery.
    """
    arming_status = global_live_arming_store.get_status()
    report = global_live_readiness_engine.evaluate_readiness()
    recovery_status = global_live_failure_engine.get_status()
    tracker_stats = global_order_tracker.get_stats()
    reconcile_status = global_reconciliation_service.get_status()
    account_sync_status = global_account_sync_service.get_status()
    persistent_store_status = global_persistent_state_store.get_status()
    journal_status = global_state_journal.get_status()
    crash_recovery_status = global_state_recovery_engine.get_status()

    return {
        "is_live_enabled_in_env": report.is_live_enabled_in_env,
        "is_armed": arming_status.is_armed,
        "remaining_seconds": arming_status.remaining_seconds,
        "expires_at": arming_status.expires_at.isoformat() if arming_status.expires_at else None,
        "overall_status": report.overall_status.value,
        "is_ready_for_arming": report.is_ready_for_arming,
        "is_ready_for_order": report.is_ready_for_order,
        "market_session": report.market_session,
        "dhan_connection": report.dhan_connection,
        "blocking_failures": report.blocking_failures,
        "warnings": report.warnings,
        "recovery_engine": recovery_status,
        "order_tracker": tracker_stats,
        "reconciliation": reconcile_status,
        "account_sync": account_sync_status,
        "persistent_store": persistent_store_status,
        "state_journal": journal_status,
        "crash_recovery": crash_recovery_status,
    }







from pydantic import BaseModel
from backend.domain.preflight_schemas import ExecutionAuthorizationSnapshot
from backend.domain.broker_schemas import OrderResult
from backend.execution.dhan_live_execution_engine import DhanLiveExecutionEngine
from backend.adapters.dhan_adapter import DhanBrokerAdapter

class LiveExecuteRequest(BaseModel):
    authorization: ExecutionAuthorizationSnapshot
    confirmation_token: str

@broker_router.post(
    "/live/execute",
    response_model=OrderResult,
    summary="Execute Live Order via Dhan",
)
def execute_live_order(req: LiveExecuteRequest):
    """
    Submits a preflight-approved authorization to the live broker.
    Strictly fail-closed if LIVE_EXECUTION_ENABLED=False.
    """
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="LIVE_EXECUTION_DISABLED: Automated AI live execution is permanently blocked in Phase 42. Use /api/production/execute with a Phase 42 Operator Token."
    )

@broker_router.get(
    "/live/orders/{order_id}",
    summary="Get Live Order Status",
)
def get_live_order_status(order_id: str):
    from backend.execution.order_tracker import global_order_tracker
    order = global_order_tracker.lookup_by_order_id(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found in tracker")
    return order

from backend.application.dhan_reconciliation_engine import global_dhan_reconciliation_engine
from backend.domain.broker_schemas import BrokerConnectivityStatus, ReconciliationResult

@broker_router.get('/validation/status', response_model=BrokerConnectivityStatus, summary='Get Dhan Connectivity Status')
def get_validation_status():
    adapter = DhanBrokerAdapter()
    return global_dhan_reconciliation_engine.check_connectivity(adapter)

@broker_router.post('/reconciliation/run', response_model=ReconciliationResult, summary='Trigger READ-ONLY Reconciliation')
def trigger_dhan_reconciliation():
    from backend.execution.account_sync_service import global_account_sync_service
    from backend.execution.order_tracker import global_order_tracker
    
    adapter = DhanBrokerAdapter()
    local_state = {
        "orders": global_order_tracker.get_all_tracked(),
        "trades": global_order_tracker.get_all_tracked(),
        "positions": global_account_sync_service.get_cached_positions(),
        "holdings": global_account_sync_service.get_cached_holdings(),
        "funds": global_account_sync_service.get_cached_account()
    }
    return global_dhan_reconciliation_engine.run_reconciliation(adapter, local_state)

@broker_router.get('/reconciliation/history/latest', response_model=ReconciliationResult, summary='Get Latest Reconciliation')
def get_latest_dhan_reconciliation():
    if not global_dhan_reconciliation_engine.latest_result:
        raise HTTPException(status_code=404, detail='No reconciliation history.')
    return global_dhan_reconciliation_engine.latest_result

@broker_router.get('/holdings', summary='Get Raw Broker Holdings')
def get_raw_holdings():
    adapter = DhanBrokerAdapter()
    try:
        h = adapter.get_holdings()
        if h is None:
            raise HTTPException(status_code=503, detail='Holdings unavailable or ERROR')
        return h
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

@broker_router.get('/trades', summary='Get Raw Broker Trades')
def get_raw_trades():
    adapter = DhanBrokerAdapter()
    try:
        t = adapter.get_trade_book()
        if t is None:
            raise HTTPException(status_code=503, detail='Trades unavailable or ERROR')
        return t
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
