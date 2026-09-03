"""
Phase 35 -- AI Advisory Guard & Low-Latency Optimization Engine

Ensures AI/LLM advisory outputs remain strictly non-authoritative, time-bounded,
and deterministic before interfacing with the authoritative Execution Decision Pipeline.

Safety Invariants:
1. AI ADVISORY ONLY: AI/LLM results NEVER possess execution authority.
2. Latency Budget Enforcement: AI inference exceeding budget fails closed.
3. Stale Output Prevention: Advisory outputs older than MAX_ADVISORY_AGE (5s) are rejected.
4. Metadata Sanitization: Injected authorization flags ('approved=True', 'bypass=True') are stripped.
5. Deterministic Veto Preservation: AI cannot bypass RiskEngine, PreFlight, Governance,
   Readiness, Arming, Safety Gate, Kill Switch, or Duplicate Checks.
"""

from datetime import datetime, timezone, timedelta
import logging
import math
import time
from typing import Any, Callable, Dict, Optional, Tuple
import uuid

from pydantic import BaseModel, Field

from backend.domain.execution_decision_schemas import ExecutionMode, ExecutionPipelineRequest
from backend.domain.strategy_schemas import SignalDirection, SignalSource

logger = logging.getLogger(__name__)


class AIAdvisoryBudget(BaseModel):
    """Latency, age, and confidence limits for AI advisory evaluations."""
    max_latency_ms: float = 1500.0
    max_age_seconds: float = 5.0
    min_confidence: float = 0.50
    max_confidence: float = 1.0


