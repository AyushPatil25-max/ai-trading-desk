"""
Phase 23 — Decision Explainability Engine

Synthesizes structured, auditable decision explainability records from actual Trading OS
engine states (factors, debate, committee, conviction, risk assessment, position sizing).

Safety Invariant:
- Zero hallucinated explanations: strictly constructed from structured engine state.
- Strictly observational: ZERO authority to execute orders or mutate risk limits.
- TIER_4_LIVE_REAL_MONEY remains permanently locked and fail-closed.
"""

from datetime import datetime, timezone
import logging
import threading
from typing import Any, Dict, List, Optional

from backend.domain.observability_schemas import (
    DecisionExplainabilityRecord,
    _sanitize_payload,
)

logger = logging.getLogger(__name__)


class DecisionExplainabilityEngine:
    """
    Structured repository for decision explainability records.
    Allows post-hoc inspection of why any simulation or paper trading decision was made.
    """

    def __init__(self, max_records: int = 5_000):
        self._lock = threading.RLock()
        self._max_records = max_records
        self._records_by_id: Dict[str, DecisionExplainabilityRecord] = {}
        self._records_by_correlation: Dict[str, DecisionExplainabilityRecord] = {}
        self._records_by_symbol: Dict[str, List[str]] = {}

    def record_decision(
        self,
        correlation_id: str,
        symbol: str,
        decision_type: str,
        final_decision: str,
        decision_reason: str,
        direction: str = "NEUTRAL",
        conviction: float = 0.0,
        run_id: Optional[str] = None,
        factor_scores: Optional[Dict[str, float]] = None,
        risk_constraints: Optional[Dict[str, Any]] = None,
        position_sizing_inputs: Optional[Dict[str, Any]] = None,
        stop_loss_inputs: Optional[Dict[str, Any]] = None,
        conviction_inputs: Optional[Dict[str, Any]] = None,
        rejected_constraints: Optional[List[str]] = None,
        snapshot_reference: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DecisionExplainabilityRecord:
        """
        Record a structured explainability record for a paper/simulation decision.
        """
        with self._lock:
            record = DecisionExplainabilityRecord(
                correlation_id=correlation_id,
                run_id=run_id,
                symbol=symbol,
                decision_type=decision_type,
                direction=direction,
                conviction=conviction,
                factor_scores=factor_scores or {},
                risk_constraints=_sanitize_payload(risk_constraints or {}),
                position_sizing_inputs=_sanitize_payload(position_sizing_inputs or {}),
                stop_loss_inputs=_sanitize_payload(stop_loss_inputs or {}),
                conviction_inputs=_sanitize_payload(conviction_inputs or {}),
                rejected_constraints=rejected_constraints or [],
                final_decision=final_decision,
                decision_reason=decision_reason,
                snapshot_reference=snapshot_reference,
                metadata=_sanitize_payload(metadata or {}),
            )

            # Enforce max capacity bounds
            if len(self._records_by_id) >= self._max_records:
                oldest_id = next(iter(self._records_by_id))
                oldest_rec = self._records_by_id.pop(oldest_id)
                self._records_by_correlation.pop(oldest_rec.correlation_id, None)

            self._records_by_id[record.decision_id] = record
            self._records_by_correlation[correlation_id] = record
            self._records_by_symbol.setdefault(symbol, []).append(record.decision_id)

            return record

    def get_by_correlation_id(self, correlation_id: str) -> Optional[DecisionExplainabilityRecord]:
        with self._lock:
            rec = self._records_by_correlation.get(correlation_id)
            return rec.model_copy() if rec else None

    def get_by_id(self, decision_id: str) -> Optional[DecisionExplainabilityRecord]:
        with self._lock:
            rec = self._records_by_id.get(decision_id)
            return rec.model_copy() if rec else None

    def get_by_symbol(self, symbol: str, limit: int = 50) -> List[DecisionExplainabilityRecord]:
        with self._lock:
            d_ids = self._records_by_symbol.get(symbol, [])[-limit:]
            return [self._records_by_id[did].model_copy() for did in d_ids if did in self._records_by_id]

    def reset(self) -> None:
        """Reset state for clean testing."""
        with self._lock:
            self._records_by_id.clear()
            self._records_by_correlation.clear()
            self._records_by_symbol.clear()


# Global singleton instance
global_explainability_engine = DecisionExplainabilityEngine()
