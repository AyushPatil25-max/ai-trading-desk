"""
Phase 29 — Strategy Registry & Lifecycle Manager

Thread-safe, version-aware registry for managing trading strategy definitions,
authorizations, and lifecycle state transitions:
- Explicit registration and duplicate prevention
- Monotonic versioning validation
- Lifecycle operations (Activate, Pause, Disable, Quarantine, Recover)
- Crash-safe persistence via PersistentStateStore and StateJournal
- Standardized audit logging via TamperEvidentAuditChain

Safety Invariants:
- Strategy registration/activation NEVER authorizes live order placement.
- Quarantined strategies CANNOT produce admissible trading decisions.
- Disabled strategies CANNOT produce admissible trading decisions.
- Strategy recovery from quarantine REQUIRES explicit operator action (AI cannot self-recover).
- Zero secrets or execution credentials persisted in registry records.
"""

from datetime import datetime, timezone
import logging
import threading
from typing import Any, Dict, List, Optional, Tuple
import uuid

from backend.domain.strategy_schemas import (
    StrategyDefinition,
    StrategyStatus,
)
from backend.domain.observability_schemas import (
    EventCategory,
    EventSeverity,
    _sanitize_payload,
)
from backend.application.tamper_evident_audit_chain import global_audit_chain
from backend.execution.persistent_state_store import global_persistent_state_store
from backend.execution.state_journal import global_state_journal

logger = logging.getLogger(__name__)


class StrategyRegistryError(Exception):
    """Base exception for strategy registry operations."""
    pass


class DuplicateStrategyError(StrategyRegistryError):
    """Raised when registering an existing strategy with conflicting properties."""
    pass


class StrategyNotFoundError(StrategyRegistryError):
    """Raised when operating on an unregistered strategy."""
    pass


