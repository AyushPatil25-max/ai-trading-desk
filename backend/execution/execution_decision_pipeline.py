"""
Phase 30 — Authoritative Execution Decision Pipeline Engine

Coordinates the complete, multi-stage deterministic execution authorization pipeline:
Strategy Signal -> Strategy Governance -> Risk Engine -> Execution Preflight
-> Live Readiness -> Live Arming -> Manual Order Safety Gate -> Confirmation Token
-> Duplicate / Idempotency Check -> Final Authorization -> Broker Routing.

Safety Invariants:
- Strategy approval is ADVISORY ONLY and does not authorize execution.
- AI_ADVISORY signals must pass all deterministic gates identically to rule-based signals.
- Injected AI flags ("approved=True", "is_safe=True", "bypass=True") are strictly ignored.
- Rejection at ANY stage halts the pipeline immediately (Fail-Closed).
- Paper execution is strictly isolated from Live execution.
- Live execution requires unexpired Arming (5m TTL), Kill Switch inactive, Safety Gate approval, and single-use Confirmation Token.
- LIVE_EXECUTION_ENABLED=false remains strictly enforced.
"""

from datetime import datetime, timezone
import logging
import math
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

from backend.domain.broker_schemas import (
    ExchangeSegment,
    OrderRequest as BrokerOrderRequestDomain,
    OrderSide as BrokerOrderSide,
    OrderType as BrokerOrderType,
    ProductType as BrokerProductType,
)
from backend.domain.execution_decision_schemas import (
    ExecutionMode,
    ExecutionPipelineDecision,
    ExecutionPipelineRequest,
    ExecutionPipelineStatus,
    GateExecutionResult,
    PipelineGateName,
)
from backend.domain.strategy_schemas import (
    GovernanceStatus,
    SignalDirection,
    SignalSource,
    StrategyDecision,
    StrategySignal,
)
from backend.domain.observability_schemas import (
    EventCategory,
    EventSeverity,
    _sanitize_payload,
)
from backend.application.tamper_evident_audit_chain import global_audit_chain
from backend.execution.strategy_governance import global_strategy_governance_engine
from backend.execution.strategy_registry import global_strategy_registry
from backend.execution.safety_engine import (
    global_kill_switch,
    global_manual_order_safety_gate,
)
from backend.execution.live_readiness import global_live_readiness_engine
from backend.execution.live_arming_store import global_live_arming_store
from backend.application.confirmation_store import (
    compute_order_fingerprint,
    global_confirmation_store,
)
from backend.execution.order_tracker import global_order_tracker
from backend.execution.persistent_state_store import global_persistent_state_store
from backend.execution.state_journal import global_state_journal

from backend.execution.execution_telemetry import global_execution_telemetry_collector

logger = logging.getLogger(__name__)


