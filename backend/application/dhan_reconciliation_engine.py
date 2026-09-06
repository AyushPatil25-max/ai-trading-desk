from datetime import datetime, timezone
import uuid
import logging
from typing import Dict, List, Any, Optional

from backend.domain.broker_schemas import (
    ReconciliationResult,
    EntityRecResult,
    DiscrepancyDetail,
    RecStatus,
    DiscrepancyCategory,
    BrokerConnectivityStatus,
    BrokerPosition,
    BrokerAccountState
)
from backend.application.broker_interface import BrokerAdapter

logger = logging.getLogger(__name__)

class DhanReconciliationEngine:
    def __init__(self):
        self.latest_result: Optional[ReconciliationResult] = None
        self.price_tolerance = 0.5  # Rs 0.50
        self.quantity_tolerance = 0 # Strict quantity matching
        self.value_tolerance = 1.0  # Rs 1.0 for P&L or funds

    def _safe_call(self, func, default=None):
        try:
            res = func()
            if res is None:
                return default, "ERROR"
            return res, "FRESH"
        except Exception as e:
            logger.error(f"[DhanReconciliation] Error calling {func.__name__}: {e}")
            return default, "ERROR"

    def check_connectivity(self, adapter: BrokerAdapter) -> BrokerConnectivityStatus:
        conn = adapter.get_connection_state()
        status_name = conn.name if hasattr(conn, 'name') else str(conn)
        status = BrokerConnectivityStatus(
            broker_name="DhanBroker",
            connection_status=status_name,
            authentication_status="AUTHENTICATED" if status_name in ["CONNECTED", "DHAN_CONNECTED"] else "UNAUTHENTICATED",
            last_successful_call=datetime.now(timezone.utc),
            last_error=None,
            latency_ms=15.0
        )
        return status

    def _generate_missing(self, entity_type, broker_key, local_key, b_val, l_val, missing_from, reason):
        return DiscrepancyDetail(
            entity_type=entity_type,
            broker_key=broker_key,
            local_key=local_key,
            field="N/A",
            broker_value=b_val,
            local_value=l_val,
            difference="MISSING",
            severity="CRITICAL",
            status=missing_from,
            reason=reason
        )

    def reconcile_holdings(self, broker_holdings: List[Dict], local_holdings: List[Dict], discrepancies: List[DiscrepancyDetail]) -> EntityRecResult:
        if broker_holdings is None:
            return EntityRecResult(status=RecStatus.UNAVAILABLE, freshness="ERROR")
        if local_holdings is None:
            local_holdings = []
        
        b_map = {h.get("tradingSymbol", str(i)): h for i, h in enumerate(broker_holdings)}
        l_map = {h.get("tradingSymbol", str(i)): h for i, h in enumerate(local_holdings)}
        
        matched, mismatched, missing = 0, 0, 0
        
        # Compare Broker -> Local
        for sym, b_hold in b_map.items():
            if sym not in l_map:
                discrepancies.append(self._generate_missing("HOLDING", sym, None, str(b_hold), None, DiscrepancyCategory.MISSING_LOCALLY, "Holding found in Dhan but not locally"))
                missing += 1
                continue
                
            l_hold = l_map[sym]
            b_qty = b_hold.get("quantity", b_hold.get("netQty", 0))
            l_qty = l_hold.get("quantity", l_hold.get("netQty", 0))
            
            if b_qty != l_qty:
                discrepancies.append(DiscrepancyDetail(
                    entity_type="HOLDING", broker_key=sym, local_key=sym, field="quantity",
                    broker_value=b_qty, local_value=l_qty, difference=abs(b_qty - l_qty),
                    severity="CRITICAL", status=DiscrepancyCategory.QUANTITY_MISMATCH, reason="Holding quantity mismatch"
                ))
                mismatched += 1
            else:
                matched += 1

        # Compare Local -> Broker
        for sym, l_hold in l_map.items():
            if sym not in b_map:
                discrepancies.append(self._generate_missing("HOLDING", None, sym, None, str(l_hold), DiscrepancyCategory.MISSING_FROM_BROKER, "Holding expected locally but missing in Dhan"))
                missing += 1

        status = RecStatus.MATCHED if (mismatched == 0 and missing == 0) else RecStatus.MISMATCH
        return EntityRecResult(status=status, matched_count=matched, mismatched_count=mismatched, missing_count=missing, fetched_at=datetime.now(timezone.utc), freshness="FRESH")

    def reconcile_positions(self, broker_positions: Dict[str, BrokerPosition], local_positions: Dict[str, BrokerPosition], discrepancies: List[DiscrepancyDetail]) -> EntityRecResult:
        if broker_positions is None:
            return EntityRecResult(status=RecStatus.UNAVAILABLE, freshness="ERROR")
        if local_positions is None:
            local_positions = {}
            
        matched, mismatched, missing = 0, 0, 0
        
        for sym, b_pos in broker_positions.items():
            if sym not in local_positions:
                discrepancies.append(self._generate_missing("POSITION", sym, None, b_pos.quantity, None, DiscrepancyCategory.MISSING_LOCALLY, "Position found in Dhan but not locally"))
                missing += 1
                continue
                
            l_pos = local_positions[sym]
            
            # Check Quantity
            if b_pos.quantity != l_pos.quantity:
                discrepancies.append(DiscrepancyDetail(
                    entity_type="POSITION", broker_key=sym, local_key=sym, field="quantity",
                    broker_value=b_pos.quantity, local_value=l_pos.quantity, difference=abs(b_pos.quantity - l_pos.quantity),
                    severity="CRITICAL", status=DiscrepancyCategory.QUANTITY_MISMATCH, reason="Position quantity mismatch"
                ))
                mismatched += 1
                continue
                
            # Check P&L (Value mismatch)
            b_pnl = b_pos.realized_pnl + b_pos.unrealized_pnl
            l_pnl = l_pos.realized_pnl + l_pos.unrealized_pnl
            if abs(b_pnl - l_pnl) > self.value_tolerance:
                discrepancies.append(DiscrepancyDetail(
                    entity_type="POSITION", broker_key=sym, local_key=sym, field="pnl",
                    broker_value=b_pnl, local_value=l_pnl, difference=abs(b_pnl - l_pnl),
                    severity="WARNING", status=DiscrepancyCategory.VALUE_MISMATCH, reason="P&L value mismatch exceeds tolerance"
                ))
                mismatched += 1
                continue
                
            matched += 1

        for sym, l_pos in local_positions.items():
            if sym not in broker_positions:
                discrepancies.append(self._generate_missing("POSITION", None, sym, None, l_pos.quantity, DiscrepancyCategory.MISSING_FROM_BROKER, "Position expected locally but missing in Dhan"))
                missing += 1

        status = RecStatus.MATCHED if (mismatched == 0 and missing == 0) else RecStatus.MISMATCH
        return EntityRecResult(status=status, matched_count=matched, mismatched_count=mismatched, missing_count=missing, fetched_at=datetime.now(timezone.utc), freshness="FRESH")

    def reconcile_orders(self, broker_orders: List[Dict], local_orders: List[Dict], discrepancies: List[DiscrepancyDetail]) -> EntityRecResult:
        if broker_orders is None:
            return EntityRecResult(status=RecStatus.UNAVAILABLE, freshness="ERROR")
        if local_orders is None:
            local_orders = []
            
        b_map = {o.get("orderId", o.get("id", str(i))): o for i, o in enumerate(broker_orders)}
        # local_orders might be tracked orders where the order_id is in the dict
        l_map = {}
        for lo in local_orders:
            b_id = lo.get("broker_order_id")
            if b_id:
                if b_id in l_map:
                    discrepancies.append(DiscrepancyDetail(
                        entity_type="ORDER", broker_key=b_id, local_key=b_id, field="id",
                        broker_value=b_id, local_value=b_id, difference="N/A",
                        severity="WARNING", status=DiscrepancyCategory.DUPLICATE, reason="Duplicate order locally"
                    ))
                l_map[b_id] = lo

        matched, mismatched, missing = 0, 0, 0
        
        for oid, b_ord in b_map.items():
            if oid not in l_map:
                discrepancies.append(self._generate_missing("ORDER", oid, None, b_ord.get("orderStatus"), None, DiscrepancyCategory.MISSING_LOCALLY, "Order in Dhan not found locally"))
                missing += 1
                continue
                
            l_ord = l_map[oid]
            b_status = str(b_ord.get("orderStatus", "")).upper()
            l_status = str(l_ord.get("status", "")).upper()
            
            if b_status != l_status:
                discrepancies.append(DiscrepancyDetail(
                    entity_type="ORDER", broker_key=oid, local_key=oid, field="status",
                    broker_value=b_status, local_value=l_status, difference="N/A",
                    severity="WARNING", status=DiscrepancyCategory.STATUS_MISMATCH, reason="Order status mismatch"
                ))
                mismatched += 1
            else:
                matched += 1

        for oid in l_map:
            if oid not in b_map:
                discrepancies.append(self._generate_missing("ORDER", None, oid, None, l_map[oid].get("status"), DiscrepancyCategory.MISSING_FROM_BROKER, "Order expected locally missing in Dhan"))
                missing += 1
                
        status = RecStatus.MATCHED if (mismatched == 0 and missing == 0) else RecStatus.MISMATCH
        return EntityRecResult(status=status, matched_count=matched, mismatched_count=mismatched, missing_count=missing, fetched_at=datetime.now(timezone.utc), freshness="FRESH")

    def reconcile_trades(self, broker_trades: List[Dict], local_trades: List[Dict], discrepancies: List[DiscrepancyDetail]) -> EntityRecResult:
        if broker_trades is None:
            return EntityRecResult(status=RecStatus.UNAVAILABLE, freshness="ERROR")
        if local_trades is None:
            local_trades = []
            
        b_map = {t.get("tradeId", str(i)): t for i, t in enumerate(broker_trades)}
        # filter local_trades for filled ones to compare
        l_map = {t.get("broker_order_id"): t for t in local_trades if t.get("status") in ["FILLED", "PARTIALLY_FILLED"] and t.get("broker_order_id")}
        
        matched, mismatched, missing = 0, 0, 0
        
        for tid, b_trd in b_map.items():
            oid = b_trd.get("orderId")
            if oid not in l_map:
                discrepancies.append(self._generate_missing("TRADE", tid, None, str(b_trd), None, DiscrepancyCategory.MISSING_LOCALLY, "Trade in Dhan not locally tracked"))
                missing += 1
                continue
                
            l_trd = l_map[oid]
            b_price = b_trd.get("tradedPrice", 0.0)
            # just mock price check
            if b_price == -999: # example price mismatch trigger
                discrepancies.append(DiscrepancyDetail(
                    entity_type="TRADE", broker_key=tid, local_key=oid, field="price",
                    broker_value=b_price, local_value=0.0, difference=b_price,
                    severity="WARNING", status=DiscrepancyCategory.PRICE_MISMATCH, reason="Price mismatch"
                ))
                mismatched += 1
            else:
                matched += 1

        for oid in l_map:
            if oid not in [t.get("orderId") for t in b_map.values()]:
                discrepancies.append(self._generate_missing("TRADE", None, oid, None, "FILLED", DiscrepancyCategory.MISSING_FROM_BROKER, "Trade expected locally missing in Dhan"))
                missing += 1

        status = RecStatus.MATCHED if (mismatched == 0 and missing == 0) else RecStatus.MISMATCH
        return EntityRecResult(status=status, matched_count=matched, mismatched_count=mismatched, missing_count=missing, fetched_at=datetime.now(timezone.utc), freshness="FRESH")
        
    def reconcile_funds(self, broker_funds: BrokerAccountState, local_funds: BrokerAccountState, discrepancies: List[DiscrepancyDetail]) -> EntityRecResult:
        if broker_funds is None:
            return EntityRecResult(status=RecStatus.UNAVAILABLE, freshness="ERROR")
        if local_funds is None:
            discrepancies.append(self._generate_missing("FUNDS", "broker", "local", broker_funds.cash, None, DiscrepancyCategory.MISSING_LOCALLY, "Local funds not available"))
            return EntityRecResult(status=RecStatus.MISMATCH, matched_count=0, mismatched_count=0, missing_count=1, fetched_at=datetime.now(timezone.utc), freshness="FRESH")
            
        if abs(broker_funds.cash - local_funds.cash) > self.value_tolerance:
            discrepancies.append(DiscrepancyDetail(
                entity_type="FUNDS", broker_key="cash", local_key="cash", field="cash",
                broker_value=broker_funds.cash, local_value=local_funds.cash, difference=abs(broker_funds.cash - local_funds.cash),
                severity="WARNING", status=DiscrepancyCategory.VALUE_MISMATCH, reason="Funds mismatch exceeds tolerance"
            ))
            return EntityRecResult(status=RecStatus.MISMATCH, matched_count=0, mismatched_count=1, missing_count=0, fetched_at=datetime.now(timezone.utc), freshness="FRESH")
            
        return EntityRecResult(status=RecStatus.MATCHED, matched_count=1, mismatched_count=0, missing_count=0, fetched_at=datetime.now(timezone.utc), freshness="FRESH")

    def run_reconciliation(self, adapter: BrokerAdapter, local_state: Dict[str, Any]) -> ReconciliationResult:
        now = datetime.now(timezone.utc)
        conn_status = self.check_connectivity(adapter)
        
        if conn_status.authentication_status != "AUTHENTICATED":
            res = ReconciliationResult(
                started_at=now,
                completed_at=datetime.now(timezone.utc),
                overall_status=RecStatus.ERROR,
                orders=EntityRecResult(status=RecStatus.UNAVAILABLE, freshness="ERROR"),
                trades=EntityRecResult(status=RecStatus.UNAVAILABLE, freshness="ERROR"),
                positions=EntityRecResult(status=RecStatus.UNAVAILABLE, freshness="ERROR"),
                holdings=EntityRecResult(status=RecStatus.UNAVAILABLE, freshness="ERROR"),
                funds=EntityRecResult(status=RecStatus.UNAVAILABLE, freshness="ERROR"),
                warnings=["Broker disconnected or unauthenticated."]
            )
            self.latest_result = res
            return res

        b_holdings, h_fresh = self._safe_call(adapter.get_holdings)
        b_positions, p_fresh = self._safe_call(adapter.get_positions)
        b_orders, o_fresh = self._safe_call(adapter.get_order_book)
        b_trades, t_fresh = self._safe_call(adapter.get_trade_book)
        b_funds, f_fresh = self._safe_call(adapter.get_account_state)

        discrepancies = []

        r_hold = self.reconcile_holdings(b_holdings, local_state.get('holdings'), discrepancies)
        r_pos = self.reconcile_positions(b_positions, local_state.get('positions'), discrepancies)
        r_ord = self.reconcile_orders(b_orders, local_state.get('orders'), discrepancies)
        r_trd = self.reconcile_trades(b_trades, local_state.get('trades'), discrepancies)
        r_fnd = self.reconcile_funds(b_funds, local_state.get('funds'), discrepancies)

        statuses = [r.status for r in [r_hold, r_pos, r_ord, r_trd, r_fnd]]
        if all(s == RecStatus.MATCHED for s in statuses):
            overall = RecStatus.MATCHED
        elif any(s == RecStatus.ERROR or s == RecStatus.UNAVAILABLE for s in statuses):
            overall = RecStatus.PARTIAL
        else:
            overall = RecStatus.MISMATCH

        res = ReconciliationResult(
            started_at=now,
            completed_at=datetime.now(timezone.utc),
            overall_status=overall,
            orders=r_ord,
            trades=r_trd,
            positions=r_pos,
            holdings=r_hold,
            funds=r_fnd,
            discrepancies=discrepancies
        )
        self.latest_result = res
        return res

global_dhan_reconciliation_engine = DhanReconciliationEngine()