class AIAdvisoryEvaluationResult(BaseModel):
    """Result of AI advisory output validation and normalization."""
    is_valid: bool
    rejection_reason: Optional[str] = None
    sanitized_request: Optional[ExecutionPipelineRequest] = None
    measured_latency_ms: float = 0.0
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AIAdvisoryGuard:
    """
    Deterministic gatekeeper that evaluates, bounds, sanitizes, and prepares AI advisory signals.
    """

    def __init__(self, budget: Optional[AIAdvisoryBudget] = None):
        self.budget = budget or AIAdvisoryBudget()

    def validate_and_prepare_request(
        self,
        strategy_id: str,
        strategy_version: str,
        symbol: str,
        direction: str,
        quantity: float,
        target_price: Optional[float] = None,
        stop_loss_price: Optional[float] = None,
        execution_mode: ExecutionMode = ExecutionMode.PAPER,
        confirmation_token: Optional[str] = None,
        ai_timestamp: Optional[datetime] = None,
        ai_latency_ms: Optional[float] = None,
        ai_confidence: Optional[float] = None,
        ai_status: str = "SUCCESS",
        metadata: Optional[Dict[str, Any]] = None,
        current_time: Optional[datetime] = None,
    ) -> AIAdvisoryEvaluationResult:
        """
        Validate and sanitize an AI advisory signal into a fail-closed ExecutionPipelineRequest.
        """
        now = current_time or datetime.now(timezone.utc)
        eval_time = now if now.tzinfo else now.replace(tzinfo=timezone.utc)

        # 1. AI Service Status & Timeout Check
        if ai_status.upper() in ("TIMEOUT", "FAILED", "DEGRADED_UNAVAILABLE", "ERROR"):
            return AIAdvisoryEvaluationResult(
                is_valid=False,
                rejection_reason=f"AI advisory service failed or timed out (status={ai_status}). Fail-closed invariant enforced.",
                measured_latency_ms=ai_latency_ms or 0.0,
                evaluated_at=eval_time,
            )

        # 2. Latency Budget Enforcement
        measured_lat = float(ai_latency_ms or 0.0)
        if math.isnan(measured_lat) or math.isinf(measured_lat) or measured_lat < 0.0:
            return AIAdvisoryEvaluationResult(
                is_valid=False,
                rejection_reason="Invalid AI advisory latency: must be a non-negative finite number.",
                measured_latency_ms=0.0,
                evaluated_at=eval_time,
            )

        if measured_lat > self.budget.max_latency_ms:
            return AIAdvisoryEvaluationResult(
                is_valid=False,
                rejection_reason=f"AI advisory latency {measured_lat:.1f}ms exceeded budget {self.budget.max_latency_ms:.1f}ms.",
                measured_latency_ms=measured_lat,
                evaluated_at=eval_time,
            )

        # 3. Confidence Bounds Validation
        if ai_confidence is not None:
            if math.isnan(ai_confidence) or math.isinf(ai_confidence):
                return AIAdvisoryEvaluationResult(
                    is_valid=False,
                    rejection_reason="AI advisory confidence must be a finite numerical value.",
                    measured_latency_ms=measured_lat,
                    evaluated_at=eval_time,
                )
            if ai_confidence < self.budget.min_confidence or ai_confidence > self.budget.max_confidence:
                return AIAdvisoryEvaluationResult(
                    is_valid=False,
                    rejection_reason=f"AI advisory confidence {ai_confidence:.2f} is outside acceptable range [{self.budget.min_confidence}, {self.budget.max_confidence}].",
                    measured_latency_ms=measured_lat,
                    evaluated_at=eval_time,
                )

        # 4. Freshness & Staleness Check
        ts = ai_timestamp or now
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        # Check future timestamp
        if (ts - eval_time).total_seconds() > 1.0:
            return AIAdvisoryEvaluationResult(
                is_valid=False,
                rejection_reason="AI advisory timestamp is in the FUTURE (clock skew error).",
                measured_latency_ms=measured_lat,
                evaluated_at=eval_time,
            )

        age = (eval_time - ts).total_seconds()
        if age > self.budget.max_age_seconds:
            return AIAdvisoryEvaluationResult(
                is_valid=False,
                rejection_reason=f"AI advisory is STALE (age={age:.2f}s > {self.budget.max_age_seconds}s).",
                measured_latency_ms=measured_lat,
                evaluated_at=eval_time,
            )

        # 5. Metadata Sanitization: Strip any adversarial bypass keys
        raw_meta = dict(metadata or {})
        forbidden_keys = [
            "approved", "is_approved", "is_authorized", "is_safe", "bypass_safety",
            "bypass_risk", "override_governance", "force_execution", "skip_preflight",
            "skip_arming", "skip_readiness", "admin_override",
        ]
        sanitized_meta = {k: v for k, v in raw_meta.items() if k.lower() not in forbidden_keys}
        sanitized_meta["ai_latency_ms"] = measured_lat
        sanitized_meta["ai_timestamp"] = ts.isoformat()
        sanitized_meta["is_ai_advisory"] = True

        # 6. Direction & Quantity Validation
        try:
            dir_clean = direction.upper().strip()
            if dir_clean not in ("BUY", "SELL", "HOLD"):
                return AIAdvisoryEvaluationResult(
                    is_valid=False,
                    rejection_reason=f"Invalid signal direction '{direction}'.",
                    measured_latency_ms=measured_lat,
                    evaluated_at=eval_time,
                )
        except Exception:
            return AIAdvisoryEvaluationResult(
                is_valid=False,
                rejection_reason="Invalid direction parameter.",
                measured_latency_ms=measured_lat,
                evaluated_at=eval_time,
            )

        if quantity <= 0 or math.isnan(quantity) or math.isinf(quantity):
            return AIAdvisoryEvaluationResult(
                is_valid=False,
                rejection_reason="Quantity must be a positive finite number.",
                measured_latency_ms=measured_lat,
                evaluated_at=eval_time,
            )

        req = ExecutionPipelineRequest(
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            symbol=symbol,
            direction=dir_clean,
            quantity=quantity,
            target_price=target_price,
            stop_loss_price=stop_loss_price,
            execution_mode=execution_mode,
            confirmation_token=confirmation_token,
            timestamp=ts,
            market_data_timestamp=ts,
            source="AI_ADVISORY",
            metadata=sanitized_meta,
        )

        return AIAdvisoryEvaluationResult(
            is_valid=True,
            rejection_reason=None,
            sanitized_request=req,
            measured_latency_ms=measured_lat,
            evaluated_at=eval_time,
        )


global_ai_advisory_guard = AIAdvisoryGuard()
