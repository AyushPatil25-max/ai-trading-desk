"""
Phase 42 — Final Production Activation & Controlled Live Execution Routes

Exposes secure, deterministic REST API endpoints for:
1. Operator Authorization Token Issuance (Human operator only)
2. Controlled Live Trade Execution (1 order, multi-stage safety gate)
3. Production Readiness & Certification Status
4. First Live Trade Hard Safety Limits Inspection
5. Live Order History & Broker Reconciliation

Safety Invariants:
- All secrets (passwords, tokens, API keys) are strictly redacted.
- Direct live execution without human operator token is blocked (403/400).
- LIVE_EXECUTION_ENABLED=False remains fail-closed default.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.domain.broker_schemas import (
    ExchangeSegment,
    OrderRequest as BrokerOrderRequestDomain,
    OrderSide as BrokerOrderSide,
    OrderType as BrokerOrderType,
    ProductType as BrokerProductType,
)
from backend.domain.phase42_schemas import (
    AppEnvironment,
    FirstLiveTradeConfig,
    LiveExecutionGateResult,
    ProductionCertificationReport,
)
from backend.execution.operator_authorization_store import global_operator_authorization_store
from backend.execution.live_execution_gate import global_live_execution_gate
from backend.execution.controlled_live_execution_orchestrator import global_controlled_live_trade_orchestrator
from backend.execution.production_certification_engine import global_production_certification_engine
from backend.execution.reconciliation_service import global_reconciliation_service

logger = logging.getLogger(__name__)

production_router = APIRouter(prefix="/api/production", tags=["Production Activation & Live Execution"])


# ── Request Models ────────────────────────────────────────────────────────────

class IssueOperatorTokenRequest(BaseModel):
    operator_id: str
    symbol: str
    side: str = "BUY"
    quantity: int = 1
    price: Optional[float] = None
    order_type: str = "LIMIT"
    exchange_segment: str = "NSE"
    product_type: str = "CNC"
    ttl_seconds: int = 120
    source: str = "HUMAN_OPERATOR"
    operator_notes: Optional[str] = None


class ControlledLiveExecutionRequest(BaseModel):
    symbol: str
    side: str = "BUY"
    quantity: int = 1
    price: Optional[float] = None
    order_type: str = "LIMIT"
    exchange_segment: str = "NSE"
    product_type: str = "CNC"
    operator_token_id: str
    confirmation_token: Optional[str] = None
    strategy_id: Optional[str] = None
    strategy_version: Optional[str] = None
    reference_price: Optional[float] = None
    request_id: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@production_router.post("/operator/token", status_code=status.HTTP_201_CREATED)
def issue_operator_authorization_token(req: IssueOperatorTokenRequest) -> Dict[str, Any]:
    """
    Issue a single-use, time-bound operator authorization token for a specific order.
    Rejects AI or autonomous caller sources.
    """
    try:
        side_enum = BrokerOrderSide.BUY if req.side.upper() == "BUY" else BrokerOrderSide.SELL
        order_type_enum = BrokerOrderType.LIMIT if req.order_type.upper() == "LIMIT" else BrokerOrderType.MARKET
        seg_enum = ExchangeSegment.NSE if req.exchange_segment.upper() in ("NSE", "NSE_EQ") else ExchangeSegment.BSE
        prod_enum = BrokerProductType.CNC

        order = BrokerOrderRequestDomain(
            symbol=req.symbol.upper().strip(),
            side=side_enum,
            quantity=req.quantity,
            price=req.price,
            order_type=order_type_enum,
            exchange_segment=seg_enum,
            product_type=prod_enum,
            request_id=f"req-{req.symbol}-{datetime.now(timezone.utc).timestamp()}",
        )

        token = global_operator_authorization_store.issue_token(
            operator_id=req.operator_id,
            order_request=order,
            ttl_seconds=req.ttl_seconds,
            source=req.source,
            operator_notes=req.operator_notes,
        )

        return {
            "token_id": token.token_id,
            "order_fingerprint": token.order_fingerprint,
            "operator_id": token.operator_id,
            "issued_at": token.issued_at.isoformat(),
            "expires_at": token.expires_at.isoformat(),
            "ttl_seconds": int((token.expires_at - token.issued_at).total_seconds()),
            "status": "ISSUED",
        }

    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        logger.error("Operator token issuance error: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@production_router.post("/execute")
def execute_controlled_live_trade(req: ControlledLiveExecutionRequest) -> Dict[str, Any]:
    """
    Submit a single controlled real-money trade through the full LiveExecutionGate hierarchy.
    """
    try:
        side_enum = BrokerOrderSide.BUY if req.side.upper() == "BUY" else BrokerOrderSide.SELL
        order_type_enum = BrokerOrderType.LIMIT if req.order_type.upper() == "LIMIT" else BrokerOrderType.MARKET
        seg_enum = ExchangeSegment.NSE if req.exchange_segment.upper() in ("NSE", "NSE_EQ") else ExchangeSegment.BSE
        prod_enum = BrokerProductType.CNC

        order = BrokerOrderRequestDomain(
            symbol=req.symbol.upper().strip(),
            side=side_enum,
            quantity=req.quantity,
            price=req.price,
            order_type=order_type_enum,
            exchange_segment=seg_enum,
            product_type=prod_enum,
            request_id=req.request_id or f"live-{req.symbol}-{datetime.now(timezone.utc).timestamp()}",
        )

        gate_res, order_rec, broker_res = global_controlled_live_trade_orchestrator.execute_controlled_trade(
            order=order,
            operator_token_id=req.operator_token_id,
            confirmation_token=req.confirmation_token,
            strategy_id=req.strategy_id,
            strategy_version=req.strategy_version,
            reference_price=req.reference_price,
        )

        if not gate_res.is_approved:
            return {
                "success": False,
                "gate_status": "REJECTED",
                "reason_code": gate_res.reason_code.value,
                "reason": gate_res.reason,
                "checks_failed": gate_res.checks_failed,
                "order_record": None,
                "broker_result": None,
            }

        return {
            "success": True,
            "gate_status": "APPROVED",
            "reason_code": gate_res.reason_code.value,
            "order_record": order_rec.model_dump(mode="json") if order_rec else None,
            "broker_result": broker_res.model_dump(mode="json") if broker_res else None,
        }

    except Exception as e:
        logger.error("Controlled trade execution error: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@production_router.get("/certification")
def get_production_certification(
    env: str = Query(default="LIVE_CONTROLLED", description="Target environment")
) -> Dict[str, Any]:
    """
    Evaluate and return the full Phase 42 production certification report.
    """
    try:
        env_enum = AppEnvironment.LIVE_CONTROLLED
        if env.upper() == "DEVELOPMENT":
            env_enum = AppEnvironment.DEVELOPMENT
        elif env.upper() == "PAPER_TRADING":
            env_enum = AppEnvironment.PAPER_TRADING

        report = global_production_certification_engine.certify_production_readiness(
            target_environment=env_enum
        )
        return report.model_dump(mode="json")
    except Exception as e:
        logger.error("Production certification evaluation error: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@production_router.get("/limits")
def get_first_live_trade_limits() -> Dict[str, Any]:
    """
    Return active first live trade hard limits.
    """
    return global_live_execution_gate.first_live_config.model_dump(mode="json")


@production_router.get("/orders")
def list_controlled_orders() -> List[Dict[str, Any]]:
    """
    List all controlled live order records.
    """
    records = global_controlled_live_trade_orchestrator.list_order_records()
    return [r.model_dump(mode="json") for r in records]


@production_router.post("/reconcile")
def run_broker_reconciliation() -> Dict[str, Any]:
    """
    Trigger manual broker order book reconciliation.
    """
    report = global_reconciliation_service.run_once()
    return report
