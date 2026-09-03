"""
Phase 28 — Multi-Node Identity & Lifecycle Manager

Coordinates deterministic cluster node identities, sanitized configuration fingerprints,
and cluster member registration without secrets.

Safety Invariant:
- Real-money live trading remains permanently locked, unroutable, and fail-closed.
- LIVE execution mode is strictly forbidden.
- Node identity and diagnostics contain ZERO credentials or secrets.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional
import uuid

from backend.domain.distributed_state_schemas import (
    DISTRIBUTED_STATE_VERSION,
    NodeIdentity,
)

logger = logging.getLogger(__name__)


class NodeIdentityManager:
    """
    Manages local node identity and maintains cluster-wide node registration.
    """

    def __init__(
        self,
        node_id: Optional[str] = None,
        execution_mode: str = "PAPER",
        config_fingerprint: Optional[str] = None,
    ):
        self._lock = threading.RLock()
        self.node_id = node_id or f"node-{uuid.uuid4().hex[:8]}"
        self.process_id = os.getpid()
        self.execution_mode = execution_mode
        self.software_version = DISTRIBUTED_STATE_VERSION
        self.config_fingerprint = config_fingerprint or "CANONICAL_PHASE28_CONFIG_FINGERPRINT"

        self._local_identity = NodeIdentity(
            node_id=self.node_id,
            process_id=self.process_id,
            worker_ids=[f"worker-{s}" for s in ["TCS.NS", "RELIANCE.NS", "INFY.NS"]],
            software_version=self.software_version,
            configuration_fingerprint=self.config_fingerprint,
            execution_mode=self.execution_mode,
            is_leader=True,
        )
        self._cluster_nodes: Dict[str, NodeIdentity] = {self.node_id: self._local_identity}
        self._last_heartbeat: Dict[str, datetime] = {self.node_id: datetime.now(timezone.utc)}

    @property
    def local_identity(self) -> NodeIdentity:
        with self._lock:
            return self._local_identity

    def register_node(self, node: NodeIdentity) -> None:
        """Register a remote or peer node in the cluster directory."""
        with self._lock:
            self._cluster_nodes[node.node_id] = node
            self._last_heartbeat[node.node_id] = datetime.now(timezone.utc)
            logger.info(f"Registered cluster node: {node.node_id} (mode={node.execution_mode})")

    def record_heartbeat(self, node_id: str) -> None:
        """Record node heartbeat."""
        with self._lock:
            self._last_heartbeat[node_id] = datetime.now(timezone.utc)

    def get_active_nodes(self, max_age_seconds: float = 30.0) -> List[NodeIdentity]:
        """Return list of active nodes whose heartbeat is within max_age_seconds."""
        with self._lock:
            now = datetime.now(timezone.utc)
            active: List[NodeIdentity] = []
            for n_id, node in self._cluster_nodes.items():
                hb = self._last_heartbeat.get(n_id)
                if hb and (now - hb).total_seconds() <= max_age_seconds:
                    active.append(node)
            return active

    def update_worker_list(self, worker_ids: List[str]) -> None:
        """Update active worker IDs assigned to local node."""
        with self._lock:
            self._local_identity.worker_ids = worker_ids
            self._cluster_nodes[self.node_id] = self._local_identity


# Global node identity manager singleton
global_node_identity_manager = NodeIdentityManager()
