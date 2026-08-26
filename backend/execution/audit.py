"""
Execution Audit Engine — Phase 5.1

Maintains an immutable, structured record of every order evaluation, validation result,
and execution outcome.
"""

from datetime import datetime
from typing import Dict, List, Optional
import uuid

from backend.domain.execution_schemas import (
    ExecutionAuditRecord,
    ExecutionDecision,
    ExecutionResult,
    OrderRequest,
    OrderValidationResult,
)


class ExecutionAuditManager:
    """
    Structured in-memory and auditable execution log.
    """

    def __init__(self) -> None:
        self._records: List[ExecutionAuditRecord] = []
        self._by_context: Dict[str, List[ExecutionAuditRecord]] = {}
        self._by_order: Dict[str, ExecutionAuditRecord] = {}

    def record(
        self,
        order: OrderRequest,
        validation: OrderValidationResult,
        execution: Optional[ExecutionResult] = None,
        kill_switch_active: bool = False,
        metadata: Optional[dict] = None,
    ) -> ExecutionAuditRecord:
        """
        Create and append a new execution audit record.
        """
        audit_id = f"aud-{uuid.uuid4().hex[:8]}"
        record = ExecutionAuditRecord(
            audit_id=audit_id,
            order_id=order.order_id,
            context_id=order.context_id,
            run_id=order.run_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=order.price,
            decision=validation.decision,
            validation_result=validation,
            execution_result=execution,
            timestamp=datetime.utcnow(),
            kill_switch_active=kill_switch_active,
            metadata=metadata or {},
        )

        self._records.append(record)
        self._by_order[order.order_id] = record

        if order.context_id not in self._by_context:
            self._by_context[order.context_id] = []
        self._by_context[order.context_id].append(record)

        return record

    def get_by_context(self, context_id: str) -> List[ExecutionAuditRecord]:
        """Retrieve audit history for a specific context ID."""
        return self._by_context.get(context_id, [])

    def get_by_order(self, order_id: str) -> Optional[ExecutionAuditRecord]:
        """Retrieve audit record for a specific order ID."""
        return self._by_order.get(order_id)

    def all_records(self) -> List[ExecutionAuditRecord]:
        """Retrieve all recorded audit events."""
        return list(self._records)

    def clear(self) -> None:
        """Reset the audit log."""
        self._records.clear()
        self._by_context.clear()
        self._by_order.clear()