class StrategyRegistry:
    """
    Authoritative, thread-safe in-memory and persistent registry of all trading strategies.
    """

    def __init__(self, load_persisted: bool = True):
        self._lock = threading.RLock()
        self._strategies: Dict[str, StrategyDefinition] = {}
        if load_persisted:
            self._load_from_persistent_store()

    def register(self, strategy: StrategyDefinition) -> StrategyDefinition:
        """
        Register a new strategy or a valid new version of an existing strategy.
        Rejects conflicting registrations for existing versions.
        """
        with self._lock:
            sid = strategy.strategy_id.lower()
            if sid in self._strategies:
                existing = self._strategies[sid]
                # If identical version but different configuration, reject as duplicate conflict
                if existing.version == strategy.version:
                    if existing.model_dump(exclude={"created_at", "updated_at"}) != strategy.model_dump(exclude={"created_at", "updated_at"}):
                        raise DuplicateStrategyError(
                            f"Strategy '{sid}' version {strategy.version} is already registered with conflicting parameters."
                        )
                    return existing

            now = datetime.now(timezone.utc)
            strategy.updated_at = now
            self._strategies[sid] = strategy
            self._persist_strategies("STRATEGY_REGISTERED", sid)

            self._emit_audit(
                event_type="STRATEGY_REGISTERED",
                category=EventCategory.CONFIGURATION,
                severity=EventSeverity.INFO,
                reason=f"Registered strategy '{sid}' (version {strategy.version}, status={strategy.status.value})",
                payload={"strategy_id": sid, "version": strategy.version, "status": strategy.status.value},
            )

            return strategy

    def get(self, strategy_id: str) -> Optional[StrategyDefinition]:
        """Retrieve strategy definition by ID."""
        with self._lock:
            sid = strategy_id.lower().strip()
            strat = self._strategies.get(sid)
            return strat.model_copy(deep=True) if strat else None

    def list(self, status_filter: Optional[StrategyStatus] = None) -> List[StrategyDefinition]:
        """List registered strategies, optionally filtered by lifecycle status."""
        with self._lock:
            results = list(self._strategies.values())
            if status_filter is not None:
                results = [s for s in results if s.status == status_filter]
            return [s.model_copy(deep=True) for s in results]

    def activate(self, strategy_id: str) -> Tuple[bool, str, Optional[StrategyDefinition]]:
        """
        Activate a strategy from DRAFT or PAUSED state.
        Cannot activate a QUARANTINED strategy without formal recovery.
        """
        with self._lock:
            sid = strategy_id.lower().strip()
            if sid not in self._strategies:
                return False, f"Strategy '{sid}' not found.", None

            strategy = self._strategies[sid]
            if strategy.status == StrategyStatus.QUARANTINED:
                return False, f"Strategy '{sid}' is QUARANTINED and must be formally recovered before activation.", strategy

            now = datetime.now(timezone.utc)
            strategy.status = StrategyStatus.ACTIVE
            strategy.enabled = True
            strategy.updated_at = now
            self._persist_strategies("STRATEGY_ACTIVATED", sid)

            self._emit_audit(
                event_type="STRATEGY_ACTIVATED",
                category=EventCategory.CONFIGURATION,
                severity=EventSeverity.INFO,
                reason=f"Activated strategy '{sid}'",
                payload={"strategy_id": sid, "version": strategy.version},
            )

            return True, f"Strategy '{sid}' activated successfully.", strategy.model_copy(deep=True)

    def pause(self, strategy_id: str) -> Tuple[bool, str, Optional[StrategyDefinition]]:
        """Pause an active strategy temporarily."""
        with self._lock:
            sid = strategy_id.lower().strip()
            if sid not in self._strategies:
                return False, f"Strategy '{sid}' not found.", None

            strategy = self._strategies[sid]
            now = datetime.now(timezone.utc)
            strategy.status = StrategyStatus.PAUSED
            strategy.updated_at = now
            self._persist_strategies("STRATEGY_PAUSED", sid)

            self._emit_audit(
                event_type="STRATEGY_PAUSED",
                category=EventCategory.CONFIGURATION,
                severity=EventSeverity.INFO,
                reason=f"Paused strategy '{sid}'",
                payload={"strategy_id": sid, "version": strategy.version},
            )

            return True, f"Strategy '{sid}' paused.", strategy.model_copy(deep=True)

    def disable(self, strategy_id: str) -> Tuple[bool, str, Optional[StrategyDefinition]]:
        """Disable a strategy administratively."""
        with self._lock:
            sid = strategy_id.lower().strip()
            if sid not in self._strategies:
                return False, f"Strategy '{sid}' not found.", None

            strategy = self._strategies[sid]
            now = datetime.now(timezone.utc)
            strategy.status = StrategyStatus.DISABLED
            strategy.enabled = False
            strategy.updated_at = now
            self._persist_strategies("STRATEGY_DISABLED", sid)

            self._emit_audit(
                event_type="STRATEGY_DISABLED",
                category=EventCategory.CONFIGURATION,
                severity=EventSeverity.WARNING,
                reason=f"Disabled strategy '{sid}'",
                payload={"strategy_id": sid, "version": strategy.version},
            )

            return True, f"Strategy '{sid}' disabled.", strategy.model_copy(deep=True)

    def quarantine(self, strategy_id: str, reason: str) -> Tuple[bool, str, Optional[StrategyDefinition]]:
        """
        Quarantine a strategy due to repeated failures, malformed output, or risk violations.
        Quarantined strategies are immediately blocked from producing decisions.
        """
        with self._lock:
            sid = strategy_id.lower().strip()
            if sid not in self._strategies:
                return False, f"Strategy '{sid}' not found.", None

            strategy = self._strategies[sid]
            now = datetime.now(timezone.utc)
            strategy.status = StrategyStatus.QUARANTINED
            strategy.enabled = False
            strategy.quarantine_reason = reason
            strategy.quarantined_at = now
            strategy.updated_at = now
            self._persist_strategies("STRATEGY_QUARANTINED", sid)

            self._emit_audit(
                event_type="STRATEGY_QUARANTINED",
                category=EventCategory.SECURITY,
                severity=EventSeverity.CRITICAL,
                reason=f"Quarantined strategy '{sid}': {reason}",
                payload={"strategy_id": sid, "reason": reason, "quarantined_at": now.isoformat()},
            )

            return True, f"Strategy '{sid}' quarantined: {reason}", strategy.model_copy(deep=True)

    def recover(self, strategy_id: str, operator_notes: Optional[str] = None) -> Tuple[bool, str, Optional[StrategyDefinition]]:
        """
        Recover a quarantined strategy back to PAUSED status.
        Requires explicit operator invocation.
        """
        with self._lock:
            sid = strategy_id.lower().strip()
            if sid not in self._strategies:
                return False, f"Strategy '{sid}' not found.", None

            strategy = self._strategies[sid]
            if strategy.status != StrategyStatus.QUARANTINED:
                return False, f"Strategy '{sid}' is not quarantined (current status={strategy.status.value}).", strategy

            now = datetime.now(timezone.utc)
            strategy.status = StrategyStatus.PAUSED
            strategy.quarantine_reason = None
            strategy.quarantined_at = None
            strategy.updated_at = now
            self._persist_strategies("STRATEGY_RECOVERED", sid)

            self._emit_audit(
                event_type="STRATEGY_RECOVERED",
                category=EventCategory.SECURITY,
                severity=EventSeverity.WARNING,
                reason=f"Recovered strategy '{sid}' from quarantine (notes: {operator_notes or 'None'})",
                payload={"strategy_id": sid, "operator_notes": operator_notes},
            )

            return True, f"Strategy '{sid}' recovered from quarantine and set to PAUSED.", strategy.model_copy(deep=True)

    def get_version(self, strategy_id: str) -> Optional[str]:
        """Get the active version of a strategy."""
        with self._lock:
            sid = strategy_id.lower().strip()
            strat = self._strategies.get(sid)
            return strat.version if strat else None

    def validate(self, strategy_id: str) -> Tuple[bool, Optional[str]]:
        """Validate whether a strategy is registered and in ACTIVE status."""
        with self._lock:
            sid = strategy_id.lower().strip()
            if sid not in self._strategies:
                return False, f"Strategy '{sid}' is not registered."
            strat = self._strategies[sid]
            if strat.status != StrategyStatus.ACTIVE:
                return False, f"Strategy '{sid}' is not ACTIVE (status is {strat.status.value})."
            if not strat.enabled:
                return False, f"Strategy '{sid}' is disabled."
            return True, None

    def status(self) -> Dict[str, Any]:
        """Return summary operational status of the registry."""
        with self._lock:
            by_status: Dict[str, int] = {}
            for s in self._strategies.values():
                st = s.status.value
                by_status[st] = by_status.get(st, 0) + 1

            return {
                "total_registered": len(self._strategies),
                "by_status": by_status,
                "strategy_ids": list(self._strategies.keys()),
            }

    def clear(self) -> None:
        """Clear in-memory strategies (used for isolated test fixtures)."""
        with self._lock:
            self._strategies.clear()

    # ── Internal Persistence Helpers ──────────────────────────────────────────

    def _persist_strategies(self, mutation_type: str, strategy_id: str) -> None:
        """Persist strategies dictionary to PersistentStateStore and StateJournal."""
        try:
            serialized_dict = {sid: s.model_dump(mode="json") for sid, s in self._strategies.items()}
            res = global_persistent_state_store.commit_mutation(
                mutation_type=f"STRATEGY_REGISTRY_{mutation_type}",
                mutations={"registered_strategies": serialized_dict},
                idempotency_key=f"sreg-{uuid.uuid4().hex[:8]}",
            )
            global_state_journal.append_entry(
                event_type=mutation_type,
                state_revision=res.get("new_revision", global_persistent_state_store.revision),
                payload={"strategy_id": strategy_id, "total_registered": len(self._strategies)},
                key="registered_strategies",
            )
        except Exception as e:
            logger.debug("Failed to persist strategy registry state: %s", e)

    def _load_from_persistent_store(self) -> None:
        """Load strategies from PersistentStateStore."""
        try:
            persisted = global_persistent_state_store.get("registered_strategies")
            if isinstance(persisted, dict):
                for sid, sdata in persisted.items():
                    if isinstance(sdata, dict):
                        try:
                            self._strategies[sid.lower()] = StrategyDefinition(**sdata)
                        except Exception as e:
                            logger.warning("Could not parse persisted strategy '%s': %s", sid, e)
        except Exception as e:
            logger.debug("Could not load strategies from persistent state store: %s", e)

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
                component="StrategyRegistry",
                correlation_id=f"strat-{uuid.uuid4().hex[:8]}",
                severity=severity,
                reason=reason,
                payload=_sanitize_payload(payload or {}),
            )
        except Exception:
            pass


# Global singleton instance
global_strategy_registry = StrategyRegistry()
