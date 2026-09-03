"""
Phase 28 — Distributed State, Coordination & Recovery REST API Routes

Endpoints for cluster node registry, worker partition leases, persistent state inspection,
split-brain quarantine controls, and the 14-step deterministic recovery engine.

Safety Invariant:
- Real-money live trading remains permanently locked and fail-closed.
- Zero live order execution authority.
- All actions strictly constrained to PAPER, SHADOW, and RESEARCH modes.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.domain.distributed_state_schemas import (
    ConsistencyState,
    CoordinationState,
    DistributedHealthSnapshot,
    NodeIdentity,
    RecoveryVerificationReport,
    WorkerLease,
)
from backend.application.persistent_state_store import global_persistent_state_store
from backend.application.state_journal import global_state_journal
from backend.application.node_identity_manager import global_node_identity_manager
from backend.application.distributed_coordinator import global_distributed_coordinator
from backend.application.state_conflict_resolver import global_state_conflict_resolver
from backend.application.distributed_recovery_engine import global_distributed_recovery_engine

distributed_router = APIRouter(prefix="/api/distributed", tags=["Distributed State & Coordination"])


class QuarantineRequest(BaseModel):
    reason: str = "Operator intervention"


@distributed_router.get("/nodes", response_model=List[NodeIdentity])
def get_nodes() -> List[NodeIdentity]:
    """Retrieve registered cluster nodes and sanitized configuration fingerprints."""
    global_node_identity_manager.record_heartbeat(global_node_identity_manager.node_id)
    return global_node_identity_manager.get_active_nodes()


@distributed_router.get("/workers")
def get_workers() -> Dict[str, Any]:
    """Retrieve worker partition ownership and lease status."""
    leases = global_distributed_coordinator.get_active_leases()
    quarantined = global_distributed_coordinator.get_quarantined_partitions()
    return {
        "active_leases_count": len(leases),
        "quarantined_count": len(quarantined),
        "leases": [l.model_dump() for l in leases],
        "quarantined_partitions": quarantined,
    }


@distributed_router.get("/state")
def get_state_summary() -> Dict[str, Any]:
    """Retrieve durable persistent state store revision and summary."""
    return {
        "current_revision": global_persistent_state_store.current_revision,
        "latest_journal_seq": global_state_journal.latest_sequence,
        "journal_head_hash": global_state_journal.last_hash,
        "state_data": global_persistent_state_store.get_state(),
    }


@distributed_router.get("/health", response_model=DistributedHealthSnapshot)
def get_distributed_health() -> DistributedHealthSnapshot:
    """Retrieve distributed cluster and persistence health snapshot."""
    leases = global_distributed_coordinator.get_active_leases()
    quarantined = global_distributed_coordinator.get_quarantined_partitions()
    j_valid, _, _ = global_state_journal.verify_integrity()

    consistency = ConsistencyState.CONSISTENT if j_valid else ConsistencyState.CORRUPTED
    if quarantined:
        coordination = CoordinationState.QUARANTINED
    else:
        coordination = global_distributed_coordinator.coordination_state

    return DistributedHealthSnapshot(
        node_count=len(global_node_identity_manager.get_active_nodes()),
        active_leases_count=len(leases),
        consistency_state=consistency,
        coordination_state=coordination,
        split_brain_detected=coordination == CoordinationState.SPLIT_BRAIN_SUSPECTED,
        quarantined_partitions=quarantined,
        latest_revision=global_persistent_state_store.current_revision,
        journal_sequence=global_state_journal.latest_sequence,
    )


@distributed_router.get("/leases", response_model=List[WorkerLease])
def get_leases() -> List[WorkerLease]:
    """Retrieve all currently active partition leases."""
    return global_distributed_coordinator.get_active_leases()


@distributed_router.get("/conflicts")
def get_conflicts() -> Dict[str, Any]:
    """Retrieve active state conflicts and quarantined partitions."""
    conflicts = global_state_conflict_resolver.get_active_conflicts()
    quarantined = global_distributed_coordinator.get_quarantined_partitions()
    return {
        "active_conflicts_count": len(conflicts),
        "quarantined_partitions": quarantined,
        "conflicts": [c.model_dump() for c in conflicts],
    }


@distributed_router.get("/recovery/status")
def get_recovery_status() -> Dict[str, Any]:
    """Retrieve latest recovery status and verification state."""
    report = global_distributed_recovery_engine.get_latest_report()
    if not report:
        return {"status": "NO_RECOVERY_RUN", "is_safe": True}
    return {
        "status": report.status.value,
        "steps_completed": report.steps_completed,
        "is_safe": report.is_safe_for_execution,
        "blockers": report.blockers,
    }


@distributed_router.get("/recovery/report", response_model=Optional[RecoveryVerificationReport])
def get_recovery_report() -> Optional[RecoveryVerificationReport]:
    """Retrieve full 14-step recovery verification audit report."""
    return global_distributed_recovery_engine.get_latest_report()


@distributed_router.post("/recovery/verify", response_model=RecoveryVerificationReport)
def run_recovery_verification() -> RecoveryVerificationReport:
    """Execute the full 14-step deterministic state recovery workflow."""
    return global_distributed_recovery_engine.execute_14_step_recovery()


@distributed_router.post("/workers/{symbol}/quarantine")
def quarantine_worker(symbol: str, request: QuarantineRequest) -> Dict[str, Any]:
    """Quarantine a symbol partition and halt paper execution immediately."""
    global_distributed_coordinator.quarantine_partition(symbol, request.reason)
    return {"status": "SUCCESS", "symbol": symbol.upper(), "quarantined": True, "reason": request.reason}


@distributed_router.post("/workers/{symbol}/unquarantine")
def unquarantine_worker(symbol: str) -> Dict[str, Any]:
    """Unquarantine a symbol partition after recovery verification."""
    global_distributed_coordinator.unquarantine_partition(symbol)
    return {"status": "SUCCESS", "symbol": symbol.upper(), "quarantined": False}
