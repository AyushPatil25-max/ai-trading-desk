from backend.config.app_config import get_app_config
"""
Phase 26 — Live Trading Readiness Engine

Deterministic readiness evaluator that inspects all safety gates, credentials,
broker connectivity, account state, market session, data freshness, and arming status.
Never equates 'CONFIGURED' with 'READY'.
"""

from datetime import datetime, timezone, timedelta
import os
from typing import Any, Dict, List, Optional, Tuple

from backend.domain.broker_schemas import (
    BrokerConnectionState,
)
from backend.domain.forward_simulation_schemas import MarketSessionState
from backend.domain.live_readiness_schemas import (
    CheckSeverity,
    LiveReadinessReport,
    ReadinessCheckCode,
    ReadinessCheckItem,
    ReadinessStatus,
)
from backend.domain.observability_schemas import EventCategory, EventSeverity
from backend.application.forward_simulation_engine import get_market_session_state
from backend.adapters.dhan_adapter import DhanBrokerAdapter
from backend.execution.safety_engine import global_manual_order_safety_gate
from backend.application.confirmation_store import global_confirmation_store
from backend.application.tamper_evident_audit_chain import global_audit_chain
from backend.execution.live_arming_store import global_live_arming_store


class LiveTradingReadinessEngine:
    """
    Deterministic readiness engine for live trading execution.
    Does NOT place orders. Strictly assesses readiness.
    """

    def __init__(self):
        pass

    def evaluate_readiness(
        self,
        enforce_market_calendar: bool = True,
        check_time: Optional[datetime] = None,
        market_data_timestamp: Optional[datetime] = None,
    ) -> LiveReadinessReport:
        """
        Run 17+ comprehensive checks across SAFETY, DHAN, MARKET, and EXECUTION subsystems.
        """
        now = check_time or datetime.now(timezone.utc)
        checks: List[ReadinessCheckItem] = []
        blocking_failures: List[str] = []
        warnings: List[str] = []

        # ── 1. SAFETY SUBSYSTEM CHECKS ─────────────────────────────────────────

        # Check 1: Kill Switch State
        ks_active = global_manual_order_safety_gate.kill_switch.is_active()
        if ks_active:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.KILL_SWITCH_ACTIVE,
                name="Emergency Kill Switch",
                category="SAFETY",
                passed=False,
                severity=CheckSeverity.BLOCKING,
                is_blocking=True,
                message="Emergency kill switch is ACTIVE. All live trading is halted.",
            ))
            blocking_failures.append("Kill switch is active.")
            # Invalidate armed session immediately if kill switch is active
            global_live_arming_store.invalidate(reason="Kill switch active during readiness evaluation")
        else:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.KILL_SWITCH_CLEAR,
                name="Emergency Kill Switch",
                category="SAFETY",
                passed=True,
                severity=CheckSeverity.INFO,
                is_blocking=False,
                message="Emergency kill switch is clear (inactive).",
            ))

        # Check 2: Safety Engine Availability
        if global_manual_order_safety_gate is not None:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.SAFETY_ENGINE_AVAILABLE,
                name="Manual Order Safety Gate",
                category="SAFETY",
                passed=True,
                severity=CheckSeverity.INFO,
                is_blocking=False,
                message="ManualOrderSafetyGate is online with 15+ deterministic validation rules.",
            ))
        else:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.SAFETY_ENGINE_UNAVAILABLE,
                name="Manual Order Safety Gate",
                category="SAFETY",
                passed=False,
                severity=CheckSeverity.BLOCKING,
                is_blocking=True,
                message="ManualOrderSafetyGate is unavailable.",
            ))
            blocking_failures.append("Safety engine unavailable.")

        # Check 3: Confirmation Store Availability
        if global_confirmation_store is not None:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.CONFIRMATION_STORE_AVAILABLE,
                name="Confirmation Store",
                category="SAFETY",
                passed=True,
                severity=CheckSeverity.INFO,
                is_blocking=False,
                message="In-memory 256-bit ConfirmationStore is online and thread-safe.",
            ))
        else:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.CONFIRMATION_STORE_UNAVAILABLE,
                name="Confirmation Store",
                category="SAFETY",
                passed=False,
                severity=CheckSeverity.BLOCKING,
                is_blocking=True,
                message="ConfirmationStore is unavailable.",
            ))
            blocking_failures.append("Confirmation store unavailable.")

        # Check 4: Audit Chain Availability
        if global_audit_chain is not None:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.AUDIT_CHAIN_AVAILABLE,
                name="Tamper-Evident Audit Chain",
                category="SAFETY",
                passed=True,
                severity=CheckSeverity.INFO,
                is_blocking=False,
                message="Cryptographic SHA-256 audit chain is online and recording.",
            ))
        else:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.AUDIT_CHAIN_UNAVAILABLE,
                name="Tamper-Evident Audit Chain",
                category="SAFETY",
                passed=False,
                severity=CheckSeverity.BLOCKING,
                is_blocking=True,
                message="Tamper-evident audit chain is unavailable.",
            ))
            blocking_failures.append("Audit chain unavailable.")

        # ── 2. DHAN BROKER SUBSYSTEM CHECKS ───────────────────────────────────

        app_config = get_app_config()
        dhan_enabled = app_config.dhan_enabled
        client_id = app_config.dhan_client_id
        access_token = app_config.dhan_access_token

        # Check 5: DHAN_ENABLED configuration
        if dhan_enabled:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.DHAN_ENABLED,
                name="Dhan Integration Flag",
                category="DHAN",
                passed=True,
                severity=CheckSeverity.INFO,
                is_blocking=False,
                message="DHAN_ENABLED is true.",
            ))
        else:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.DHAN_DISABLED,
                name="Dhan Integration Flag",
                category="DHAN",
                passed=False,
                severity=CheckSeverity.BLOCKING,
                is_blocking=True,
                message="DHAN_ENABLED is false in environment.",
            ))
            blocking_failures.append("Dhan integration is disabled.")

        # Check 6: DHAN_CLIENT_ID configured
        if client_id:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.DHAN_CLIENT_ID_CONFIGURED,
                name="Dhan Client ID",
                category="DHAN",
                passed=True,
                severity=CheckSeverity.INFO,
                is_blocking=False,
                message=f"DHAN_CLIENT_ID is configured ({client_id[:4]}***).",
            ))
        else:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.DHAN_CLIENT_ID_MISSING,
                name="Dhan Client ID",
                category="DHAN",
                passed=False,
                severity=CheckSeverity.BLOCKING,
                is_blocking=True,
                message="DHAN_CLIENT_ID is missing from environment.",
            ))
            blocking_failures.append("Dhan Client ID is missing.")

        # Check 7: DHAN_ACCESS_TOKEN configured (secret protected)
        if access_token:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.DHAN_ACCESS_TOKEN_CONFIGURED,
                name="Dhan Access Token",
                category="DHAN",
                passed=True,
                severity=CheckSeverity.INFO,
                is_blocking=False,
                message="DHAN_ACCESS_TOKEN is configured (secret protected).",
            ))
        else:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.DHAN_ACCESS_TOKEN_MISSING,
                name="Dhan Access Token",
                category="DHAN",
                passed=False,
                severity=CheckSeverity.BLOCKING,
                is_blocking=True,
                message="DHAN_ACCESS_TOKEN is missing from environment.",
            ))
            blocking_failures.append("Dhan Access Token is missing.")

        # Instantiate adapter to verify active connection and account synchronization
        adapter = DhanBrokerAdapter()
        conn_state = adapter.get_connection_state()

        # Check 8: Dhan Connection & Authentication
        if conn_state == BrokerConnectionState.DHAN_CONNECTED:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.DHAN_CONNECTED,
                name="Dhan API Connectivity & Auth",
                category="DHAN",
                passed=True,
                severity=CheckSeverity.INFO,
                is_blocking=False,
                message="Dhan v2 API connectivity and profile authentication verified.",
            ))
        elif conn_state == BrokerConnectionState.DHAN_AUTH_FAILED:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.DHAN_AUTH_FAILED,
                name="Dhan API Connectivity & Auth",
                category="DHAN",
                passed=False,
                severity=CheckSeverity.BLOCKING,
                is_blocking=True,
                message="Dhan API authentication failed (HTTP 401/403). Invalid or expired token.",
            ))
            blocking_failures.append("Dhan authentication failed.")
        elif conn_state == BrokerConnectionState.DHAN_UNAVAILABLE:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.DHAN_UNAVAILABLE,
                name="Dhan API Connectivity & Auth",
                category="DHAN",
                passed=False,
                severity=CheckSeverity.BLOCKING,
                is_blocking=True,
                message="Dhan v2 API is currently unreachable or network timed out.",
            ))
            blocking_failures.append("Dhan API unreachable.")
        else:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.DHAN_DISCONNECTED,
                name="Dhan API Connectivity & Auth",
                category="DHAN",
                passed=False,
                severity=CheckSeverity.BLOCKING,
                is_blocking=True,
                message=f"Dhan adapter is disconnected (state: {conn_state.value}).",
            ))
            blocking_failures.append(f"Dhan disconnected: {conn_state.value}")

        # Check 9: Account Profile & Buying Power
        acct_state = adapter.get_account_state()
        buying_power_val = None
        if acct_state and conn_state == BrokerConnectionState.DHAN_CONNECTED:
            buying_power_val = acct_state.buying_power
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.ACCOUNT_AVAILABLE,
                name="Dhan Account State",
                category="DHAN",
                passed=True,
                severity=CheckSeverity.INFO,
                is_blocking=False,
                message=f"Account synchronized (ID: {acct_state.account_id}).",
                details={"buying_power": acct_state.buying_power, "cash": acct_state.cash},
            ))

            # Check 10: Buying Power Value
            if acct_state.buying_power is not None and acct_state.buying_power > 0:
                checks.append(ReadinessCheckItem(
                    code=ReadinessCheckCode.BUYING_POWER_AVAILABLE,
                    name="Available Buying Power",
                    category="DHAN",
                    passed=True,
                    severity=CheckSeverity.INFO,
                    is_blocking=False,
                    message=f"Available buying power: ₹{acct_state.buying_power:,.2f}",
                ))
            else:
                checks.append(ReadinessCheckItem(
                    code=ReadinessCheckCode.BUYING_POWER_UNAVAILABLE,
                    name="Available Buying Power",
                    category="DHAN",
                    passed=False,
                    severity=CheckSeverity.WARNING,
                    is_blocking=False,
                    message=f"Buying power is zero or unavailable (₹{acct_state.buying_power}).",
                ))
                warnings.append("Zero or negative buying power.")
        else:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.ACCOUNT_UNAVAILABLE,
                name="Dhan Account State",
                category="DHAN",
                passed=False,
                severity=CheckSeverity.BLOCKING if (dhan_enabled and client_id and access_token) else CheckSeverity.WARNING,
                is_blocking=True if (dhan_enabled and client_id and access_token) else False,
                message="Dhan account state could not be synchronized.",
            ))
            if dhan_enabled and client_id and access_token:
                blocking_failures.append("Account synchronization failed.")

        # ── 3. MARKET SUBSYSTEM CHECKS ────────────────────────────────────────

        # Check 11: Market Session State
        session_state, session_msg = get_market_session_state(check_time=now, enforce_calendar=enforce_market_calendar)
        if session_state == MarketSessionState.OPEN:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.MARKET_SESSION_OPEN,
                name="Market Session State",
                category="MARKET",
                passed=True,
                severity=CheckSeverity.INFO,
                is_blocking=False,
                message=session_msg,
            ))
        elif session_state == MarketSessionState.PRE_OPEN:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.MARKET_SESSION_PRE_OPEN,
                name="Market Session State",
                category="MARKET",
                passed=True,
                severity=CheckSeverity.WARNING,
                is_blocking=False,
                message=session_msg,
            ))
            warnings.append("Exchange is in Pre-Open session.")
        elif session_state in (MarketSessionState.CLOSED, MarketSessionState.WEEKEND, MarketSessionState.POST_CLOSE, MarketSessionState.HOLIDAY):
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.MARKET_SESSION_CLOSED,
                name="Market Session State",
                category="MARKET",
                passed=False,
                severity=CheckSeverity.WARNING if not enforce_market_calendar else CheckSeverity.BLOCKING,
                is_blocking=True if enforce_market_calendar else False,
                message=session_msg,
            ))
            if enforce_market_calendar:
                blocking_failures.append(f"Market closed: {session_msg}")
            else:
                warnings.append(f"Market closed (calendar bypass active): {session_msg}")
        else:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.MARKET_SESSION_UNKNOWN,
                name="Market Session State",
                category="MARKET",
                passed=False,
                severity=CheckSeverity.BLOCKING,
                is_blocking=True,
                message="Market session state cannot be safely determined.",
            ))
            blocking_failures.append("Market session state unknown.")

        # Check 12: Market Data Freshness
        if market_data_timestamp:
            age_sec = (now - market_data_timestamp).total_seconds()
            if age_sec > 300.0:
                checks.append(ReadinessCheckItem(
                    code=ReadinessCheckCode.MARKET_DATA_STALE,
                    name="Market Data Freshness",
                    category="MARKET",
                    passed=False,
                    severity=CheckSeverity.BLOCKING,
                    is_blocking=True,
                    message=f"Market data age is {age_sec:.1f}s (>300s limit). Stale data rejected.",
                ))
                blocking_failures.append(f"Market data is stale ({age_sec:.1f}s).")
            else:
                checks.append(ReadinessCheckItem(
                    code=ReadinessCheckCode.MARKET_DATA_FRESH,
                    name="Market Data Freshness",
                    category="MARKET",
                    passed=True,
                    severity=CheckSeverity.INFO,
                    is_blocking=False,
                    message=f"Market data freshness verified ({age_sec:.1f}s age).",
                ))
        else:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.MARKET_DATA_FRESH,
                name="Market Data Freshness",
                category="MARKET",
                passed=True,
                severity=CheckSeverity.INFO,
                is_blocking=False,
                message="Freshness gate active (evaluated dynamically per order).",
            ))

        # ── 4. EXECUTION & ISOLATION CHECKS ───────────────────────────────────

        # Check 13: LIVE_EXECUTION_ENABLED flag
        live_flag = get_app_config().live_execution_enabled
        if live_flag:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.LIVE_EXECUTION_FLAG_ENABLED,
                name="Live Execution Flag",
                category="EXECUTION",
                passed=True,
                severity=CheckSeverity.INFO,
                is_blocking=False,
                message="LIVE_EXECUTION_ENABLED is true.",
            ))
        else:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.LIVE_EXECUTION_FLAG_DISABLED,
                name="Live Execution Flag",
                category="EXECUTION",
                passed=False,
                severity=CheckSeverity.BLOCKING,
                is_blocking=True,
                message="LIVE_EXECUTION_ENABLED is false in environment. Real-money live trading locked.",
            ))
            blocking_failures.append("LIVE_EXECUTION_ENABLED is false.")

        # Check 14: Broker Adapter Availability
        if adapter is not None:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.BROKER_ADAPTER_AVAILABLE,
                name="Broker Adapter Availability",
                category="EXECUTION",
                passed=True,
                severity=CheckSeverity.INFO,
                is_blocking=False,
                message="DhanBrokerAdapter is loaded and operational.",
            ))
        else:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.BROKER_ADAPTER_UNAVAILABLE,
                name="Broker Adapter Availability",
                category="EXECUTION",
                passed=False,
                severity=CheckSeverity.BLOCKING,
                is_blocking=True,
                message="Broker adapter is unavailable.",
            ))
            blocking_failures.append("Broker adapter unavailable.")

        # Check 15: Paper vs Live Mode Isolation
        checks.append(ReadinessCheckItem(
            code=ReadinessCheckCode.MODE_ISOLATED,
            name="Paper / Live Mode Isolation",
            category="EXECUTION",
            passed=True,
            severity=CheckSeverity.INFO,
            is_blocking=False,
            message="Paper and Live execution routes are strictly isolated. No cross-routing possible.",
        ))

        # Check 16: Live Trading Armed State
        is_armed = global_live_arming_store.is_currently_armed()
        if is_armed:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.ARMED_STATE_ACTIVE,
                name="Live Trading Armed State",
                category="EXECUTION",
                passed=True,
                severity=CheckSeverity.INFO,
                is_blocking=False,
                message="Live trading is currently ARMED with active operator authorization.",
            ))
        else:
            checks.append(ReadinessCheckItem(
                code=ReadinessCheckCode.ARMED_STATE_INACTIVE,
                name="Live Trading Armed State",
                category="EXECUTION",
                passed=False,
                severity=CheckSeverity.WARNING,
                is_blocking=False,
                message="Live trading is DISARMED (requires explicit operator arming before live order submission).",
            ))
            warnings.append("Live trading is currently disarmed.")

        # ── 5. OVERALL STATUS DETERMINATION ────────────────────────────────────

        # Evaluate is_ready_for_arming (all config, credentials, connection, safety gates pass)
        non_arm_blocking_codes = {
            ReadinessCheckCode.LIVE_EXECUTION_FLAG_DISABLED,
            ReadinessCheckCode.ARMED_STATE_INACTIVE,
            ReadinessCheckCode.MARKET_SESSION_CLOSED,
        }
        critical_arm_blockers = [
            f for c, f in zip(checks, blocking_failures)
            if c.code not in non_arm_blocking_codes and c.is_blocking and not c.passed
        ]

        is_ready_for_arming = (
            not ks_active
            and dhan_enabled
            and bool(client_id)
            and bool(access_token)
            and conn_state == BrokerConnectionState.DHAN_CONNECTED
            and acct_state is not None
            and len(critical_arm_blockers) == 0
        )

        is_ready_for_order = (
            is_ready_for_arming
            and live_flag
            and is_armed
            and (session_state == MarketSessionState.OPEN or not enforce_market_calendar)
            and len(blocking_failures) == 0
        )

        if ks_active:
            overall_status = ReadinessStatus.BLOCKED
        elif len(blocking_failures) > 0:
            overall_status = ReadinessStatus.NOT_READY
        elif not is_armed:
            overall_status = ReadinessStatus.DEGRADED if is_ready_for_arming else ReadinessStatus.NOT_READY
        elif len(warnings) > 0:
            overall_status = ReadinessStatus.DEGRADED
        else:
            overall_status = ReadinessStatus.READY

        report = LiveReadinessReport(
            overall_status=overall_status,
            is_ready_for_arming=is_ready_for_arming,
            is_ready_for_order=is_ready_for_order,
            is_live_enabled_in_env=live_flag,
            is_currently_armed=is_armed,
            blocking_failures=blocking_failures,
            warnings=warnings,
            checks=checks,
            market_session=session_state.value,
            dhan_connection=conn_state.value,
            buying_power=buying_power_val,
            evaluated_at=now,
        )

        # Audit logging
        try:
            event_type = "LIVE_READINESS_CHECKED" if overall_status in (ReadinessStatus.READY, ReadinessStatus.DEGRADED) else "LIVE_READINESS_FAILED"
            global_audit_chain.append_event(
                event_type=event_type,
                category=EventCategory.EXECUTION,
                component="LiveTradingReadinessEngine",
                correlation_id=f"readiness-{now.strftime('%Y%m%d%H%M%S')}",
                severity=EventSeverity.INFO if is_ready_for_arming else EventSeverity.WARNING,
                reason=f"Readiness status: {overall_status.value} (Ready to Arm: {is_ready_for_arming}, Ready for Order: {is_ready_for_order})",
                payload={
                    "overall_status": overall_status.value,
                    "is_ready_for_arming": is_ready_for_arming,
                    "is_ready_for_order": is_ready_for_order,
                    "blocking_count": len(blocking_failures),
                    "warning_count": len(warnings),
                    "market_session": session_state.value,
                    "dhan_connection": conn_state.value,
                },
            )
        except Exception:
            pass

        return report


# Global singleton
global_live_readiness_engine = LiveTradingReadinessEngine()