class ExecutionDecisionEngine:
    """
    Authoritative coordinator for the 10-stage Execution Decision Pipeline.
    """

    MAX_SIGNAL_AGE_SECONDS = 5.0
    MAX_MARKET_DATA_AGE_SECONDS = 15.0
    MAX_AI_ADVISORY_AGE_SECONDS = 5.0

    def __init__(self):
        self._lock = threading.RLock()
        self._decisions_history: List[ExecutionPipelineDecision] = []

    def evaluate_pipeline(
        self,
        request: ExecutionPipelineRequest,
        current_time: Optional[datetime] = None,
    ) -> ExecutionPipelineDecision:
        """
        Evaluate the complete execution pipeline in strict deterministic order.
        Returns an authoritative ExecutionPipelineDecision.
        """
        t_start = time.perf_counter_ns()
        with self._lock:
            now = current_time or datetime.now(timezone.utc)
            corr_id = f"exec-corr-{uuid.uuid4().hex[:8]}"
            gate_results: List[GateExecutionResult] = []

            # 1. Emit Decision Started Audit Event
            self._emit_audit(
                event_type="EXECUTION_DECISION_STARTED",
                category=EventCategory.EXECUTION,
                severity=EventSeverity.INFO,
                reason=f"Initiated execution pipeline for {request.symbol} ({request.direction}, mode={request.execution_mode.value})",
                correlation_id=corr_id,
                payload={
                    "strategy_id": request.strategy_id,
                    "symbol": request.symbol,
                    "quantity": request.quantity,
                    "mode": request.execution_mode.value,
                },
            )

            # ── Gate 1: SIGNAL_VALIDATION ─────────────────────────────────────
            sig_valid, sig_err, signal_obj = self._evaluate_gate_signal_validation(request, now)
            t_sig = time.perf_counter_ns()
            gate_results.append(GateExecutionResult(
                gate_name=PipelineGateName.SIGNAL_VALIDATION,
                passed=sig_valid,
                status="PASSED" if sig_valid else "FAILED",
                reason=sig_err,
                evaluated_at=now,
                details={"duration_ms": max(0.0001, round((t_sig - t_start) / 1_000_000.0, 4))},
            ))
            if not sig_valid or signal_obj is None:
                t_end = time.perf_counter_ns()
                timing_meta = {
                    "signal_received_to_governance_ms": max(0.0001, round((t_sig - t_start) / 1_000_000.0, 4)),
                    "total_execution_decision_latency_ms": max(0.0001, round((t_end - t_start) / 1_000_000.0, 4)),
                }
                return self._finalize_blocked(
                    request=request,
                    status=ExecutionPipelineStatus.REJECTED,
                    blocking_gate=PipelineGateName.SIGNAL_VALIDATION,
                    reason=sig_err or "Signal validation failed.",
                    gate_results=gate_results,
                    now=now,
                    corr_id=corr_id,
                    timing_metadata=timing_meta,
                )

            signal_fingerprint = signal_obj.compute_fingerprint()
            ref_price = request.target_price or 100.0
            estimated_val = request.quantity * ref_price

            # ── Gate 2: STRATEGY_GOVERNANCE ───────────────────────────────────
            gov_decision: StrategyDecision = global_strategy_governance_engine.evaluate_signal(
                signal=signal_obj,
                current_time=now,
            )
            t_gov = time.perf_counter_ns()
            gov_passed = (gov_decision.governance_status == GovernanceStatus.APPROVED)
            gate_results.append(GateExecutionResult(
                gate_name=PipelineGateName.STRATEGY_GOVERNANCE,
                passed=gov_passed,
                status=gov_decision.governance_status.value,
                reason=gov_decision.rejection_reason,
                evaluated_at=now,
                details={
                    "decision_id": gov_decision.decision_id,
                    "duration_ms": max(0.0001, round((t_gov - t_sig) / 1_000_000.0, 4)),
                },
            ))

            if not gov_passed:
                t_end = time.perf_counter_ns()
                timing_meta = {
                    "signal_received_to_governance_ms": max(0.0001, round((t_gov - t_sig) / 1_000_000.0, 4)),
                    "total_execution_decision_latency_ms": max(0.0001, round((t_end - t_start) / 1_000_000.0, 4)),
                }
                # Map governance status to pipeline status
                pipeline_status = ExecutionPipelineStatus.REJECTED
                if gov_decision.governance_status == GovernanceStatus.CONFLICTED:
                    pipeline_status = ExecutionPipelineStatus.CONFLICTED
                elif gov_decision.governance_status == GovernanceStatus.QUARANTINED:
                    pipeline_status = ExecutionPipelineStatus.BLOCKED
                elif gov_decision.governance_status == GovernanceStatus.DUPLICATE:
                    pipeline_status = ExecutionPipelineStatus.BLOCKED

                return self._finalize_blocked(
                    request=request,
                    status=pipeline_status,
                    blocking_gate=PipelineGateName.STRATEGY_GOVERNANCE,
                    reason=gov_decision.rejection_reason or f"Governance status is {gov_decision.governance_status.value}",
                    gate_results=gate_results,
                    now=now,
                    corr_id=corr_id,
                    signal_fingerprint=signal_fingerprint,
                    governance_status=gov_decision.governance_status.value,
                    timing_metadata=timing_meta,
                )

            self._emit_audit(
                event_type="EXECUTION_GOVERNANCE_APPROVED",
                category=EventCategory.EXECUTION,
                severity=EventSeverity.INFO,
                reason=f"Governance approved signal for {request.symbol}",
                correlation_id=corr_id,
                payload={"strategy_id": request.strategy_id, "symbol": request.symbol},
            )

            # ── Gate 3: RISK_ENGINE ───────────────────────────────────────────
            risk_valid, risk_err, risk_details = self._evaluate_gate_risk_engine(request, estimated_val)
            t_risk = time.perf_counter_ns()
            gate_results.append(GateExecutionResult(
                gate_name=PipelineGateName.RISK_ENGINE,
                passed=risk_valid,
                status="PASSED" if risk_valid else "FAILED",
                reason=risk_err,
                evaluated_at=now,
                details={**risk_details, "duration_ms": max(0.0001, round((t_risk - t_gov) / 1_000_000.0, 4))},
            ))
            if not risk_valid:
                t_end = time.perf_counter_ns()
                timing_meta = {
                    "signal_received_to_governance_ms": max(0.0001, round((t_gov - t_sig) / 1_000_000.0, 4)),
                    "governance_to_risk_ms": max(0.0001, round((t_risk - t_gov) / 1_000_000.0, 4)),
                    "total_execution_decision_latency_ms": max(0.0001, round((t_end - t_start) / 1_000_000.0, 4)),
                }
                return self._finalize_blocked(
                    request=request,
                    status=ExecutionPipelineStatus.REJECTED,
                    blocking_gate=PipelineGateName.RISK_ENGINE,
                    reason=risk_err or "Risk checks failed.",
                    gate_results=gate_results,
                    now=now,
                    corr_id=corr_id,
                    signal_fingerprint=signal_fingerprint,
                    governance_status=gov_decision.governance_status.value,
                    risk_decision="REJECTED",
                    timing_metadata=timing_meta,
                )

            self._emit_audit(
                event_type="EXECUTION_RISK_APPROVED",
                category=EventCategory.RISK,
                severity=EventSeverity.INFO,
                reason=f"Risk engine approved sizing for {request.symbol}",
                correlation_id=corr_id,
                payload={"symbol": request.symbol, "estimated_value": estimated_val},
            )

            # ── Gate 4: EXECUTION_PREFLIGHT ───────────────────────────────────
            preflight_valid, preflight_err, preflight_details = self._evaluate_gate_preflight(request)
            t_preflight = time.perf_counter_ns()
            gate_results.append(GateExecutionResult(
                gate_name=PipelineGateName.EXECUTION_PREFLIGHT,
                passed=preflight_valid,
                status="PASSED" if preflight_valid else "FAILED",
                reason=preflight_err,
                evaluated_at=now,
                details={**preflight_details, "duration_ms": max(0.0001, round((t_preflight - t_risk) / 1_000_000.0, 4))},
            ))
            if not preflight_valid:
                t_end = time.perf_counter_ns()
                timing_meta = {
                    "signal_received_to_governance_ms": max(0.0001, round((t_gov - t_sig) / 1_000_000.0, 4)),
                    "governance_to_risk_ms": max(0.0001, round((t_risk - t_gov) / 1_000_000.0, 4)),
                    "risk_to_preflight_ms": max(0.0001, round((t_preflight - t_risk) / 1_000_000.0, 4)),
                    "total_execution_decision_latency_ms": max(0.0001, round((t_end - t_start) / 1_000_000.0, 4)),
                }
                return self._finalize_blocked(
                    request=request,
                    status=ExecutionPipelineStatus.REJECTED,
                    blocking_gate=PipelineGateName.EXECUTION_PREFLIGHT,
                    reason=preflight_err or "Preflight validation failed.",
                    gate_results=gate_results,
                    now=now,
                    corr_id=corr_id,
                    signal_fingerprint=signal_fingerprint,
                    governance_status=gov_decision.governance_status.value,
                    risk_decision="APPROVED",
                    preflight_decision="REJECTED",
                    timing_metadata=timing_meta,
                )

            self._emit_audit(
                event_type="EXECUTION_PREFLIGHT_APPROVED",
                category=EventCategory.EXECUTION,
                severity=EventSeverity.INFO,
                reason=f"Execution preflight approved order parameters for {request.symbol}",
                correlation_id=corr_id,
                payload={"symbol": request.symbol},
            )

            # ── Branch: PAPER vs LIVE Execution Path ─────────────────────────
            if request.execution_mode == ExecutionMode.PAPER:
                t_end = time.perf_counter_ns()
                timing_meta = {
                    "signal_received_to_governance_ms": max(0.0001, round((t_gov - t_sig) / 1_000_000.0, 4)),
                    "governance_to_risk_ms": max(0.0001, round((t_risk - t_gov) / 1_000_000.0, 4)),
                    "risk_to_preflight_ms": max(0.0001, round((t_preflight - t_risk) / 1_000_000.0, 4)),
                    "total_execution_decision_latency_ms": max(0.0001, round((t_end - t_start) / 1_000_000.0, 4)),
                    "ai_advisory_latency_ms": float(request.metadata.get("ai_latency_ms", 0.0)) if request.metadata.get("ai_latency_ms") is not None else None,
                }
                # In PAPER mode, downstream live readiness/arming/dhan safety gates are bypassed
                # Final authorization for Paper Broker Simulator
                return self._finalize_approved(
                    request=request,
                    gate_results=gate_results,
                    now=now,
                    corr_id=corr_id,
                    signal_fingerprint=signal_fingerprint,
                    estimated_val=estimated_val,
                    governance_status="APPROVED",
                    risk_decision="APPROVED",
                    preflight_decision="APPROVED",
                    timing_metadata=timing_meta,
                )

            # ── LIVE EXECUTION GATES (Strict Multi-Stage Fail-Closed) ─────────

            # Gate 5: LIVE_READINESS
            readiness_report = global_live_readiness_engine.evaluate_readiness(check_time=now)
            t_readiness = time.perf_counter_ns()
            readiness_passed = readiness_report.is_ready_for_order
            gate_results.append(GateExecutionResult(
                gate_name=PipelineGateName.LIVE_READINESS,
                passed=readiness_passed,
                status=readiness_report.overall_status.value,
                reason="; ".join(readiness_report.blocking_failures) if not readiness_passed else None,
                evaluated_at=now,
                details={
                    "blocking_failures": readiness_report.blocking_failures,
                    "duration_ms": max(0.0001, round((t_readiness - t_preflight) / 1_000_000.0, 4)),
                },
            ))
            if not readiness_passed:
                t_end = time.perf_counter_ns()
                timing_meta = {
                    "signal_received_to_governance_ms": max(0.0001, round((t_gov - t_sig) / 1_000_000.0, 4)),
                    "governance_to_risk_ms": max(0.0001, round((t_risk - t_gov) / 1_000_000.0, 4)),
                    "risk_to_preflight_ms": max(0.0001, round((t_preflight - t_risk) / 1_000_000.0, 4)),
                    "preflight_to_live_readiness_ms": max(0.0001, round((t_readiness - t_preflight) / 1_000_000.0, 4)),
                    "total_execution_decision_latency_ms": max(0.0001, round((t_end - t_start) / 1_000_000.0, 4)),
                }
                return self._finalize_blocked(
                    request=request,
                    status=ExecutionPipelineStatus.NOT_READY,
                    blocking_gate=PipelineGateName.LIVE_READINESS,
                    reason=f"Live trading readiness check failed: {'; '.join(readiness_report.blocking_failures)}",
                    gate_results=gate_results,
                    now=now,
                    corr_id=corr_id,
                    signal_fingerprint=signal_fingerprint,
                    governance_status="APPROVED",
                    risk_decision="APPROVED",
                    preflight_decision="APPROVED",
                    readiness_decision=readiness_report.overall_status.value,
                    timing_metadata=timing_meta,
                )

            # Gate 6: LIVE_ARMING
            arming_status = global_live_arming_store.get_status()
            t_arming = time.perf_counter_ns()
            arming_passed = arming_status.is_armed
            gate_results.append(GateExecutionResult(
                gate_name=PipelineGateName.LIVE_ARMING,
                passed=arming_passed,
                status="ARMED" if arming_passed else "DISARMED",
                reason=None if arming_passed else "Live trading is DISARMED. Explicit operator arming session required.",
                evaluated_at=now,
                details={
                    "remaining_seconds": arming_status.remaining_seconds,
                    "duration_ms": max(0.0001, round((t_arming - t_readiness) / 1_000_000.0, 4)),
                },
            ))
            if not arming_passed:
                t_end = time.perf_counter_ns()
                timing_meta = {
                    "signal_received_to_governance_ms": max(0.0001, round((t_gov - t_sig) / 1_000_000.0, 4)),
                    "governance_to_risk_ms": max(0.0001, round((t_risk - t_gov) / 1_000_000.0, 4)),
                    "risk_to_preflight_ms": max(0.0001, round((t_preflight - t_risk) / 1_000_000.0, 4)),
                    "preflight_to_live_readiness_ms": max(0.0001, round((t_readiness - t_preflight) / 1_000_000.0, 4)),
                    "total_execution_decision_latency_ms": max(0.0001, round((t_end - t_start) / 1_000_000.0, 4)),
                }
                return self._finalize_blocked(
                    request=request,
                    status=ExecutionPipelineStatus.BLOCKED,
                    blocking_gate=PipelineGateName.LIVE_ARMING,
                    reason="Live execution blocked: live trading session is not armed.",
                    gate_results=gate_results,
                    now=now,
                    corr_id=corr_id,
                    signal_fingerprint=signal_fingerprint,
                    governance_status="APPROVED",
                    risk_decision="APPROVED",
                    preflight_decision="APPROVED",
                    readiness_decision="READY",
                    arming_status="DISARMED",
                    timing_metadata=timing_meta,
                )

            # Build Domain OrderRequest for downstream safety & confirmation checks
            side_enum = BrokerOrderSide.BUY if request.direction.upper() == "BUY" else BrokerOrderSide.SELL
            broker_order = BrokerOrderRequestDomain(
                symbol=request.symbol,
                side=side_enum,
                quantity=int(request.quantity),
                order_type=BrokerOrderType.LIMIT if request.target_price else BrokerOrderType.MARKET,
                price=float(request.target_price) if request.target_price else None,
                trigger_price=float(request.stop_loss_price) if request.stop_loss_price else None,
                exchange_segment=ExchangeSegment.NSE if request.exchange.upper() == "NSE" else ExchangeSegment.BSE,
                product_type=BrokerProductType.CNC,
                request_id=f"live-req-{uuid.uuid4().hex[:8]}",
            )
            order_fingerprint = compute_order_fingerprint(broker_order)

            # Gate 7: MANUAL_SAFETY_GATE
            safety_res = global_manual_order_safety_gate.evaluate_order(
                order=broker_order,
                target_broker="Dhan",
                require_live_enabled=True,
                reference_price=ref_price,
                data_timestamp=now,
            )
            t_safety = time.perf_counter_ns()
            safety_passed = safety_res.is_approved
            gate_results.append(GateExecutionResult(
                gate_name=PipelineGateName.MANUAL_SAFETY_GATE,
                passed=safety_passed,
                status="APPROVED" if safety_passed else "REJECTED",
                reason=safety_res.reason if not safety_passed else None,
                evaluated_at=now,
                details={
                    "reason_code": safety_res.reason_code.value,
                    "duration_ms": max(0.0001, round((t_safety - t_arming) / 1_000_000.0, 4)),
                },
            ))
            if not safety_passed:
                t_end = time.perf_counter_ns()
                timing_meta = {
                    "signal_received_to_governance_ms": max(0.0001, round((t_gov - t_sig) / 1_000_000.0, 4)),
                    "governance_to_risk_ms": max(0.0001, round((t_risk - t_gov) / 1_000_000.0, 4)),
                    "risk_to_preflight_ms": max(0.0001, round((t_preflight - t_risk) / 1_000_000.0, 4)),
                    "preflight_to_live_readiness_ms": max(0.0001, round((t_readiness - t_preflight) / 1_000_000.0, 4)),
                    "total_execution_decision_latency_ms": max(0.0001, round((t_end - t_start) / 1_000_000.0, 4)),
                }
                return self._finalize_blocked(
                    request=request,
                    status=ExecutionPipelineStatus.BLOCKED,
                    blocking_gate=PipelineGateName.MANUAL_SAFETY_GATE,
                    reason=f"Manual order safety gate rejection: {safety_res.reason}",
                    gate_results=gate_results,
                    now=now,
                    corr_id=corr_id,
                    signal_fingerprint=signal_fingerprint,
                    governance_status="APPROVED",
                    risk_decision="APPROVED",
                    preflight_decision="APPROVED",
                    readiness_decision="READY",
                    arming_status="ARMED",
                    safety_decision=safety_res.reason_code.value,
                    timing_metadata=timing_meta,
                )

            # Gate 8: DUPLICATE_CHECK
            is_dup = global_order_tracker.is_duplicate(order_fingerprint)
            t_dup = time.perf_counter_ns()
            if is_dup:
                global_execution_telemetry_collector.record_duplicate_rejection()
            gate_results.append(GateExecutionResult(
                gate_name=PipelineGateName.DUPLICATE_CHECK,
                passed=not is_dup,
                status="UNIQUE" if not is_dup else "DUPLICATE_DETECTED",
                reason="Duplicate order fingerprint detected in order tracker." if is_dup else None,
                evaluated_at=now,
                details={"duration_ms": max(0.0001, round((t_dup - t_safety) / 1_000_000.0, 4))},
            ))
            if is_dup:
                t_end = time.perf_counter_ns()
                timing_meta = {
                    "signal_received_to_governance_ms": max(0.0001, round((t_gov - t_sig) / 1_000_000.0, 4)),
                    "governance_to_risk_ms": max(0.0001, round((t_risk - t_gov) / 1_000_000.0, 4)),
                    "risk_to_preflight_ms": max(0.0001, round((t_preflight - t_risk) / 1_000_000.0, 4)),
                    "preflight_to_live_readiness_ms": max(0.0001, round((t_readiness - t_preflight) / 1_000_000.0, 4)),
                    "total_execution_decision_latency_ms": max(0.0001, round((t_end - t_start) / 1_000_000.0, 4)),
                }
                return self._finalize_blocked(
                    request=request,
                    status=ExecutionPipelineStatus.BLOCKED,
                    blocking_gate=PipelineGateName.DUPLICATE_CHECK,
                    reason="Duplicate active order already exists in order tracker.",
                    gate_results=gate_results,
                    now=now,
                    corr_id=corr_id,
                    signal_fingerprint=signal_fingerprint,
                    governance_status="APPROVED",
                    risk_decision="APPROVED",
                    preflight_decision="APPROVED",
                    readiness_decision="READY",
                    arming_status="ARMED",
                    safety_decision="APPROVED",
                    duplicate_status="DUPLICATE_DETECTED",
                    timing_metadata=timing_meta,
                )

            # Gate 9: CONFIRMATION_CHECK
            if not request.confirmation_token:
                conf_passed = False
                conf_reason = "Confirmation token is mandatory for live execution."
            else:
                conf_passed, conf_reason, _ = global_confirmation_store.verify_and_consume(
                    token=request.confirmation_token,
                    order_fingerprint=order_fingerprint,
                )
            t_conf = time.perf_counter_ns()

            gate_results.append(GateExecutionResult(
                gate_name=PipelineGateName.CONFIRMATION_CHECK,
                passed=conf_passed,
                status="CONFIRMED" if conf_passed else "UNCONFIRMED",
                reason=conf_reason if not conf_passed else None,
                evaluated_at=now,
                details={"duration_ms": max(0.0001, round((t_conf - t_dup) / 1_000_000.0, 4))},
            ))
            if not conf_passed:
                t_end = time.perf_counter_ns()
                timing_meta = {
                    "signal_received_to_governance_ms": max(0.0001, round((t_gov - t_sig) / 1_000_000.0, 4)),
                    "governance_to_risk_ms": max(0.0001, round((t_risk - t_gov) / 1_000_000.0, 4)),
                    "risk_to_preflight_ms": max(0.0001, round((t_preflight - t_risk) / 1_000_000.0, 4)),
                    "preflight_to_live_readiness_ms": max(0.0001, round((t_readiness - t_preflight) / 1_000_000.0, 4)),
                    "total_execution_decision_latency_ms": max(0.0001, round((t_end - t_start) / 1_000_000.0, 4)),
                }
                return self._finalize_blocked(
                    request=request,
                    status=ExecutionPipelineStatus.BLOCKED,
                    blocking_gate=PipelineGateName.CONFIRMATION_CHECK,
                    reason=f"Confirmation verification failed: {conf_reason}",
                    gate_results=gate_results,
                    now=now,
                    corr_id=corr_id,
                    signal_fingerprint=signal_fingerprint,
                    governance_status="APPROVED",
                    risk_decision="APPROVED",
                    preflight_decision="APPROVED",
                    readiness_decision="READY",
                    arming_status="ARMED",
                    safety_decision="APPROVED",
                    duplicate_status="UNIQUE",
                    confirmation_status="FAILED",
                    timing_metadata=timing_meta,
                )

            # ── Gate 10: FINAL_AUTHORIZATION (LIVE) ───────────────────────────
            t_end = time.perf_counter_ns()
            timing_meta = {
                "signal_received_to_governance_ms": max(0.0001, round((t_gov - t_sig) / 1_000_000.0, 4)),
                "governance_to_risk_ms": max(0.0001, round((t_risk - t_gov) / 1_000_000.0, 4)),
                "risk_to_preflight_ms": max(0.0001, round((t_preflight - t_risk) / 1_000_000.0, 4)),
                "preflight_to_live_readiness_ms": max(0.0001, round((t_readiness - t_preflight) / 1_000_000.0, 4)),
                "readiness_to_broker_submission_ms": max(0.0001, round((t_end - t_readiness) / 1_000_000.0, 4)),
                "total_execution_decision_latency_ms": max(0.0001, round((t_end - t_start) / 1_000_000.0, 4)),
                "ai_advisory_latency_ms": float(request.metadata.get("ai_latency_ms", 0.0)) if request.metadata.get("ai_latency_ms") is not None else None,
            }

            return self._finalize_approved(
                request=request,
                gate_results=gate_results,
                now=now,
                corr_id=corr_id,
                signal_fingerprint=signal_fingerprint,
                estimated_val=estimated_val,
                governance_status="APPROVED",
                risk_decision="APPROVED",
                preflight_decision="APPROVED",
                readiness_decision="READY",
                arming_status="ARMED",
                safety_decision="APPROVED",
                duplicate_status="UNIQUE",
                confirmation_status="CONFIRMED",
                broker_payload={"symbol": request.symbol, "quantity": request.quantity, "mode": "LIVE", "timing_metadata": timing_meta},
                timing_metadata=timing_meta,
            )

    # ── Internal Gate Evaluators ──────────────────────────────────────────────

    def _evaluate_gate_signal_validation(
        self,
        req: ExecutionPipelineRequest,
        now: datetime,
    ) -> Tuple[bool, Optional[str], Optional[StrategySignal]]:
        """Validate signal format, quantity, confidence, timestamps, and staleness."""
        try:
            dir_enum = SignalDirection[req.direction.upper()]
        except KeyError:
            return False, f"Invalid direction '{req.direction}'. Must be BUY, SELL, or HOLD.", None

        if req.quantity <= 0 or math.isnan(req.quantity) or math.isinf(req.quantity):
            return False, "Quantity must be a positive finite number.", None

        # 1. Signal Timestamp Validation & Staleness
        sig_ts = req.timestamp or now
        if sig_ts.tzinfo is None:
            sig_ts = sig_ts.replace(tzinfo=timezone.utc)
        now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)

        # Future timestamp / clock skew check (> 1.0s in future)
        future_delta = (sig_ts - now_utc).total_seconds()
        if future_delta > 1.0:
            return False, f"Signal timestamp is in the FUTURE (skew={future_delta:.2f}s > 1.0s). Clock error detected.", None

        # Signal staleness check
        sig_age = (now_utc - sig_ts).total_seconds()
        if sig_age > self.MAX_SIGNAL_AGE_SECONDS:
            global_execution_telemetry_collector.record_stale_rejection()
            return False, f"Signal is STALE (age={sig_age:.2f}s > {self.MAX_SIGNAL_AGE_SECONDS}s).", None

        # 2. Market Data Timestamp Validation & Staleness
        if req.market_data_timestamp is not None:
            mkt_ts = req.market_data_timestamp
            if mkt_ts.tzinfo is None:
                mkt_ts = mkt_ts.replace(tzinfo=timezone.utc)
            mkt_future = (mkt_ts - now_utc).total_seconds()
            if mkt_future > 1.0:
                return False, f"Market data timestamp is in the FUTURE (skew={mkt_future:.2f}s > 1.0s). Clock error detected.", None
            mkt_age = (now_utc - mkt_ts).total_seconds()
            if mkt_age > self.MAX_MARKET_DATA_AGE_SECONDS:
                global_execution_telemetry_collector.record_stale_rejection()
                return False, f"Market data is STALE (age={mkt_age:.2f}s > {self.MAX_MARKET_DATA_AGE_SECONDS}s).", None

        # 3. AI Advisory Specific Safety & Staleness Checks
        is_ai_advisory = (req.source.upper() == "AI_ADVISORY" or req.metadata.get("is_ai_advisory") is True)
        if is_ai_advisory:
            # Check AI failure / timeout status
            if req.metadata.get("ai_timeout") is True or req.metadata.get("ai_status") in ("TIMEOUT", "FAILED", "DEGRADED_UNAVAILABLE"):
                return False, "AI advisory service failed or timed out: fail-closed safety invariant enforced.", None

            # Check AI timestamp staleness if provided in metadata
            if req.metadata.get("ai_timestamp") is not None:
                ai_ts_raw = req.metadata["ai_timestamp"]
                try:
                    if isinstance(ai_ts_raw, str):
                        ai_ts = datetime.fromisoformat(ai_ts_raw.replace("Z", "+00:00"))
                    elif isinstance(ai_ts_raw, datetime):
                        ai_ts = ai_ts_raw
                    else:
                        ai_ts = sig_ts
                    if ai_ts.tzinfo is None:
                        ai_ts = ai_ts.replace(tzinfo=timezone.utc)
                    ai_age = (now_utc - ai_ts).total_seconds()
                    if ai_age > self.MAX_AI_ADVISORY_AGE_SECONDS:
                        global_execution_telemetry_collector.record_stale_rejection()
                        return False, f"AI advisory output is STALE (age={ai_age:.2f}s > {self.MAX_AI_ADVISORY_AGE_SECONDS}s).", None
                except Exception:
                    pass

            # Check for invalid/corrupted latency metadata
            if "ai_latency_ms" in req.metadata:
                try:
                    ai_lat = float(req.metadata["ai_latency_ms"])
                    if ai_lat < 0.0 or math.isnan(ai_lat) or math.isinf(ai_lat):
                        return False, "Invalid AI advisory latency: must be non-negative finite number.", None
                except (ValueError, TypeError):
                    return False, "Invalid AI advisory latency format.", None

        # Build StrategySignal
        try:
            sig = StrategySignal(
                strategy_id=req.strategy_id,
                strategy_version=req.strategy_version,
                symbol=req.symbol,
                exchange=req.exchange,
                direction=dir_enum,
                confidence=0.85,
                quantity=req.quantity,
                target_price=req.target_price,
                stop_loss_price=req.stop_loss_price,
                source=SignalSource.AI_ADVISORY if is_ai_advisory else SignalSource.RULE_BASED,
                timestamp=sig_ts,
                market_data_timestamp=req.market_data_timestamp or sig_ts,
                metadata=req.metadata,
            )
            return True, None, sig
        except Exception as e:
            return False, f"Signal construction failed: {str(e)}", None

    def _evaluate_gate_risk_engine(
        self,
        req: ExecutionPipelineRequest,
        estimated_val: float,
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """Evaluate strategy definition limits and capital boundaries."""
        strat = global_strategy_registry.get(req.strategy_id)
        if not strat:
            return False, f"Strategy '{req.strategy_id}' not found.", {}

        if req.quantity > strat.max_position_size:
            return False, f"Quantity {req.quantity} exceeds strategy max_position_size {strat.max_position_size}.", {}

        if estimated_val > strat.max_order_value:
            return False, f"Estimated value ₹{estimated_val:,.2f} exceeds strategy max_order_value ₹{strat.max_order_value:,.2f}.", {}

        if global_kill_switch.is_active():
            return False, "Emergency Kill Switch is ACTIVE. All trading blocked.", {}

        return True, None, {"max_position_size": strat.max_position_size, "max_order_value": strat.max_order_value}

    def _evaluate_gate_preflight(
        self,
        req: ExecutionPipelineRequest,
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """Validate exchange constraints and instrument parameters."""
        exch = req.exchange.upper().strip()
        if exch not in ("NSE", "BSE", "MCX"):
            return False, f"Unsupported exchange '{exch}'.", {}

        sym = req.symbol.upper().strip()
        if not sym or len(sym) < 2:
            return False, "Invalid instrument symbol.", {}

        return True, None, {"symbol": sym, "exchange": exch}

    # ── Internal Finalization & Persistence ───────────────────────────────────

    def _finalize_blocked(
        self,
        request: ExecutionPipelineRequest,
        status: ExecutionPipelineStatus,
        blocking_gate: PipelineGateName,
        reason: str,
        gate_results: List[GateExecutionResult],
        now: datetime,
        corr_id: str,
        signal_fingerprint: str = "",
        governance_status: Optional[str] = None,
        risk_decision: Optional[str] = None,
        preflight_decision: Optional[str] = None,
        readiness_decision: Optional[str] = None,
        arming_status: Optional[str] = None,
        safety_decision: Optional[str] = None,
        duplicate_status: Optional[str] = None,
        confirmation_status: Optional[str] = None,
        timing_metadata: Optional[Dict[str, Any]] = None,
    ) -> ExecutionPipelineDecision:
        """Create a blocked/rejected execution decision and record audit events."""
        decision = ExecutionPipelineDecision(
            execution_mode=request.execution_mode,
            pipeline_status=status,
            is_authorized=False,
            strategy_id=request.strategy_id,
            strategy_version=request.strategy_version,
            signal_fingerprint=signal_fingerprint or f"fp-{uuid.uuid4().hex[:8]}",
            symbol=request.symbol,
            exchange=request.exchange,
            direction=request.direction,
            quantity=request.quantity,
            estimated_value=(request.quantity * (request.target_price or 100.0)),
            governance_status=governance_status,
            risk_decision=risk_decision,
            preflight_decision=preflight_decision,
            readiness_decision=readiness_decision,
            arming_status=arming_status,
            safety_decision=safety_decision,
            confirmation_status=confirmation_status,
            duplicate_status=duplicate_status,
            gate_results=gate_results,
            rejection_reason=reason,
            rejection_details=[reason],
            blocking_gate=blocking_gate,
            broker_payload={"mode": request.execution_mode.value, "timing_metadata": timing_metadata or {}},
            audit_correlation_id=corr_id,
            timestamp=now,
        )

        self._decisions_history.append(decision)
        self._persist_decision(decision)

        self._emit_audit(
            event_type="EXECUTION_BLOCKED",
            category=EventCategory.EXECUTION,
            severity=EventSeverity.WARNING,
            reason=f"Execution blocked at {blocking_gate.value}: {reason}",
            correlation_id=corr_id,
            payload={
                "decision_id": decision.decision_id,
                "blocking_gate": blocking_gate.value,
                "status": status.value,
                "reason": reason,
            },
        )

        return decision

    def _finalize_approved(
        self,
        request: ExecutionPipelineRequest,
        gate_results: List[GateExecutionResult],
        now: datetime,
        corr_id: str,
        signal_fingerprint: str,
        estimated_val: float,
        governance_status: str,
        risk_decision: str,
        preflight_decision: str,
        readiness_decision: Optional[str] = None,
        arming_status: Optional[str] = None,
        safety_decision: Optional[str] = None,
        duplicate_status: Optional[str] = None,
        confirmation_status: Optional[str] = None,
        broker_payload: Optional[Dict[str, Any]] = None,
        timing_metadata: Optional[Dict[str, Any]] = None,
    ) -> ExecutionPipelineDecision:
        """Create an approved execution decision and record audit events."""
        final_payload = dict(broker_payload or {"mode": request.execution_mode.value})
        if timing_metadata:
            final_payload["timing_metadata"] = timing_metadata

        decision = ExecutionPipelineDecision(
            execution_mode=request.execution_mode,
            pipeline_status=ExecutionPipelineStatus.APPROVED,
            is_authorized=True,
            strategy_id=request.strategy_id,
            strategy_version=request.strategy_version,
            signal_fingerprint=signal_fingerprint,
            symbol=request.symbol,
            exchange=request.exchange,
            direction=request.direction,
            quantity=request.quantity,
            estimated_value=estimated_val,
            governance_status=governance_status,
            risk_decision=risk_decision,
            preflight_decision=preflight_decision,
            readiness_decision=readiness_decision,
            arming_status=arming_status,
            safety_decision=safety_decision,
            confirmation_status=confirmation_status,
            duplicate_status=duplicate_status,
            gate_results=gate_results,
            rejection_reason=None,
            rejection_details=[],
            blocking_gate=None,
            broker_payload=final_payload,
            audit_correlation_id=corr_id,
            timestamp=now,
        )

        self._decisions_history.append(decision)
        self._persist_decision(decision)

        self._emit_audit(
            event_type="EXECUTION_AUTHORIZED",
            category=EventCategory.EXECUTION,
            severity=EventSeverity.INFO,
            reason=f"Execution AUTHORIZED for {request.symbol} in {request.execution_mode.value} mode",
            correlation_id=corr_id,
            payload={
                "decision_id": decision.decision_id,
                "symbol": request.symbol,
                "quantity": request.quantity,
                "mode": request.execution_mode.value,
            },
        )

        return decision

    def _persist_decision(self, decision: ExecutionPipelineDecision) -> None:
        """Persist decision record to PersistentStateStore and StateJournal."""
        try:
            serialized = decision.model_dump(mode="json")
            res = global_persistent_state_store.commit_mutation(
                mutation_type="EXECUTION_DECISION_RECORDED",
                mutations={f"last_decision_{decision.symbol}": serialized},
                idempotency_key=f"dec-{decision.decision_id}",
            )
            global_state_journal.append_entry(
                event_type="EXECUTION_DECISION_RECORDED",
                state_revision=res.get("new_revision", global_persistent_state_store.revision),
                payload={
                    "decision_id": decision.decision_id,
                    "symbol": decision.symbol,
                    "status": decision.pipeline_status.value,
                    "is_authorized": decision.is_authorized,
                },
                key=f"last_decision_{decision.symbol}",
            )
        except Exception as e:
            logger.debug("Failed to persist execution decision: %s", e)

    def _emit_audit(
        self,
        event_type: str,
        category: EventCategory,
        severity: EventSeverity,
        reason: str,
        correlation_id: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        def _do_audit():
            try:
                global_audit_chain.append_event(
                    event_type=event_type,
                    category=category,
                    component="ExecutionDecisionEngine",
                    correlation_id=correlation_id,
                    severity=severity,
                    reason=reason,
                    payload=_sanitize_payload(payload or {}),
                )
            except Exception:
                pass
        import concurrent.futures
        if not hasattr(self, "_audit_pool"):
            self._audit_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self._audit_pool.submit(_do_audit)

    def get_decision_history(self) -> List[ExecutionPipelineDecision]:
        """Return a copy of all evaluated execution decisions."""
        with self._lock:
            return [d.model_copy(deep=True) for d in self._decisions_history]

    def clear(self) -> None:
        """Clear in-memory decision history (used for test isolation)."""
        with self._lock:
            self._decisions_history.clear()

    def status(self) -> Dict[str, Any]:
        """Return operational summary of the execution decision engine."""
        with self._lock:
            total = len(self._decisions_history)
            approved = sum(1 for d in self._decisions_history if d.pipeline_status == ExecutionPipelineStatus.APPROVED)
            blocked = sum(1 for d in self._decisions_history if d.pipeline_status in (ExecutionPipelineStatus.BLOCKED, ExecutionPipelineStatus.REJECTED))
            conflicted = sum(1 for d in self._decisions_history if d.pipeline_status == ExecutionPipelineStatus.CONFLICTED)
            return {
                "total_decisions_evaluated": total,
                "approved_count": approved,
                "blocked_count": blocked,
                "conflicted_count": conflicted,
            }


# Global singleton instance
global_execution_decision_engine = ExecutionDecisionEngine()
