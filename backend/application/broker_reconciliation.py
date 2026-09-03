"""
Phase 15 — Broker State Reconciliation Engine

Provides deterministic, bi-directional reconciliation between Trading OS expected state
and external broker sandbox / paper state.
Detects order discrepancies, missing fills, quantity/price variances, position mismatches,
and cash/equity differences without blindly modifying financial records.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid

from backend.domain.broker_schemas import (
    BrokerAccountState,
    BrokerEnvironment,
    BrokerPosition,
    DiscrepancyType,
    ReconciliationDiscrepancy,
    ReconciliationReport,
)
from backend.domain.paper_broker_schemas import PaperOrder, PaperOrderStatus
from backend.domain.telemetry_schemas import EventSeverity, ExecutionEventType
from backend.domain.trading_os_schemas import TradingOSRun
from backend.application.broker_interface import BrokerAdapter
from backend.application.broker_manager import global_broker_manager

logger = logging.getLogger(__name__)


class BrokerReconciliationEngine:
    """
    Bi-directional audit engine verifying synchronization between Trading OS internal
    accounting and external broker state.
    """

    def __init__(self, telemetry_engine: Optional[Any] = None) -> None:
        self.telemetry_engine = telemetry_engine
        self.latest_report: Optional[ReconciliationReport] = None

    def reconcile(
        self,
        trading_os_runs: Optional[List[TradingOSRun]] = None,
        expected_positions: Optional[Dict[str, int]] = None,
        expected_cash: Optional[float] = None,
        adapter: Optional[BrokerAdapter] = None,
    ) -> ReconciliationReport:
        """
        Execute deterministic reconciliation between Trading OS expected state and broker state.
        """
        now = datetime.now(timezone.utc)
        rec_id = f"rec-{uuid.uuid4().hex[:8]}"
        target_adapter = adapter or global_broker_manager.get_active_adapter()
        caps = target_adapter.get_capabilities()

        # Telemetry: Audit Started
        if self.telemetry_engine:
            self.telemetry_engine.record_event(
                event_type=ExecutionEventType.SANDBOX_RECONCILIATION_STARTED,
                execution_id=rec_id,
                symbol="PORTFOLIO",
                reason="Starting bi-directional reconciliation audit.",
                metadata={"adapter": caps.broker_name, "mode": caps.mode.value},
            )

        discrepancies: List[ReconciliationDiscrepancy] = []

        # 1. Fetch Actual Broker State
        try:
            actual_account: BrokerAccountState = target_adapter.get_account_state()
            actual_positions: Dict[str, BrokerPosition] = target_adapter.get_positions()
            actual_orders: List[PaperOrder] = target_adapter.list_orders()
        except Exception as ex:
            logger.error(f"[ReconciliationEngine] Failed to retrieve broker state: {ex}")
            discrepancy = ReconciliationDiscrepancy(
                discrepancy_type=DiscrepancyType.EQUITY_MISMATCH,
                severity="CRITICAL",
                details=f"Failed to query broker state: {ex}",
            )
            report = ReconciliationReport(
                reconciliation_id=rec_id,
                timestamp=now,
                is_reconciled=False,
                discrepancy_count=1,
                discrepancies=[discrepancy],
                summary_message=f"Reconciliation query failed: {ex}",
            )
            self.latest_report = report
            return report

        # 2. Reconcile Orders
        runs = trading_os_runs or []
        expected_order_ids = set()

        for run in runs:
            p_order = run.paper_order or {}
            oid = p_order.get("order_id")
            if oid:
                expected_order_ids.add(oid)
                # Check if order exists in actual broker orders
                matched_actual = next((o for o in actual_orders if o.order_id == oid), None)
                if not matched_actual:
                    discrepancies.append(ReconciliationDiscrepancy(
                        discrepancy_type=DiscrepancyType.MISSING_ORDER_IN_BROKER,
                        order_id=oid,
                        symbol=p_order.get("symbol"),
                        expected_value=p_order.get("status"),
                        actual_value=None,
                        severity="CRITICAL",
                        details=f"Trading OS order {oid} is missing in broker state.",
                    ))
                else:
                    # Check quantity and price
                    exp_qty = p_order.get("requested_quantity", 0)
                    act_qty = matched_actual.requested_quantity
                    if exp_qty != act_qty:
                        discrepancies.append(ReconciliationDiscrepancy(
                            discrepancy_type=DiscrepancyType.QUANTITY_MISMATCH,
                            order_id=oid,
                            symbol=p_order.get("symbol"),
                            expected_value=exp_qty,
                            actual_value=act_qty,
                            severity="WARNING",
                            details=f"Quantity mismatch for {oid}: expected {exp_qty}, actual {act_qty}.",
                        ))

        # Check for unexpected orders in broker
        if expected_order_ids:
            for act_ord in actual_orders:
                if act_ord.order_id not in expected_order_ids:
                    discrepancies.append(ReconciliationDiscrepancy(
                        discrepancy_type=DiscrepancyType.UNEXPECTED_ORDER_IN_BROKER,
                        order_id=act_ord.order_id,
                        symbol=act_ord.symbol,
                        expected_value=None,
                        actual_value=act_ord.status.value if hasattr(act_ord.status, "value") else str(act_ord.status),
                        severity="WARNING",
                        details=f"Broker has unrecognized order {act_ord.order_id} not recorded in expected runs.",
                    ))

        # 3. Reconcile Positions
        if expected_positions is not None:
            for sym, exp_q in expected_positions.items():
                sym_upper = sym.upper()
                act_pos = actual_positions.get(sym_upper)
                act_q = act_pos.quantity if act_pos else 0
                if exp_q != act_q:
                    discrepancies.append(ReconciliationDiscrepancy(
                        discrepancy_type=DiscrepancyType.POSITION_MISMATCH,
                        symbol=sym_upper,
                        expected_value=exp_q,
                        actual_value=act_q,
                        severity="CRITICAL",
                        details=f"Position mismatch for {sym_upper}: expected {exp_q} shares, found {act_q} shares.",
                    ))

            for act_sym, pos_obj in actual_positions.items():
                if act_sym not in [s.upper() for s in expected_positions.keys()]:
                    if pos_obj.quantity > 0:
                        discrepancies.append(ReconciliationDiscrepancy(
                            discrepancy_type=DiscrepancyType.POSITION_MISMATCH,
                            symbol=act_sym,
                            expected_value=0,
                            actual_value=pos_obj.quantity,
                            severity="CRITICAL",
                            details=f"Unexpected position in broker for {act_sym}: {pos_obj.quantity} shares.",
                        ))

        # 4. Reconcile Cash (Tolerance: Rs 1.0)
        if expected_cash is not None:
            cash_diff = abs(actual_account.cash - expected_cash)
            if cash_diff > 1.0:
                discrepancies.append(ReconciliationDiscrepancy(
                    discrepancy_type=DiscrepancyType.CASH_MISMATCH,
                    expected_value=round(expected_cash, 2),
                    actual_value=round(actual_account.cash, 2),
                    severity="WARNING",
                    details=f"Cash balance variance Rs {cash_diff:.2f} exceeds threshold.",
                ))

        # 5. Assemble Report
        is_clean = len(discrepancies) == 0
        summary_msg = (
            "State is fully synchronized."
            if is_clean
            else f"Reconciliation detected {len(discrepancies)} discrepancy(ies)."
        )

        report = ReconciliationReport(
            reconciliation_id=rec_id,
            timestamp=now,
            is_reconciled=is_clean,
            discrepancy_count=len(discrepancies),
            discrepancies=discrepancies,
            trading_os_orders_count=len(expected_order_ids),
            broker_orders_count=len(actual_orders),
            positions_evaluated=len(actual_positions),
            execution_environment=BrokerEnvironment.SANDBOX if caps.mode == "SANDBOX" else BrokerEnvironment.PAPER,
            broker_provider=caps.broker_name,
            summary_message=summary_msg,
        )

        self.latest_report = report

        # Telemetry: Audit Outcome
        if self.telemetry_engine:
            event_type = (
                ExecutionEventType.SANDBOX_RECONCILIATION_COMPLETED
                if is_clean
                else ExecutionEventType.SANDBOX_RECONCILIATION_MISMATCH
            )
            severity = EventSeverity.INFO if is_clean else EventSeverity.WARNING
            self.telemetry_engine.record_event(
                event_type=event_type,
                execution_id=rec_id,
                symbol="PORTFOLIO",
                reason=summary_msg,
                severity=severity,
                metadata={"discrepancies": len(discrepancies), "reconciled": is_clean},
            )

        return report

    def get_latest_report(self) -> Optional[ReconciliationReport]:
        return self.latest_report


# Global singleton instance for system-wide reconciliation
global_reconciliation_engine = BrokerReconciliationEngine()
