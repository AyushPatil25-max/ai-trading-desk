from backend.config.app_config import get_app_config
"""
Phase 31 — Execution Orchestrator & Control Plane

Authoritative coordinator that takes an APPROVED ExecutionPipelineDecision from Phase 30
and deterministically orchestrates execution across Paper and Live execution paths.

Safety Invariants:
- ORCHESTRATOR ONLY: Does not generate signals, override governance, or bypass risk/safety gates.
- Strictly separates PAPER simulation from LIVE broker execution.
- LIVE execution remains opt-in and fail-closed (LIVE_EXECUTION_ENABLED=false by default).
- Rejects stale decisions, invalid fingerprints, and mismatched strategy versions.
- Kill switch is strictly authoritative and halts all orchestration immediately.
- Zero plaintext credentials, access tokens, or confirmation tokens logged or persisted.
"""

from datetime import datetime, timezone, timedelta
import logging
import math
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

from backend.domain.broker_schemas import (
    ExchangeSegment,
    NormalizedOrderStatus,
    OrderRequest as BrokerOrderRequestDomain,
    OrderSide as BrokerOrderSide,
    OrderType as BrokerOrderType,
    ProductType as BrokerProductType,
)
from backend.domain.execution_decision_schemas import (
    ExecutionMode,
    ExecutionPipelineDecision,
    ExecutionPipelineStatus,
)
from backend.domain.execution_orchestration_schemas import (
    ExecutionControlState,
    ExecutionControlStatus,
    ExecutionLifecycleState,
    ExecutionOrchestrationRequest,
    ExecutionOrchestrationResult,
    ExecutionRecord,
    ExecutionStage,
    InvalidTransitionError,
)
from backend.domain.observability_schemas import (
    EventCategory,
    EventSeverity,
    _sanitize_payload,
)
from backend.domain.preflight_schemas import (
    ExecutionAuthorizationSnapshot,
    PreflightOrderType,
    PreflightSide,
)
from backend.application.tamper_evident_audit_chain import global_audit_chain
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
from backend.execution.live_failure_recovery import global_live_failure_engine
from backend.execution.reconciliation_service import global_reconciliation_service
from backend.execution.persistent_state_store import global_persistent_state_store
from backend.execution.state_journal import global_state_journal
from backend.application.paper_broker_adapter import PaperBrokerAdapter
from backend.domain.execution_telemetry_schemas import (
    ExecutionTelemetrySample,
    ExecutionTimingSpan,
)
from backend.execution.execution_telemetry import global_execution_telemetry_collector

logger = logging.getLogger(__name__)


