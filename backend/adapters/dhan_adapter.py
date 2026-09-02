from backend.application.broker_interface import LiveBrokerDisabledError
from backend.application.confirmation_store import global_confirmation_store
import os
import logging
import copy
from typing import Dict, Optional, Any, List
from datetime import datetime, timezone

from backend.domain.broker_schemas import (
    BrokerConnectionState,
    BrokerOrderRequest, BrokerOrderResponse, OrderResult, BrokerAccountState, NormalizedOrderStatus, BrokerPosition, BrokerMode, OrderSide, OrderType,
    ExchangeSegment, ProductType, OrderRequest
)
from backend.config.app_config import get_app_config
from backend.execution.safety_engine import global_manual_order_safety_gate
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

import json
class DhanHTTPClient:
    def __init__(self, client_id, access_token, base_url):
        self.client_id = client_id
        self.access_token = access_token
        self.base_url = base_url

    def request(self, endpoint, method="GET", payload=None):
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        headers = {
            "access-token": self.access_token,
            "client-id": self.client_id,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as response:
                res_body = response.read().decode("utf-8")
                if res_body:
                    return json.loads(res_body)
                return {}
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise ValueError("DHAN_AUTH_FAILED")
            elif e.code == 429:
                raise RuntimeError("DHAN_RATE_LIMITED")
            else:
                raise RuntimeError("DHAN_UNAVAILABLE")
        except urllib.error.URLError:
            raise RuntimeError("DHAN_UNAVAILABLE")

def normalize_dhan_order_status(raw_status: str) -> NormalizedOrderStatus:
    raw = raw_status.upper()
    if raw in ("TRADED", "FILLED"): return NormalizedOrderStatus.FILLED
    if raw in ("PENDING",): return NormalizedOrderStatus.PENDING
    if raw in ("OPEN",): return NormalizedOrderStatus.OPEN
    if raw in ("TRANSIT", "SUBMITTED"): return NormalizedOrderStatus.SUBMITTED
    if raw == "REJECTED": return NormalizedOrderStatus.REJECTED
    if raw in ("CANCELLED", "CANCELED"): return NormalizedOrderStatus.CANCELLED
    if raw == "EXPIRED": return NormalizedOrderStatus.EXPIRED
    return NormalizedOrderStatus.UNKNOWN

def build_dhan_order_payload(order: OrderRequest, client_id: str) -> Dict[str, Any]:
    segment_map = {
        ExchangeSegment.NSE: "NSE_EQ",
        ExchangeSegment.BSE: "BSE_EQ",
        ExchangeSegment.NSE_FNO: "NSE_FNO",
        ExchangeSegment.BSE_FNO: "BSE_FNO",
    }
    exchange_segment_str = segment_map.get(order.exchange_segment, order.exchange_segment.value if hasattr(order.exchange_segment, "value") else str(order.exchange_segment))

    return {
        "dhanClientId": client_id,
        "correlationId": order.request_id,
        "transactionType": "BUY" if order.side.value == "BUY" else "SELL",
        "exchangeSegment": exchange_segment_str,
        "productType": order.product_type.value,
        "orderType": order.order_type.value,
        "validity": "DAY",
        "tradingSymbol": order.symbol,
        "securityId": "",
        "quantity": int(order.quantity),
        "disclosedQuantity": 0,
        "price": order.price or 0.0,
        "triggerPrice": order.trigger_price or 0.0,
        "afterMarketOrder": False,
        "amoTime": "OPEN",
        "boProfitValue": 0.0,
        "boStopLossValue": 0.0
    }

class DhanBrokerAdapter:
    """
    Phase 26 Hardened Dhan API Adapter.
    Requires explict opt-in and live_execution_enabled flag.
    Zero capability for unattended live trading without explicit arming.
    """
    
    def __init__(self, mode: BrokerMode = BrokerMode.SANDBOX):
        self._mode = mode
        self._last_balance: Optional[BrokerAccountBalance] = None
        self._positions: Dict[str, BrokerPosition] = {}
        self._mock_orders: Dict[str, BrokerOrderState] = {}
        self.broker_name = "DhanBrokerAdapter"
        
        # Load from strictly parsed centralized config
        app_config = get_app_config()
        self.client_id = app_config.dhan_client_id
        self._access_token = app_config.dhan_access_token
        self.base_url = app_config.dhan_api_base_url
        self.enabled = app_config.dhan_enabled
        self.static_ip_configured = app_config.dhan_static_ip_configured
        self.live_execution_enabled = app_config.live_execution_enabled
        
        if self.enabled and self.client_id and self._access_token:
            self.client = DhanHTTPClient(self.client_id, self._access_token, self.base_url)
        else:
            self.client = None

        self._connection_state = BrokerConnectionState.DISCONNECTED
        self._check_connection()

    def _check_connection(self):
        if not self.enabled:
            self._connection_state = BrokerConnectionState.DHAN_DISABLED
            return
        if not self.client:
            self._connection_state = BrokerConnectionState.DISCONNECTED
            return
            
        try:
            profile = self.client.request("/profile")
            self._connection_state = BrokerConnectionState.DHAN_CONNECTED
        except ValueError as e:
            if str(e) == "DHAN_AUTH_FAILED":
                self._connection_state = BrokerConnectionState.DHAN_AUTH_FAILED
            else:
                self._connection_state = BrokerConnectionState.ERROR
        except RuntimeError as e:
            if str(e) == "DHAN_UNAVAILABLE":
                self._connection_state = BrokerConnectionState.DHAN_UNAVAILABLE
            else:
                self._connection_state = BrokerConnectionState.ERROR

    def get_capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities(
            broker_name=self.broker_name,
            mode=BrokerMode.LIVE if self.live_execution_enabled else BrokerMode.SANDBOX,
            is_live=self.live_execution_enabled,
            supports_paper=True,
            supports_market_orders=True,
            supports_limit_orders=True,
            supports_stop_orders=True,
            supports_order_cancellation=True,
            supports_order_modification=False,
            supports_fractional_shares=False,
            supports_streaming_quotes=False,
            supports_account_polling=True,
        )

    def get_account_state(self) -> BrokerAccountState:
        if self._connection_state != BrokerConnectionState.DHAN_CONNECTED:
            return BrokerAccountState(
                account_id=self.client_id or "unknown",
                broker_name=self.broker_name,
                mode=BrokerMode.LIVE if self.live_execution_enabled else BrokerMode.SANDBOX,
                is_live=self.live_execution_enabled,
                cash=0.0,
                buying_power=0.0,
                total_equity=0.0,
                realized_pnl=0.0,
                unrealized_pnl=0.0,
                positions={},
                open_positions_count=0
            )
            
        try:
            funds = self.client.request("/fundlimit")
            cash = funds.get("availabelBalance", 0.0)
            return BrokerAccountState(
                account_id=self.client_id,
                broker_name=self.broker_name,
                mode=BrokerMode.LIVE if self.live_execution_enabled else BrokerMode.SANDBOX,
                is_live=self.live_execution_enabled,
                cash=cash,
                buying_power=cash,
                total_equity=cash,
                realized_pnl=0.0,
                unrealized_pnl=0.0,
                positions={},
                open_positions_count=0
            )
        except Exception:
            return None


    def get_positions(self) -> Dict[str, BrokerPosition]:
        if self._connection_state != BrokerConnectionState.DHAN_CONNECTED:
            return {}
        try:
            positions_data = self.client.request("/positions")
            normalized = {}
            for pos in positions_data.get("data", []):
                sym = pos.get("tradingSymbol", "")
                qty = pos.get("netQty", 0)
                if qty == 0:
                    continue
                normalized[sym] = BrokerPosition(
                    symbol=sym,
                    quantity=qty,
                    average_entry_price=pos.get("costPrice", 0.0),
                    current_price=0.0,
                    market_value=0.0,
                    realized_pnl=pos.get("realizedProfit", 0.0),
                    unrealized_pnl=pos.get("unrealizedProfit", 0.0)
                )
            return normalized
        except Exception:
            return {}

    def get_holdings(self) -> List[Dict]:
        if self._connection_state != BrokerConnectionState.DHAN_CONNECTED:
            return []
        try:
            return self.client.request("/holdings").get("data", [])
        except Exception:
            return []

    def get_order_book(self) -> List[Dict]:
        if self._connection_state != BrokerConnectionState.DHAN_CONNECTED:
            return []
        try:
            return self.client.request("/orders").get("data", [])
        except Exception:
            return []

    def get_trade_book(self) -> List[Dict]:
        if self._connection_state != BrokerConnectionState.DHAN_CONNECTED:
            return []
        try:
            return self.client.request("/trades").get("data", [])
        except Exception:
            return []

    def submit_order(
        self,
        authorization: ExecutionAuthorizationSnapshot,
        market_context: Optional[MarketContext] = None,
        evaluation_timestamp: Optional[datetime] = None,
    ) -> PaperExecutionResult:
        if not self.live_execution_enabled:
            raise LiveBrokerDisabledError("LIVE_EXECUTION_ENABLED is false. Dhan orders are fail-closed.")
            
        raise LiveBrokerDisabledError("Safety gate: Real-money live execution is strictly disabled in this phase.")

    def preview_manual_order(
        self,
        order: OrderRequest,
        reference_price: Optional[float] = None,
    ) -> Tuple[SafetyGateResult, OrderPreview, Optional[ConfirmationRecord]]:
        """
        Preview a manual order for Dhan without submitting it to the broker.
        Performs structural and safety gate validation and generates a single-use confirmation token.
        """
        acct = self.get_account_state()
        buying_power = acct.buying_power if (acct and self.get_connection_state() == BrokerConnectionState.DHAN_CONNECTED) else None

        gate_res, preview = global_manual_order_safety_gate.preview_order(
            order=order,
            target_broker="Dhan",
            buying_power=buying_power,
            reference_price=reference_price,
        )

        record = None
        if gate_res.is_approved:
            record = global_confirmation_store.create_confirmation(
                order_request=order,
                dhan_payload=preview.dhan_payload,
                estimated_order_value=gate_res.estimated_order_value or 0.0,
            )

        return gate_res, preview, record

    def submit_manual_order(
        self,
        order: OrderRequest,
        confirmation_token: str,
        _phase42_caller: bool = False,
    ) -> OrderResult:
        """
        Validate confirmation token, re-verify safety gate, and submit to Dhan v2 API if live execution enabled.
        Fails closed if live execution is disabled or any safety gate check fails.
        """
        if not _phase42_caller:
            raise LiveBrokerDisabledError(
                "SECURITY AUDIT FAIL: Direct calls to submit_manual_order without Phase 42 ControlledLiveTradeOrchestrator are strictly blocked."
            )

        # Step 1: Consume confirmation token (atomic single-use + fingerprint binding)
        # In Phase 42, ControlledLiveTradeOrchestrator handles authorization and passes "CONFIRMED_VIA_LIVE_GATE"
        if _phase42_caller and confirmation_token == "CONFIRMED_VIA_LIVE_GATE":
            is_valid, reason_code, reason_msg = True, None, "Authorized by Phase 42 Operator Token"
        else:
            is_valid, reason_code, reason_msg, conf_record = global_confirmation_store.consume_confirmation(
                confirmation_token=confirmation_token,
                order_request=order,
            )

        if not is_valid:
            return OrderResult(
                request_id=order.request_id,
                broker_name=self.broker_name,
                symbol=order.symbol,
                side=order.side.value,
                quantity=order.quantity,
                order_type=order.order_type.value,
                product_type=order.product_type.value,
                exchange_segment=order.exchange_segment.value,
                status=NormalizedOrderStatus.REJECTED.value,
                message=reason_msg,
                rejection_reason=reason_code.value,
            )

        # Step 2: Immediate Safety Gate Re-check (with require_live_enabled=True)
        acct = self.get_account_state()
        buying_power = acct.buying_power if (acct and self.get_connection_state() == BrokerConnectionState.DHAN_CONNECTED) else None
        gate_res = global_manual_order_safety_gate.evaluate_order(
            order=order,
            target_broker="Dhan",
            require_live_enabled=True,
            buying_power=buying_power,
        )

        if not gate_res.is_approved:
            return OrderResult(
                request_id=order.request_id,
                broker_name=self.broker_name,
                symbol=order.symbol,
                side=order.side.value,
                quantity=order.quantity,
                order_type=order.order_type.value,
                product_type=order.product_type.value,
                exchange_segment=order.exchange_segment.value,
                status=NormalizedOrderStatus.REJECTED.value,
                message=gate_res.reason,
                rejection_reason=gate_res.reason_code.value,
            )

        # Step 3: Check Live Execution Flag (Fail Closed)
        if not self.live_execution_enabled:
            raise LiveBrokerDisabledError(
                "LIVE_EXECUTION_ENABLED is false. Dhan real-money live order execution is locked."
            )

        if not self.client:
            raise LiveBrokerDisabledError(
                "DhanHTTPClient is not initialized. Check credentials and configuration."
            )

        # Step 4: Phase 26 Live Readiness & Active Armed State Gate
        from backend.execution.live_arming_store import global_live_arming_store
        is_armed, arm_msg = global_live_arming_store.validate_active_arm()
        if not is_armed:
            try:
                global_audit_chain.append_event(
                    event_type="LIVE_ORDER_BLOCKED",
                    category=EventCategory.EXECUTION,
                    component="DhanBrokerAdapter",
                    correlation_id=order.request_id,
                    symbol=order.symbol,
                    severity=EventSeverity.WARNING,
                    reason=arm_msg,
                    payload={"request_id": order.request_id, "error": "ARMED_STATE_INACTIVE"},
                )
            except Exception:
                pass

            return OrderResult(
                request_id=order.request_id,
                broker_name=self.broker_name,
                symbol=order.symbol,
                side=order.side.value,
                quantity=order.quantity,
                order_type=order.order_type.value,
                product_type=order.product_type.value,
                exchange_segment=order.exchange_segment.value,
                status=NormalizedOrderStatus.REJECTED.value,
                message=arm_msg,
                rejection_reason="LIVE_TRADING_NOT_ARMED",
            )

        # Step 5: Construct Dhan v2 Order Payload and Submit via LiveFailureRecoveryEngine
        dhan_payload = build_dhan_order_payload(order, self.client_id)

        from backend.execution.live_failure_recovery import (
            global_live_failure_engine,
            is_transient_error,
        )

        def _do_submit() -> OrderResult:
            try:
                global_audit_chain.append_event(
                    event_type="ORDER_SUBMISSION_ATTEMPTED",
                    category=EventCategory.EXECUTION,
                    component="DhanBrokerAdapter",
                    correlation_id=order.request_id,
                    symbol=order.symbol,
                    severity=EventSeverity.INFO,
                    reason="Submitting manual order to Dhan API",
                    payload={
                        "request_id": order.request_id,
                        "symbol": order.symbol,
                        "side": order.side.value,
                        "quantity": order.quantity,
                        "order_type": order.order_type.value,
                        "product_type": order.product_type.value,
                    },
                )
            except Exception:
                pass

            try:
                dhan_res = self.client.request("/orders", method="POST", payload=dhan_payload)
                raw_status = dhan_res.get("orderStatus", "TRANSIT")
                order_id = str(dhan_res.get("orderId", f"dhan-{order.request_id}"))
                norm_status = normalize_dhan_order_status(raw_status)
                remarks = dhan_res.get("remarks", "Order submitted to Dhan.")

                # Record success audit event
                try:
                    global_audit_chain.append_event(
                        event_type="ORDER_SUBMITTED_TO_DHAN",
                        category=EventCategory.EXECUTION,
                        component="DhanBrokerAdapter",
                        correlation_id=order.request_id,
                        symbol=order.symbol,
                        severity=EventSeverity.INFO,
                        reason=f"Order accepted by Dhan: {norm_status.value}",
                        payload={
                            "order_id": order_id,
                            "request_id": order.request_id,
                            "status": norm_status.value,
                            "dhan_status": raw_status,
                        },
                    )
                except Exception:
                    pass

                return OrderResult(
                    order_id=order_id,
                    request_id=order.request_id,
                    broker_name=self.broker_name,
                    symbol=order.symbol,
                    side=order.side.value,
                    quantity=order.quantity,
                    order_type=order.order_type.value,
                    product_type=order.product_type.value,
                    exchange_segment=order.exchange_segment.value,
                    status=norm_status.value,
                    message=remarks,
                    rejection_reason=None if norm_status in (NormalizedOrderStatus.SUBMITTED, NormalizedOrderStatus.PENDING, NormalizedOrderStatus.OPEN, NormalizedOrderStatus.FILLED) else "BROKER_REJECTED",
                )
            except Exception as e:
                err_msg = str(e)
                try:
                    global_audit_chain.append_event(
                        event_type="ORDER_SUBMISSION_FAILED",
                        category=EventCategory.EXECUTION,
                        component="DhanBrokerAdapter",
                        correlation_id=order.request_id,
                        symbol=order.symbol,
                        severity=EventSeverity.ERROR,
                        reason=f"Dhan submission failed: {err_msg}",
                        payload={
                            "request_id": order.request_id,
                            "error": err_msg,
                        },
                    )
                except Exception:
                    pass

                if is_transient_error(e):
                    raise e

                return OrderResult(
                    order_id=None,
                    request_id=order.request_id,
                    broker_name=self.broker_name,
                    symbol=order.symbol,
                    side=order.side.value,
                    quantity=order.quantity,
                    order_type=order.order_type.value,
                    product_type=order.product_type.value,
                    exchange_segment=order.exchange_segment.value,
                    status=NormalizedOrderStatus.REJECTED.value,
                    message=f"Dhan submission error: {err_msg}",
                    rejection_reason="BROKER_SUBMISSION_ERROR",
                )

        def _reconcile_check(req_id: str) -> Optional[Dict[str, Any]]:
            """Check if order was already received on Dhan during network ambiguity."""
            try:
                orders = self.get_order_book()
                if isinstance(orders, list):
                    for o in orders:
                        if isinstance(o, dict) and str(o.get("correlationId", "")) == str(req_id):
                            raw_st = o.get("orderStatus", "TRANSIT")
                            return {
                                "orderId": o.get("orderId"),
                                "orderStatus": raw_st,
                                "status": normalize_dhan_order_status(raw_st).value,
                            }
            except Exception:
                pass
            return None

        return global_live_failure_engine.execute_with_recovery(
            order=order,
            submit_fn=_do_submit,
            reconcile_check_fn=_reconcile_check,
        )

    def get_dhan_order_status(self, order_id: str) -> Dict[str, Any]:
        """
        Query current execution status of an order directly from Dhan v2 API.
        """
        if not self.client:
            return {"order_id": order_id, "status": NormalizedOrderStatus.UNKNOWN.value, "error": "DHAN_CLIENT_NOT_CONFIGURED"}

        try:
            res = self.client.request(f"/orders/{order_id}", method="GET")
            raw_status = res.get("orderStatus", "UNKNOWN")
            norm_status = normalize_dhan_order_status(raw_status)

            try:
                event_type = "ORDER_STATUS_CHECKED"
                if norm_status == NormalizedOrderStatus.FILLED:
                    event_type = "ORDER_FILLED"
                elif norm_status == NormalizedOrderStatus.REJECTED:
                    event_type = "ORDER_REJECTED"
                elif norm_status == NormalizedOrderStatus.CANCELLED:
                    event_type = "ORDER_CANCELLED"

                global_audit_chain.append_event(
                    event_type=event_type,
                    category=EventCategory.EXECUTION,
                    component="DhanBrokerAdapter",
                    correlation_id=f"order-{order_id}",
                    severity=EventSeverity.INFO,
                    reason=f"Dhan order status: {norm_status.value}",
                    payload={"order_id": order_id, "status": norm_status.value, "dhan_status": raw_status},
                )
            except Exception:
                pass

            return {
                "order_id": order_id,
                "status": norm_status.value,
                "dhan_status": raw_status,
                "quantity": res.get("quantity", 0),
                "filled_quantity": res.get("filledQty", 0),
                "price": res.get("price", 0.0),
                "average_price": res.get("averageTradedPrice", 0.0),
                "symbol": res.get("tradingSymbol", ""),
            }
        except Exception as e:
            return {
                "order_id": order_id,
                "status": NormalizedOrderStatus.UNKNOWN.value,
                "error": str(e),
            }

    def cancel_dhan_order(self, order_id: str) -> Dict[str, Any]:
        """
        Request cancellation of an active Dhan order.
        """
        if not self.client:
            return {"order_id": order_id, "cancelled": False, "error": "DHAN_CLIENT_NOT_CONFIGURED"}

        try:
            res = self.client.request(f"/orders/{order_id}", method="DELETE")
            try:
                global_audit_chain.append_event(
                    event_type="ORDER_CANCELLED",
                    category=EventCategory.EXECUTION,
                    component="DhanBrokerAdapter",
                    correlation_id=f"order-{order_id}",
                    severity=EventSeverity.INFO,
                    reason=f"Dhan order cancelled: {order_id}",
                    payload={"order_id": order_id, "response": res},
                )
            except Exception:
                pass
            return {"order_id": order_id, "cancelled": True, "details": res}
        except Exception as e:
            return {"order_id": order_id, "cancelled": False, "error": str(e)}

    def cancel_order(self, order_id: str) -> bool:
        res = self.cancel_dhan_order(order_id)
        return bool(res.get("cancelled", False))


    def get_order(self, order_id: str) -> Optional[PaperOrder]:
        return None

    def list_orders(
        self,
        symbol: Optional[str] = None,
        status: Optional[PaperOrderStatus] = None,
    ) -> List[PaperOrder]:
        return []

    def get_connection_state(self) -> BrokerConnectionState:
        return self._connection_state

    def reset(self, initial_cash: Optional[float] = None) -> None:
        pass









