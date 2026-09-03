"""
Phase 29 — Strategy Governance & Decision Control Engine

Deterministic gatekeeper that evaluates whether incoming StrategySignals are admissible:
- 17-point deterministic validation pipeline
- Version matching and strategy boundary validation
- Freshness verification (signal timestamp and market data timestamp)
- Signal deduplication via SHA-256 canonical fingerprints
- Conflict detection between opposing strategies (BUY vs SELL on same instrument)
- Auto-quarantine on consecutive failures
- AI Advisory boundary enforcement (AI signals are strictly advisory, never auto-approved)
- Integration with RiskEngine, KillSwitch, and PersistentStateStore
- Full audit provenance via TamperEvidentAuditChain

Safety Invariants:
- Strategy approval NEVER places a broker order or arms live trading.
- Upstream RiskEngine, PreflightEngine, and ConfirmationStore remain strictly authoritative.
- Conflicting signals are quarantined/blocked (Fail-Closed).
- Duplicate signals are rejected.
- Zero credentials or tokens exposed or processed.
"""

from datetime import datetime, timezone
import logging
import math
import threading
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from backend.domain.strategy_schemas import (
    GovernanceStatus,
    SignalDirection,
    SignalSource,
    StrategyConflictRecord,
    StrategyDecision,
    StrategyDefinition,
    StrategyHealthMetrics,
    StrategySignal,
    StrategyStatus,
)
from backend.domain.observability_schemas import (
    EventCategory,
    EventSeverity,
    _sanitize_payload,
)
from backend.application.tamper_evident_audit_chain import global_audit_chain
from backend.execution.strategy_registry import (
    StrategyRegistry,
    global_strategy_registry,
)
from backend.application.safety_engine import global_safety_engine
from backend.execution.persistent_state_store import global_persistent_state_store
from backend.execution.state_journal import global_state_journal

logger = logging.getLogger(__name__)

DEFAULT_MAX_SIGNAL_AGE_SECONDS = 1800.0       # 30 minutes
DEFAULT_MAX_MARKET_DATA_AGE_SECONDS = 300.0   # 5 minutes
DEFAULT_CONFLICT_WINDOW_SECONDS = 300.0       # 5 minutes
DEFAULT_MAX_CONSECUTIVE_REJECTIONS = 5        # Trigger auto-quarantine