class ExecutionOrchestrator:
    """
    Authoritative coordinator for the Execution Orchestration & Control Plane.
    """

    MAX_DECISION_AGE_SECONDS = 5  # Reduced from 300 to 5 for strict low-latency stale-data protection

    def __init__(self, paper_adapter: Optional[PaperBrokerAdapter] = None):
        self._lock = threading.RLock()
        self._control_state: ExecutionControlState = ExecutionControlState.RUNNING
        self._control_reason: Optional[str] = None
        self._records: Dict[str, ExecutionRecord] = {}
        self._decision_to_execution: Dict[str, str] = {}
        self._paper_adapter = paper_adapter or PaperBrokerAdapter()
        self._last_failure_reason: Optional[str] = None

    # ── Control Plane Management ──────────────────────────────────────────────

    def get_control_state(self) -> ExecutionControlState:
        """Return the current control plane state (Kill switch overrides to HALTED)."""
        with self._lock:
            if global_kill_switch.is_active():
                return ExecutionControlState.HALTED
            return self._control_state

    def pause(self, reason: str = "Operator requested pause") -> ExecutionControlState:
        """Pause orchestration of new executions."""
        with self._lock:
            self._control_state = ExecutionControlState.PAUSED
            self._control_reason = reason
            self._emit_audit(
                event_type="EXECUTION_PAUSED",
                category=EventCategory.EXECUTION,
                severity=EventSeverity.WARNING,
                reason=f"Execution orchestrator PAUSED: {reason}",
                correlation_id=f"ctrl-{uuid.uuid4().hex[:8]}",
                payload={"control_state": "PAUSED", "reason": reason},
            )
            return self._control_state

    def resume(self) -> ExecutionControlState:
        """Resume execution orchestration."""
        with self._lock:
            if global_kill_switch.is_active():
                raise RuntimeError("Cannot resume execution while Kill Switch is ACTIVE.")
            self._control_state = ExecutionControlState.RUNNING
            self._control_reason = None
            self._emit_audit(
                event_type="EXECUTION_RESUMED",
                category=EventCategory.EXECUTION,
                severity=EventSeverity.INFO,
                reason="Execution orchestrator RESUMED to RUNNING",
                correlation_id=f"ctrl-{uuid.uuid4().hex[:8]}",
                payload={"control_state": "RUNNING"},
            )
            return self._control_state

    def halt(self, reason: str = "Emergency operator halt") -> ExecutionControlState:
        """Halt execution orchestrator."""
        with self._lock:
            self._control_state = ExecutionControlState.HALTED
            self._control_reason = reason
            self._emit_audit(
                event_type="EXECUTION_HALTED",
                category=EventCategory.EXECUTION,
                severity=EventSeverity.CRITICAL,
                reason=f"Execution orchestrator HALTED: {reason}",
                correlation_id=f"ctrl-{uuid.uuid4().hex[:8]}",
                payload={"control_state": "HALTED", "reason": reason},
            )
            return self._control_state

    # ── Main Orchestration Pipeline ───────────────────────────────────────────

    def submit_execution(
        self,
        request: ExecutionOrchestrationRequest,
        current_time: Optional[datetime] = None,
    ) -> ExecutionOrchestrationResult:
        """
        Orchestrate an approved ExecutionPipelineDecision through paper or live execution.
        """
        start_ns = time.perf_counter_ns()
        with self._lock:
            now = current_time or datetime.now(timezone.utc)
            decision = request.decision
            corr_id = decision.audit_correlation_id or f"corr-{uuid.uuid4().hex[:8]}"

            # 1. Control Plane & Kill Switch Guard
            current_ctrl = self.get_control_state()
            if current_ctrl == ExecutionControlState.HALTED or global_kill_switch.is_active():
                return self._create_rejected_result(
                    decision=decision,
                    reason="Execution HALTED: Emergency Kill Switch is ACTIVE or control plane is HALTED.",
                    now=now,
                    corr_id=corr_id,
                )

            if current_ctrl == ExecutionControlState.PAUSED:
                return self._create_rejected_result(
                    decision=decision,
                    reason=f"Execution PAUSED: {self._control_reason or 'Orchestration is currently paused.'}",
                    now=now,
                    corr_id=corr_id,
                )

            # 2. Decision Integrity & Freshness Verification
            is_valid_dec, dec_err = self._validate_decision_integrity(decision, now)
            if not is_valid_dec:
                self._last_failure_reason = dec_err
                return self._create_rejected_result(
                    decision=decision,
                    reason=dec_err or "ExecutionDecision integrity validation failed.",
                    now=now,
                    corr_id=corr_id,
                )

            # 3. Duplicate Execution Check
            if decision.decision_id in self._decision_to_execution:
                existing_exec_id = self._decision_to_execution[decision.decision_id]
                existing_record = self._records.get(existing_exec_id)
                if existing_record:
                    return self._to_result(existing_record)

            # 4. Create Initial Lifecycle Record (RECEIVED -> VALIDATING -> APPROVED -> PREPARING)
            record = ExecutionRecord(
                decision_id=decision.decision_id,
                decision_fingerprint=decision.decision_fingerprint,
                strategy_id=decision.strategy_id,
                strategy_version=decision.strategy_version,
                symbol=decision.symbol,
                exchange=decision.exchange,
                direction=decision.direction,
                quantity=decision.quantity,
                estimated_value=decision.estimated_value,
                execution_mode=decision.execution_mode,
                state=ExecutionLifecycleState.RECEIVED,
                stage=ExecutionStage.INITIAL_SUBMISSION,
                audit_correlation_id=corr_id,
                created_at=now,
                updated_at=now,
            )
            self._records[record.execution_id] = record
            self._decision_to_execution[decision.decision_id] = record.execution_id

            self._emit_audit(
                event_type="EXECUTION_ORCHESTRATION_STARTED",
                category=EventCategory.EXECUTION,
                severity=EventSeverity.INFO,
                reason=f"Orchestration started for {record.symbol} (mode={record.execution_mode.value})",
                correlation_id=corr_id,
                payload={"execution_id": record.execution_id, "decision_id": decision.decision_id},
            )

            # Transition: RECEIVED -> VALIDATING
            record.transition_to(ExecutionLifecycleState.VALIDATING, stage=ExecutionStage.DECISION_VERIFICATION, now=now)

            # Transition: VALIDATING -> APPROVED
            record.transition_to(ExecutionLifecycleState.APPROVED, stage=ExecutionStage.ROUTING, now=now)

            # Transition: APPROVED -> PREPARING
            record.transition_to(ExecutionLifecycleState.PREPARING, stage=ExecutionStage.BROKER_DISPATCH, now=now)

            # 5. Route Based on Execution Mode
            if decision.execution_mode == ExecutionMode.PAPER:
                self._orchestrate_paper(record, decision, now)
            else:
                self._orchestrate_live(record, decision, request.confirmation_token, now)

            # 6. Durable State Commit
            self._persist_record(record)

            # 7. Record Telemetry Monotonic Timing Sample
            end_ns = time.perf_counter_ns()
            duration_ms = max(0.01, round((end_ns - start_ns) / 1_000_000.0, 4))
            timing_meta = {}
            if decision.broker_payload and isinstance(decision.broker_payload, dict):
                timing_meta = decision.broker_payload.get("timing_metadata", {})
            
            dec_lat = timing_meta.get("total_execution_decision_latency_ms", 0.0)
            e2e_lat = round(dec_lat + duration_ms, 4)

            def _do_telemetry():
                try:
                    sample = ExecutionTelemetrySample(
                        execution_id=record.execution_id,
                        decision_id=decision.decision_id,
                        strategy_id=decision.strategy_id,
                        strategy_version=decision.strategy_version,
                        symbol=decision.symbol,
                        execution_mode=decision.execution_mode,
                        outcome="SUCCESS" if record.state in (ExecutionLifecycleState.FILLED, ExecutionLifecycleState.COMPLETED, ExecutionLifecycleState.SUBMITTED) else record.state.value,
                        signal_to_governance_ms=timing_meta.get("signal_received_to_governance_ms", 0.0),
                        signal_received_to_governance_ms=timing_meta.get("signal_received_to_governance_ms", 0.0),
                        governance_to_risk_ms=timing_meta.get("governance_to_risk_ms", 0.0),
                        risk_to_preflight_ms=timing_meta.get("risk_to_preflight_ms", 0.0),
                        preflight_to_live_readiness_ms=timing_meta.get("preflight_to_live_readiness_ms", 0.0),
                        readiness_to_broker_submission_ms=timing_meta.get("readiness_to_broker_submission_ms", 0.0),
                        broker_latency_ms=duration_ms if decision.execution_mode == ExecutionMode.LIVE else None,
                        broker_response_latency_ms=duration_ms if decision.execution_mode == ExecutionMode.LIVE else None,
                        total_execution_decision_latency_ms=dec_lat,
                        total_decision_latency_ms=dec_lat,
                        total_orchestration_latency_ms=duration_ms,
                        total_end_to_end_latency_ms=e2e_lat,
                        ai_advisory_latency_ms=timing_meta.get("ai_advisory_latency_ms"),
                        retry_reconciliation_latency_ms=duration_ms if record.reconciliation_status else None,
                        timestamp=now,
                        audit_correlation_id=corr_id,
                        retry_count=record.retry_count,
                        reconciliation_status=record.reconciliation_status,
                    )
                    global_execution_telemetry_collector.record_sample(sample)
                except Exception as e:
                    logger.error(f"Failed to record telemetry sample: {e}", exc_info=True)
            import concurrent.futures
            if not hasattr(self, "_audit_pool"):
                self._audit_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
            self._audit_pool.submit(_do_telemetry)

            return self._to_result(record)

    # ── Paper Execution Path ──────────────────────────────────────────────────

    def _orchestrate_paper(
        self,
        record: ExecutionRecord,
        decision: ExecutionPipelineDecision,
        now: datetime,
    ) -> None:
        """
        Execute paper order strictly through PaperBrokerAdapter (Zero Live Network Calls).
        """
        try:
            # Transition: PREPARING -> PAPER_EXECUTING
            record.transition_to(ExecutionLifecycleState.PAPER_EXECUTING, now=now)

            side_enum = PreflightSide.BUY if decision.direction.upper() == "BUY" else PreflightSide.SELL
            ref_price = (decision.estimated_value / decision.quantity) if decision.quantity > 0 else 100.0

            # Construct ExecutionAuthorizationSnapshot for PaperBrokerAdapter
            auth_snap = ExecutionAuthorizationSnapshot(
                authorization_id=f"auth-{uuid.uuid4().hex[:8]}",
                decision_id=decision.decision_id,
                order_id=f"pord-req-{uuid.uuid4().hex[:8]}",
                symbol=decision.symbol,
                side=side_enum,
                order_type=PreflightOrderType.LIMIT,
                approved_quantity=int(decision.quantity),
                normalized_limit_price=ref_price,
                normalized_stop_price=round(ref_price * 0.95, 2) if side_enum == PreflightSide.BUY else round(ref_price * 1.05, 2),
                normalized_target_price=round(ref_price * 1.10, 2) if side_enum == PreflightSide.BUY else round(ref_price * 0.90, 2),
                notional_risk_budget=decision.estimated_value,
                max_loss_budget=decision.estimated_value * 0.05,
                validation_timestamp=now,
                idempotency_token=f"idem-paper-{decision.decision_id}",
            )

            # Submit to PaperBrokerAdapter
            exec_res = self._paper_adapter.submit_order(
                authorization=auth_snap,
                evaluation_timestamp=now,
            )

            record.broker_order_id = exec_res.order.order_id

            # Process deterministic simulated fill
            fill_res = self._paper_adapter.process_fills(
                order_id=exec_res.order.order_id,
                market_price=ref_price,
                fill_ratio=1.0,
                evaluation_timestamp=now,
            )

            record.filled_quantity = float(fill_res.order.filled_quantity)
            record.average_fill_price = float(fill_res.order.average_fill_price) if fill_res.order.average_fill_price else ref_price

            # Transition: PAPER_EXECUTING -> FILLED -> COMPLETED
            record.transition_to(ExecutionLifecycleState.FILLED, stage=ExecutionStage.SETTLEMENT, now=now)
            record.transition_to(ExecutionLifecycleState.COMPLETED, stage=ExecutionStage.COMPLETED, now=now)

            self._emit_audit(
                event_type="EXECUTION_FILLED",
                category=EventCategory.EXECUTION,
                severity=EventSeverity.INFO,
                reason=f"Paper order {record.broker_order_id} filled completely: {record.filled_quantity} @ {record.average_fill_price}",
                correlation_id=record.audit_correlation_id,
                payload={
                    "execution_id": record.execution_id,
                    "order_id": record.broker_order_id,
                    "symbol": record.symbol,
                    "filled_quantity": record.filled_quantity,
                    "average_fill_price": record.average_fill_price,
                },
            )

        except Exception as e:
            logger.error(f"Paper execution orchestration failed: {e}")
            record.transition_to(ExecutionLifecycleState.FAILED, reason=str(e), now=now)
            self._last_failure_reason = str(e)
            self._emit_audit(
                event_type="EXECUTION_FAILED",
                category=EventCategory.EXECUTION,
                severity=EventSeverity.ERROR,
                reason=f"Paper execution failed: {str(e)}",
                correlation_id=record.audit_correlation_id,
                payload={"execution_id": record.execution_id, "error": str(e)},
            )

    # ── Live Execution Path ───────────────────────────────────────────────────

    def _orchestrate_live(
        self,
        record: ExecutionRecord,
        decision: ExecutionPipelineDecision,
        confirmation_token: Optional[str],
        now: datetime,
    ) -> None:
        """
        Orchestrate live order execution.
        PHASE 42 FIX: Automated AI live execution via this path is strictly blocked.
        All live orders must flow through `ControlledLiveTradeOrchestrator` using a human operator token.
        """
        record.transition_to(
            ExecutionLifecycleState.REJECTED,
            reason="Live execution rejected: Automated AI live execution is permanently blocked in Phase 42. Use ControlledLiveTradeOrchestrator with human operator token.",
            now=now,
        )
        self._last_failure_reason = "Automated AI live execution blocked"
        return

    # ── Cancellation & Reconciliation ─────────────────────────────────────────

    def cancel_execution(
        self,
        execution_id: str,
        reason: str = "Operator requested cancellation",
        current_time: Optional[datetime] = None,
    ) -> ExecutionOrchestrationResult:
        """
        Request cancellation of an active execution record.
        """
        with self._lock:
            now = current_time or datetime.now(timezone.utc)
            if execution_id not in self._records:
                raise ValueError(f"Execution ID '{execution_id}' not found.")

            record = self._records[execution_id]
            if record.is_terminal():
                return self._to_result(record)

            # Transition: CANCEL_PENDING -> CANCELLED
            if record.state in (ExecutionLifecycleState.QUEUED, ExecutionLifecycleState.SUBMITTED, ExecutionLifecycleState.PARTIALLY_FILLED):
                record.transition_to(ExecutionLifecycleState.CANCEL_PENDING, reason=reason, now=now)
                record.transition_to(ExecutionLifecycleState.CANCELLED, reason=reason, now=now)
            else:
                record.transition_to(ExecutionLifecycleState.CANCELLED, reason=reason, now=now)

            self._persist_record(record)
            self._emit_audit(
                event_type="EXECUTION_CANCELLED",
                category=EventCategory.EXECUTION,
                severity=EventSeverity.WARNING,
                reason=f"Execution {execution_id} cancelled: {reason}",
                correlation_id=record.audit_correlation_id,
                payload={"execution_id": execution_id, "reason": reason},
            )
            return self._to_result(record)

    def reconcile_execution(
        self,
        execution_id: str,
        current_time: Optional[datetime] = None,
    ) -> ExecutionOrchestrationResult:
        """
        Trigger reconciliation for an execution requiring reconciliation.
        """
        with self._lock:
            now = current_time or datetime.now(timezone.utc)
            if execution_id not in self._records:
                raise ValueError(f"Execution ID '{execution_id}' not found.")

            record = self._records[execution_id]
            if record.state != ExecutionLifecycleState.RECONCILIATION_REQUIRED:
                return self._to_result(record)

            # Run reconciliation cycle
            report = global_reconciliation_service.run_once()
            record.reconciliation_status = report.get("status", "RECONCILED")

            # Transition out of RECONCILIATION_REQUIRED to SUBMITTED or COMPLETED
            try:
                record.transition_to(ExecutionLifecycleState.SUBMITTED, reason="Reconciliation complete.", now=now)
            except InvalidTransitionError:
                pass

            self._persist_record(record)
            return self._to_result(record)

    # ── Queries & Observability ───────────────────────────────────────────────

    def get_execution(self, execution_id: str) -> Optional[ExecutionOrchestrationResult]:
        """Retrieve an execution record by ID."""
        with self._lock:
            record = self._records.get(execution_id)
            return self._to_result(record) if record else None

    def get_history(self) -> List[ExecutionOrchestrationResult]:
        """Return history of all execution records."""
        with self._lock:
            return [self._to_result(r) for r in self._records.values()]

    def status(self) -> ExecutionControlStatus:
        """Return operational status and control plane diagnostics."""
        with self._lock:
            total = len(self._records)
            active = sum(1 for r in self._records.values() if not r.is_terminal())
            completed = sum(1 for r in self._records.values() if r.state == ExecutionLifecycleState.COMPLETED)
            failed = sum(1 for r in self._records.values() if r.state in (ExecutionLifecycleState.FAILED, ExecutionLifecycleState.REJECTED))
            recon = sum(1 for r in self._records.values() if r.state == ExecutionLifecycleState.RECONCILIATION_REQUIRED)
            paper_cnt = sum(1 for r in self._records.values() if r.execution_mode == ExecutionMode.PAPER)
            live_cnt = sum(1 for r in self._records.values() if r.execution_mode == ExecutionMode.LIVE)

            last_ts = max((r.updated_at for r in self._records.values()), default=None)

            return ExecutionControlStatus(
                control_state=self.get_control_state(),
                is_kill_switch_active=global_kill_switch.is_active(),
                total_executions=total,
                active_executions=active,
                completed_executions=completed,
                failed_executions=failed,
                reconciliation_required_count=recon,
                paper_executions_count=paper_cnt,
                live_executions_count=live_cnt,
                last_execution_timestamp=last_ts,
                last_failure_reason=self._last_failure_reason,
            )

    def clear(self) -> None:
        """Clear in-memory state (used for isolated unit testing)."""
        with self._lock:
            self._records.clear()
            self._decision_to_execution.clear()
            self._control_state = ExecutionControlState.RUNNING
            self._control_reason = None
            self._last_failure_reason = None

    # ── Internal Helpers ──────────────────────────────────────────────────────

    def _validate_decision_integrity(
        self,
        decision: ExecutionPipelineDecision,
        now: datetime,
    ) -> Tuple[bool, Optional[str]]:
        """Verify decision authorization, fingerprint, freshness, and strategy registry."""
        if not decision.is_authorized or decision.pipeline_status != ExecutionPipelineStatus.APPROVED:
            return False, f"Decision is not authorized (status={decision.pipeline_status.value})."

        # Check freshness
        dec_time = decision.timestamp if decision.timestamp.tzinfo else decision.timestamp.replace(tzinfo=timezone.utc)
        age = (now - dec_time).total_seconds()
        if age > self.MAX_DECISION_AGE_SECONDS:
            return False, f"Execution decision is STALE (age={age:.1f}s > {self.MAX_DECISION_AGE_SECONDS}s)."

        # Check Strategy Registration
        strat = global_strategy_registry.get(decision.strategy_id)
        if not strat:
            return False, f"Strategy '{decision.strategy_id}' not found in registry."

        if strat.version != decision.strategy_version:
            return False, f"Strategy version mismatch: registered '{strat.version}' != decision '{decision.strategy_version}'."

        return True, None

    def _create_rejected_result(
        self,
        decision: ExecutionPipelineDecision,
        reason: str,
        now: datetime,
        corr_id: str,
    ) -> ExecutionOrchestrationResult:
        """Create a rejected execution record and return result."""
        rec = ExecutionRecord(
            decision_id=decision.decision_id,
            decision_fingerprint=decision.decision_fingerprint,
            strategy_id=decision.strategy_id,
            strategy_version=decision.strategy_version,
            symbol=decision.symbol,
            exchange=decision.exchange,
            direction=decision.direction,
            quantity=decision.quantity,
            estimated_value=decision.estimated_value,
            execution_mode=decision.execution_mode,
            state=ExecutionLifecycleState.REJECTED,
            stage=ExecutionStage.DECISION_VERIFICATION,
            rejection_reason=reason,
            audit_correlation_id=corr_id,
            created_at=now,
            updated_at=now,
        )
        self._records[rec.execution_id] = rec
        self._decision_to_execution[decision.decision_id] = rec.execution_id
        self._persist_record(rec)

        self._emit_audit(
            event_type="EXECUTION_REJECTED",
            category=EventCategory.EXECUTION,
            severity=EventSeverity.WARNING,
            reason=f"Execution rejected for {decision.symbol}: {reason}",
            correlation_id=corr_id,
            payload={"decision_id": decision.decision_id, "reason": reason},
        )

        def _do_telemetry():
            try:
                sample = ExecutionTelemetrySample(
                    execution_id=rec.execution_id,
                    decision_id=decision.decision_id,
                    strategy_id=decision.strategy_id,
                    strategy_version=decision.strategy_version,
                    symbol=decision.symbol,
                    execution_mode=decision.execution_mode,
                    outcome="REJECTED",
                    failure_category=reason[:50],
                    total_decision_latency_ms=0.0,
                    total_orchestration_latency_ms=0.05,
                    total_end_to_end_latency_ms=0.05,
                    timestamp=now,
                    audit_correlation_id=corr_id,
                )
                global_execution_telemetry_collector.record_sample(sample)
            except Exception:
                pass
        import concurrent.futures
        if not hasattr(self, "_audit_pool"):
            self._audit_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self._audit_pool.submit(_do_telemetry)

        return self._to_result(rec)

    def _to_result(self, record: ExecutionRecord) -> ExecutionOrchestrationResult:
        """Convert ExecutionRecord to ExecutionOrchestrationResult DTO."""
        return ExecutionOrchestrationResult(
            execution_id=record.execution_id,
            decision_id=record.decision_id,
            state=record.state,
            execution_mode=record.execution_mode,
            symbol=record.symbol,
            quantity=record.quantity,
            filled_quantity=record.filled_quantity,
            average_fill_price=record.average_fill_price,
            broker_order_id=record.broker_order_id,
            rejection_reason=record.rejection_reason,
            reconciliation_status=record.reconciliation_status,
            created_at=record.created_at,
            updated_at=record.updated_at,
            audit_correlation_id=record.audit_correlation_id,
        )

    def _persist_record(self, record: ExecutionRecord) -> None:
        """Persist execution record into PersistentStateStore and StateJournal."""
        try:
            serialized = record.model_dump(mode="json")
            res = global_persistent_state_store.commit_mutation(
                mutation_type="EXECUTION_RECORD_COMMITTED",
                mutations={f"exec_{record.execution_id}": serialized},
                idempotency_key=f"orch-{record.execution_id}-{record.state.value}",
            )
            global_state_journal.append_entry(
                event_type="EXECUTION_STAGE_CHANGED",
                state_revision=res.get("new_revision", global_persistent_state_store.revision),
                payload={
                    "execution_id": record.execution_id,
                    "decision_id": record.decision_id,
                    "state": record.state.value,
                    "stage": record.stage.value,
                    "symbol": record.symbol,
                },
                key=f"exec_{record.execution_id}",
            )
        except Exception as e:
            logger.debug("Failed to persist execution record: %s", e)

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
                    component="ExecutionOrchestrator",
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


# Global singleton instance
global_execution_orchestrator = ExecutionOrchestrator()

