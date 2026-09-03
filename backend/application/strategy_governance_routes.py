"""
Phase 29 — Strategy Governance REST API Routes

Exposes safe, read-only and operational governance controls under `/api/governance/*`.
Provides strategy version querying, lifecycle state machine transitions, champion/challenger comparisons,
conservative promotion gate evaluations, continuous monitoring status, and rollback controls.

Safety Invariants:
- STRICTLY OBSERVATIONAL & GOVERNANCE ONLY: Zero live-money order submission authority.
- All real-money live execution remains permanently fail-closed.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.domain.strategy_governance_schemas import (
    ChallengerRecord,
    ChampionChallengerComparison,
    ChampionRecord,
    GovernanceDecisionRecord,
    GovernancePolicy,
    GovernanceStatusSummary,
    PromotionGateResult,
    RollbackReason,
    StrategyLifecycleState,
    StrategyPerformanceSnapshot,
    StrategyRole,
    StrategyVersion,
)
from backend.application.strategy_governance_engine import (
    InvalidTransitionError,
    PromotionGateBlockedError,
    StrategyNotFoundError,
    global_strategy_governance_engine,
)

governance_router = APIRouter(prefix="/api/governance", tags=["Strategy Governance"])


# ── Request / Response DTOs ───────────────────────────────────────────────────

class RegisterStrategyRequest(BaseModel):
    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = "OPERATOR"
    parameters: Dict[str, Any] = Field(default_factory=dict)
    performance: Optional[StrategyPerformanceSnapshot] = None
    tags: List[str] = Field(default_factory=list)


class TransitionStrategyRequest(BaseModel):
    target_state: StrategyLifecycleState
    reason: str
    operator: str = "OPERATOR"


class CompareStrategiesRequest(BaseModel):
    champion_id: str
    challenger_id: str


class GateEvaluationRequest(BaseModel):
    challenger_id: str
    champion_id: Optional[str] = None


class PromoteStrategyRequest(BaseModel):
    challenger_id: str
    override_protection: bool = False
    rationale: str = "Promoted by operator"
    operator: str = "OPERATOR"


class TriggerRollbackRequest(BaseModel):
    reason: RollbackReason = RollbackReason.MANUAL
    details: str = "Manual operator rollback"
    fallback_strategy_id: Optional[str] = None
    operator: str = "OPERATOR"


# ── Route Handlers ────────────────────────────────────────────────────────────

@governance_router.get(
    "/status",
    response_model=GovernanceStatusSummary,
    summary="Get Strategy Governance System Status",
)
def get_governance_status() -> GovernanceStatusSummary:
    """Retrieve high-level governance status, champion summary, and state distribution."""
    return global_strategy_governance_engine.get_status_summary()


@governance_router.get(
    "/strategies",
    response_model=List[StrategyVersion],
    summary="List Registered Strategies",
)
def list_strategies(
    state: Optional[StrategyLifecycleState] = Query(None, description="Filter by lifecycle state"),
    role: Optional[StrategyRole] = Query(None, description="Filter by strategy role"),
) -> List[StrategyVersion]:
    """List all registered strategy versions with optional state and role filtering."""
    return global_strategy_governance_engine.list_strategies(state=state, role=role)


@governance_router.post(
    "/strategies",
    response_model=StrategyVersion,
    status_code=status.HTTP_201_CREATED,
    summary="Register New Strategy Version",
)
def register_strategy(req: RegisterStrategyRequest) -> StrategyVersion:
    """Register a new strategy version in the CANDIDATE state."""
    try:
        return global_strategy_governance_engine.register_strategy(
            name=req.name,
            version=req.version,
            description=req.description,
            author=req.author,
            parameters=req.parameters,
            performance=req.performance,
            tags=req.tags,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@governance_router.get(
    "/strategies/{strategy_id}",
    response_model=StrategyVersion,
    summary="Get Strategy Version Details",
)
def get_strategy(strategy_id: str) -> StrategyVersion:
    """Retrieve full details for a specific strategy version."""
    try:
        return global_strategy_governance_engine.get_strategy(strategy_id)
    except StrategyNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@governance_router.post(
    "/strategies/{strategy_id}/transition",
    response_model=StrategyVersion,
    summary="Transition Strategy Lifecycle State",
)
def transition_strategy(strategy_id: str, req: TransitionStrategyRequest) -> StrategyVersion:
    """Execute a lifecycle state transition enforcing state machine invariants."""
    try:
        return global_strategy_governance_engine.transition_strategy(
            strategy_id=strategy_id,
            target_state=req.target_state,
            reason=req.reason,
            operator=req.operator,
        )
    except StrategyNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except InvalidTransitionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@governance_router.get(
    "/champion",
    response_model=Optional[ChampionRecord],
    summary="Get Active Champion Strategy",
)
def get_champion() -> Optional[ChampionRecord]:
    """Retrieve summary of the currently active Champion strategy."""
    return global_strategy_governance_engine.get_champion()


@governance_router.get(
    "/challengers",
    response_model=List[ChallengerRecord],
    summary="List Active Challenger Strategies",
)
def get_challengers() -> List[ChallengerRecord]:
    """List all active Challenger strategies eligible for promotion comparison."""
    return global_strategy_governance_engine.get_challengers()


@governance_router.post(
    "/compare",
    response_model=ChampionChallengerComparison,
    summary="Compare Champion vs Challenger across 12 Dimensions",
)
def compare_strategies(req: CompareStrategiesRequest) -> ChampionChallengerComparison:
    """Execute 12-dimension deterministic scoring comparison between Champion and Challenger."""
    try:
        return global_strategy_governance_engine.compare_strategies(
            champion_id=req.champion_id,
            challenger_id=req.challenger_id,
        )
    except StrategyNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@governance_router.post(
    "/gates/evaluate",
    response_model=PromotionGateResult,
    summary="Evaluate Conservative Promotion Gates",
)
def evaluate_promotion_gates(req: GateEvaluationRequest) -> PromotionGateResult:
    """Evaluate statistical promotion gates for a Challenger strategy."""
    try:
        return global_strategy_governance_engine.evaluate_promotion_gates(
            challenger_id=req.challenger_id,
            champion_id=req.champion_id,
        )
    except StrategyNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@governance_router.post(
    "/promote",
    response_model=StrategyVersion,
    summary="Promote Challenger to Champion",
)
def promote_to_champion(req: PromoteStrategyRequest) -> StrategyVersion:
    """Promote Challenger strategy to Champion if all gates pass."""
    try:
        return global_strategy_governance_engine.promote_to_champion(
            challenger_id=req.challenger_id,
            override_protection=req.override_protection,
            rationale=req.rationale,
            operator=req.operator,
        )
    except StrategyNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except InvalidTransitionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except PromotionGateBlockedError as e:
        raise HTTPException(status_code=status.HTTP_412_PRECONDITION_FAILED, detail=str(e))


@governance_router.post(
    "/rollback",
    summary="Trigger Strategy Rollback",
)
def trigger_rollback(req: TriggerRollbackRequest) -> Dict[str, Any]:
    """Execute an immediate rollback of the active Champion strategy."""
    try:
        champ, fallback = global_strategy_governance_engine.trigger_rollback(
            reason=req.reason,
            details=req.details,
            fallback_strategy_id=req.fallback_strategy_id,
            operator=req.operator,
        )
        return {
            "status": "ROLLED_BACK",
            "rolled_back_champion_id": champ.strategy_id,
            "reinstated_fallback_id": fallback.strategy_id if fallback else None,
            "reason": req.reason.value,
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@governance_router.get(
    "/policy",
    response_model=GovernancePolicy,
    summary="Get Governance Policy Thresholds",
)
def get_policy() -> GovernancePolicy:
    """Retrieve current governance policy thresholds."""
    return global_strategy_governance_engine.policy


@governance_router.put(
    "/policy",
    response_model=GovernancePolicy,
    summary="Update Governance Policy Thresholds",
)
def update_policy(policy: GovernancePolicy) -> GovernancePolicy:
    """Update governance policy thresholds."""
    return global_strategy_governance_engine.update_policy(policy)


@governance_router.get(
    "/decisions",
    response_model=List[GovernanceDecisionRecord],
    summary="List Governance Decision Audit Records",
)
def list_decisions(
    limit: int = Query(50, ge=1, le=500, description="Max decision records to return")
) -> List[GovernanceDecisionRecord]:
    """Retrieve audit history of formal governance decisions."""
    return global_strategy_governance_engine.list_decisions(limit=limit)