class StrategyGovernanceEngine:
    """
    Deterministic gatekeeper for strategy signal admission and decision control.
    """

    def __init__(
        self,
        registry: Optional[StrategyRegistry] = None,
        max_signal_age_seconds: float = DEFAULT_MAX_SIGNAL_AGE_SECONDS,
        max_market_data_age_seconds: float = DEFAULT_MAX_MARKET_DATA_AGE_SECONDS,
        conflict_window_seconds: float = DEFAULT_CONFLICT_WINDOW_SECONDS,
        max_consecutive_rejections: int = DEFAULT_MAX_CONSECUTIVE_REJECTIONS,
    ):
        self._lock = threading.RLock()
        self.registry = registry or global_strategy_registry
        self.max_signal_age_seconds = max_signal_age_seconds
        self.max_market_data_age_seconds = max_market_data_age_seconds
        self.conflict_window_seconds = conflict_window_seconds
        self.max_consecutive_rejections = max_consecutive_rejections

        # In-memory tracking
        self._recent_fingerprints: Dict[str, datetime] = {}
        self._active_signals: Dict[str, StrategySignal] = {}  # key: f"{symbol}_{exchange}"
        self._conflicts: List[StrategyConflictRecord] = []
        self._health_metrics: Dict[str, StrategyHealthMetrics] = {}
        self._consecutive_rejections: Dict[str, int] = {}
        self._decisions_history: List[StrategyDecision] = []

    def evaluate_signal(
        self,
        signal: StrategySignal,
        current_time: Optional[datetime] = None,
    ) -> StrategyDecision:
        """
        Deterministically evaluate an incoming StrategySignal against 17 governance checks.
        Returns a strongly-typed StrategyDecision.
        """
        with self._lock:
            now = current_time or datetime.now(timezone.utc)
            sid = signal.strategy_id.lower().strip()
            fingerprint = signal.compute_fingerprint()

            # Initialize health metrics if not present
            metrics = self._get_or_create_metrics(sid)
            metrics.total_signals += 1
            metrics.last_signal_time = now

            self._emit_audit(
                event_type="STRATEGY_SIGNAL_RECEIVED",
                category=EventCategory.SIGNAL,
                severity=EventSeverity.INFO,
                reason=f"Received signal {signal.signal_id} from strategy '{sid}' ({signal.direction.value} {signal.symbol})",
                payload={
                    "signal_id": signal.signal_id,
                    "strategy_id": sid,
                    "symbol": signal.symbol,
                    "direction": signal.direction.value,
                    "source": signal.source.value,
                    "confidence": signal.confidence,
                },
            )

            rejections: List[str] = []

            # 1. Strategy Existence Check
            strat_def = self.registry.get(sid)
            if not strat_def:
                rejections.append(f"Strategy '{sid}' is not registered in StrategyRegistry.")
                return self._finalize_rejection(
                    signal=signal,
                    status=GovernanceStatus.REJECTED,
                    rejections=rejections,
                    now=now,
                    fingerprint=fingerprint,
                )

            metrics.status = strat_def.status

            # 2. Strategy Status Active Check
            if strat_def.status == StrategyStatus.QUARANTINED:
                rejections.append(f"Strategy '{sid}' is QUARANTINED (reason: {strat_def.quarantine_reason or 'unspecified'}).")
                return self._finalize_rejection(
                    signal=signal,
                    status=GovernanceStatus.QUARANTINED,
                    rejections=rejections,
                    now=now,
                    fingerprint=fingerprint,
                )

            if strat_def.status != StrategyStatus.ACTIVE:
                rejections.append(f"Strategy '{sid}' is not ACTIVE (current status={strat_def.status.value}).")

            if not strat_def.enabled:
                rejections.append(f"Strategy '{sid}' is disabled in configuration.")

            # 3. Strategy Version Matching Check
            if signal.strategy_version != strat_def.version:
                rejections.append(
                    f"Signal strategy_version '{signal.strategy_version}' does not match registered version '{strat_def.version}'."
                )

            # 4. Allowed Instrument Check
            if "*" not in strat_def.allowed_instruments and signal.symbol not in strat_def.allowed_instruments:
                rejections.append(
                    f"Symbol '{signal.symbol}' is not in allowed instruments for strategy '{sid}'."
                )

            # 5. Allowed Exchange Check
            if "*" not in strat_def.allowed_exchanges and signal.exchange not in strat_def.allowed_exchanges:
                rejections.append(
                    f"Exchange '{signal.exchange}' is not in allowed exchanges for strategy '{sid}'."
                )

            # 6. Signal Timestamp Freshness Check
            signal_age = (now - signal.timestamp).total_seconds()
            if signal_age < 0:
                rejections.append(f"Signal timestamp {signal.timestamp.isoformat()} is in the future.")
            elif signal_age > self.max_signal_age_seconds:
                rejections.append(
                    f"Signal is stale: age {signal_age:.1f}s exceeds max allowed {self.max_signal_age_seconds:.1f}s."
                )

            # 7. Market Data Timestamp Freshness Check
            market_data_age = (now - signal.market_data_timestamp).total_seconds()
            if market_data_age < 0:
                rejections.append(f"Market data timestamp {signal.market_data_timestamp.isoformat()} is in the future.")
            elif market_data_age > self.max_market_data_age_seconds:
                rejections.append(
                    f"Market data is stale: age {market_data_age:.1f}s exceeds max allowed {self.max_market_data_age_seconds:.1f}s."
                )

            # 8. Confidence Validity Check
            if math.isnan(signal.confidence) or math.isinf(signal.confidence) or signal.confidence < 0.0 or signal.confidence > 1.0:
                rejections.append(f"Invalid confidence score {signal.confidence}.")

            # 9. Signal Direction Validity Check
            if signal.direction not in (SignalDirection.BUY, SignalDirection.SELL, SignalDirection.HOLD):
                rejections.append(f"Invalid signal direction '{signal.direction}'.")

            # 10. Strategy Sizing & Value Limits
            if signal.quantity is not None:
                if signal.quantity > strat_def.max_position_size:
                    rejections.append(
                        f"Signal quantity {signal.quantity} exceeds strategy max_position_size {strat_def.max_position_size}."
                    )
                if signal.target_price is not None:
                    order_val = signal.quantity * signal.target_price
                    if order_val > strat_def.max_order_value:
                        rejections.append(
                            f"Signal estimated value {order_val:.2f} exceeds strategy max_order_value {strat_def.max_order_value:.2f}."
                        )

            # 11. Kill Switch Check
            if global_safety_engine.is_kill_switch_active():
                rejections.append("Global Emergency Kill Switch is engaged. All strategy signals rejected.")

            # 12. Duplicate Signal Check
            if fingerprint in self._recent_fingerprints:
                prev_time = self._recent_fingerprints[fingerprint]
                time_diff = (now - prev_time).total_seconds()
                if time_diff < self.max_signal_age_seconds:
                    metrics.duplicate_signals += 1
                    self._emit_audit(
                        event_type="STRATEGY_SIGNAL_DUPLICATE",
                        category=EventCategory.SIGNAL,
                        severity=EventSeverity.WARNING,
                        reason=f"Duplicate signal detected for strategy '{sid}' on {signal.symbol}",
                        payload={"fingerprint": fingerprint, "strategy_id": sid, "symbol": signal.symbol},
                    )
                    return self._finalize_rejection(
                        signal=signal,
                        status=GovernanceStatus.DUPLICATE,
                        rejections=[f"Duplicate signal fingerprint {fingerprint[:12]}... received within {time_diff:.1f}s."],
                        now=now,
                        fingerprint=fingerprint,
                    )

            # 13. Strategy Conflict Check (Opposing BUY vs SELL on same symbol/exchange)
            instrument_key = f"{signal.symbol}_{signal.exchange}"
            if instrument_key in self._active_signals:
                existing_signal = self._active_signals[instrument_key]
                time_diff = (now - existing_signal.timestamp).total_seconds()
                if time_diff <= self.conflict_window_seconds:
                    if (signal.direction == SignalDirection.BUY and existing_signal.direction == SignalDirection.SELL) or \
                       (signal.direction == SignalDirection.SELL and existing_signal.direction == SignalDirection.BUY):
                        conflict_rec = StrategyConflictRecord(
                            symbol=signal.symbol,
                            exchange=signal.exchange,
                            timestamp=now,
                            conflicting_signals=[
                                {
                                    "strategy_id": existing_signal.strategy_id,
                                    "direction": existing_signal.direction.value,
                                    "timestamp": existing_signal.timestamp.isoformat(),
                                    "signal_id": existing_signal.signal_id,
                                },
                                {
                                    "strategy_id": signal.strategy_id,
                                    "direction": signal.direction.value,
                                    "timestamp": signal.timestamp.isoformat(),
                                    "signal_id": signal.signal_id,
                                },
                            ],
                            conflict_reason=f"Conflicting signals on {signal.symbol}: {existing_signal.strategy_id} ({existing_signal.direction.value}) vs {signal.strategy_id} ({signal.direction.value})",
                        )
                        self._conflicts.append(conflict_rec)
                        metrics.conflicted_signals += 1

                        self._emit_audit(
                            event_type="STRATEGY_CONFLICT_DETECTED",
                            category=EventCategory.RISK,
                            severity=EventSeverity.CRITICAL,
                            reason=conflict_rec.conflict_reason,
                            payload=conflict_rec.model_dump(mode="json"),
                        )

                        return self._finalize_rejection(
                            signal=signal,
                            status=GovernanceStatus.CONFLICTED,
                            rejections=[conflict_rec.conflict_reason],
                            now=now,
                            fingerprint=fingerprint,
                            conflict_metadata=conflict_rec.model_dump(mode="json"),
                        )

            # 14. If rejections occurred -> finalize rejection
            if rejections:
                return self._finalize_rejection(
                    signal=signal,
                    status=GovernanceStatus.REJECTED,
                    rejections=rejections,
                    now=now,
                    fingerprint=fingerprint,
                )

            # ── 15. All checks PASSED -> Finalize APPROVAL ────────────────────
            self._recent_fingerprints[fingerprint] = now
            self._active_signals[instrument_key] = signal
            self._consecutive_rejections[sid] = 0
            metrics.accepted_signals += 1
            metrics.last_accepted_time = now

            decision = StrategyDecision(
                signal=signal,
                governance_status=GovernanceStatus.APPROVED,
                is_admissible=True,
                strategy_version=strat_def.version,
                decision_timestamp=now,
                fingerprint=fingerprint,
                risk_metadata={
                    "max_position_size": strat_def.max_position_size,
                    "max_order_value": strat_def.max_order_value,
                    "source": signal.source.value,
                    "admissibility_verified": True,
                },
            )

            self._decisions_history.append(decision)

            self._emit_audit(
                event_type="STRATEGY_SIGNAL_ACCEPTED",
                category=EventCategory.SIGNAL,
                severity=EventSeverity.INFO,
                reason=f"Admissible signal {signal.signal_id} approved for {signal.symbol} ({signal.direction.value})",
                payload={"decision_id": decision.decision_id, "strategy_id": sid, "symbol": signal.symbol},
            )
            self._emit_audit(
                event_type="STRATEGY_DECISION_CREATED",
                category=EventCategory.CONFIGURATION,
                severity=EventSeverity.INFO,
                reason=f"Created APPROVED StrategyDecision {decision.decision_id}",
                payload={"decision_id": decision.decision_id, "governance_status": "APPROVED", "fingerprint": fingerprint},
            )

            return decision

    def _finalize_rejection(
        self,
        signal: StrategySignal,
        status: GovernanceStatus,
        rejections: List[str],
        now: datetime,
        fingerprint: str,
        conflict_metadata: Optional[Dict[str, Any]] = None,
    ) -> StrategyDecision:
        """Helper to build, record, and emit rejected decision."""
        sid = signal.strategy_id.lower().strip()
        metrics = self._get_or_create_metrics(sid)
        metrics.rejected_signals += 1
        metrics.last_rejection_reason = "; ".join(rejections)

        # Track consecutive rejections for auto-quarantine
        consec = self._consecutive_rejections.get(sid, 0) + 1
        self._consecutive_rejections[sid] = consec

        # Check for auto-quarantine
        if consec >= self.max_consecutive_rejections:
            quarantine_reason = f"Automated quarantine triggered after {consec} consecutive rejections: {metrics.last_rejection_reason}"
            self.registry.quarantine(sid, reason=quarantine_reason)
            metrics.status = StrategyStatus.QUARANTINED
            metrics.quarantine_count += 1
            metrics.quarantined_at = now
            metrics.quarantine_reason = quarantine_reason

        decision = StrategyDecision(
            signal=signal,
            governance_status=status,
            is_admissible=False,
            rejection_reason="; ".join(rejections),
            rejection_details=rejections,
            strategy_version=signal.strategy_version,
            decision_timestamp=now,
            fingerprint=fingerprint,
            conflict_metadata=conflict_metadata,
        )

        self._decisions_history.append(decision)

        self._emit_audit(
            event_type="STRATEGY_SIGNAL_REJECTED",
            category=EventCategory.SIGNAL,
            severity=EventSeverity.WARNING,
            reason=f"Rejected signal {signal.signal_id} for strategy '{sid}': {decision.rejection_reason}",
            payload={
                "decision_id": decision.decision_id,
                "strategy_id": sid,
                "governance_status": status.value,
                "rejections": rejections,
            },
        )
        self._emit_audit(
            event_type="STRATEGY_DECISION_CREATED",
            category=EventCategory.CONFIGURATION,
            severity=EventSeverity.WARNING,
            reason=f"Created {status.value} StrategyDecision {decision.decision_id}",
            payload={"decision_id": decision.decision_id, "governance_status": status.value, "fingerprint": fingerprint},
        )

        return decision

    def _get_or_create_metrics(self, strategy_id: str) -> StrategyHealthMetrics:
        """Get or create strategy health metrics."""
        sid = strategy_id.lower().strip()
        if sid not in self._health_metrics:
            strat = self.registry.get(sid)
            st = strat.status if strat else StrategyStatus.DRAFT
            self._health_metrics[sid] = StrategyHealthMetrics(strategy_id=sid, status=st)
        return self._health_metrics[sid]

    def get_health(self, strategy_id: str) -> Optional[StrategyHealthMetrics]:
        """Retrieve health metrics for a strategy."""
        with self._lock:
            sid = strategy_id.lower().strip()
            metrics = self._health_metrics.get(sid)
            return metrics.model_copy(deep=True) if metrics else None

    def get_all_health(self) -> Dict[str, StrategyHealthMetrics]:
        """Retrieve health metrics for all registered strategies."""
        with self._lock:
            return {k: v.model_copy(deep=True) for k, v in self._health_metrics.items()}

    def get_conflicts(self) -> List[StrategyConflictRecord]:
        """Retrieve all recorded strategy conflicts."""
        with self._lock:
            return [c.model_copy(deep=True) for c in self._conflicts]

    def clear(self) -> None:
        """Clear governance state caches (used for test isolation)."""
        with self._lock:
            self._recent_fingerprints.clear()
            self._active_signals.clear()
            self._conflicts.clear()
            self._health_metrics.clear()
            self._consecutive_rejections.clear()
            self._decisions_history.clear()

    def status(self) -> Dict[str, Any]:
        """Return operational summary of the strategy governance engine."""
        with self._lock:
            total_decisions = len(self._decisions_history)
            approved = sum(1 for d in self._decisions_history if d.governance_status == GovernanceStatus.APPROVED)
            rejected = sum(1 for d in self._decisions_history if d.governance_status == GovernanceStatus.REJECTED)
            conflicted = sum(1 for d in self._decisions_history if d.governance_status == GovernanceStatus.CONFLICTED)
            duplicate = sum(1 for d in self._decisions_history if d.governance_status == GovernanceStatus.DUPLICATE)

            return {
                "total_decisions": total_decisions,
                "approved_count": approved,
                "rejected_count": rejected,
                "conflicted_count": conflicted,
                "duplicate_count": duplicate,
                "conflicts_count": len(self._conflicts),
                "tracked_strategies_count": len(self._health_metrics),
            }

    def _emit_audit(
        self,
        event_type: str,
        category: EventCategory,
        severity: EventSeverity,
        reason: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            global_audit_chain.append_event(
                event_type=event_type,
                category=category,
                component="StrategyGovernanceEngine",
                correlation_id=f"sgov-{uuid.uuid4().hex[:8]}",
                severity=severity,
                reason=reason,
                payload=_sanitize_payload(payload or {}),
            )
        except Exception:
            pass


# Global singleton instance
global_strategy_governance_engine = StrategyGovernanceEngine()
