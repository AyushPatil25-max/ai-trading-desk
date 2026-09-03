"""
Phase 18 — Streaming & WebSocket Telemetry API Routes

Provides:
- WebSocket endpoint `/ws/telemetry` for real-time bi-directional streaming.
- REST endpoints for stream health status, latency metrics, tick ingestion, and worker control.
- Fail-closed execution boundary: Live real-money trading is permanently blocked.
"""

import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from backend.domain.streaming_schemas import (
    STREAMING_ENGINE_VERSION,
    BackpressureStrategy,
    DistributedWorkerPoolStatus,
    StreamEvent,
    StreamEventType,
    StreamHealthMetrics,
    StreamSubscription,
)
from backend.application.stream_manager import global_stream_manager
from backend.utils.json_safety import sanitize_for_json

logger = logging.getLogger(__name__)

streaming_router = APIRouter(tags=["Phase 18 — Real-Time Streaming & Telemetry"])


# ── Request / Response Models ─────────────────────────────────────────────────

class IngestTickRequest(BaseModel):
    symbol: str = Field(min_length=1, default="TCS.NS")
    price: float = Field(default=3500.0, description="Latest market price")
    volume: Optional[float] = Field(default=100.0)
    source: str = Field(default="MANUAL_INGEST")
    sequence_num: Optional[int] = Field(default=None)


class WorkerControlRequest(BaseModel):
    action: str = Field(default="start", description="start, stop, pause, resume")
    symbols: Optional[List[str]] = Field(default=None)


# ── WebSocket Telemetry Endpoint ──────────────────────────────────────────────

@streaming_router.websocket("/ws/telemetry")
async def websocket_telemetry_endpoint(websocket: WebSocket):
    """
    Real-time bi-directional telemetry streaming connection.
    Features subscription management, periodic heartbeats, client ping/pong,
    and automatic resource cleanup upon disconnect.
    """
    await websocket.accept()
    consumer_id = f"ws-{uuid.uuid4().hex[:8]}"
    sub = StreamSubscription(
        consumer_id=consumer_id,
        symbols=["*"],
        event_types=[
            StreamEventType.MARKET_TICK,
            StreamEventType.EXECUTION_EVENT,
            StreamEventType.TELEMETRY_EVENT,
            StreamEventType.SYSTEM_EVENT,
            StreamEventType.HEARTBEAT,
        ],
        queue_capacity=500,
        backpressure_strategy=BackpressureStrategy.DROP_OLDEST,
    )
    consumer = global_stream_manager.register_consumer(sub)
    logger.info(f"[WebSocket] Client connected: {consumer_id}")

    # Send initial welcome & connection confirmation
    await websocket.send_json({
        "type": "CONNECTION_ACK",
        "consumer_id": consumer_id,
        "engine_version": STREAMING_ENGINE_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fail_closed_mode": "TIER_4_LIVE_REAL_MONEY_PERMANENTLY_BLOCKED",
    })

    last_heartbeat = asyncio.get_event_loop().time()

    try:
        while True:
            # 1. Non-blocking check for incoming client messages
            try:
                msg_text = await asyncio.wait_for(websocket.receive_text(), timeout=0.05)
                try:
                    msg = json.loads(msg_text)
                    action = msg.get("action", "").lower()
                    if action == "ping":
                        await websocket.send_json({
                            "type": "PONG",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                    elif action == "subscribe":
                        new_symbols = msg.get("symbols", ["*"])
                        sub.symbols = new_symbols
                        logger.info(f"[WebSocket] Consumer {consumer_id} updated subscriptions: {new_symbols}")
                        await websocket.send_json({
                            "type": "SUBSCRIPTION_UPDATED",
                            "symbols": new_symbols,
                        })
                    elif action == "reconnect":
                        global_stream_manager.record_reconnect()
                except Exception as parse_err:
                    logger.debug(f"[WebSocket] Client message parse error: {parse_err}")
            except asyncio.TimeoutError:
                pass  # Normal timeout when client sends no input

            # 2. Drain events from the consumer queue
            events_drained = 0
            while events_drained < 50:
                evt = consumer.pop()
                if not evt:
                    break
                await websocket.send_json(sanitize_for_json(evt.model_dump()))
                events_drained += 1

            # 3. Periodic heartbeat (every 5 seconds)
            now_time = asyncio.get_event_loop().time()
            if now_time - last_heartbeat >= 5.0:
                last_heartbeat = now_time
                metrics = global_stream_manager.get_metrics()
                await websocket.send_json({
                    "type": "HEARTBEAT",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "queue_depth": consumer.get_queue_depth(),
                    "events_per_second": metrics.events_per_second,
                    "avg_latency_ms": metrics.processing_latency_avg_ms,
                })

            await asyncio.sleep(0.02)

    except WebSocketDisconnect:
        logger.info(f"[WebSocket] Client disconnected cleanly: {consumer_id}")
    except Exception as ex:
        logger.warning(f"[WebSocket] Client error on {consumer_id}: {ex}")
    finally:
        global_stream_manager.unregister_consumer(consumer_id)


# ── REST API Endpoints ────────────────────────────────────────────────────────

@streaming_router.get("/api/streaming/status")
def get_stream_status():
    """Return stream manager health status and high-level metrics."""
    metrics = global_stream_manager.get_metrics()
    return {
        "status": "HEALTHY",
        "engine_version": STREAMING_ENGINE_VERSION,
        "phase": 18,
        "phase_name": "Distributed Real-Time Streaming & High-Frequency Telemetry Ingestion",
        "tier4_live_real_money_blocked": True,
        "metrics": sanitize_for_json(metrics.model_dump()),
    }


@streaming_router.get("/api/streaming/metrics")
def get_detailed_stream_metrics():
    """Return latency percentiles (p50/p95/p99) and data quality counters."""
    metrics = global_stream_manager.get_metrics()
    return sanitize_for_json(metrics.model_dump())


@streaming_router.post("/api/streaming/ingest")
def ingest_tick_endpoint(req: IngestTickRequest):
    """Manually or programmatically inject a market tick into the stream."""
    evt = global_stream_manager.ingest_raw_tick(
        symbol=req.symbol.upper(),
        price=req.price,
        volume=req.volume,
        source=req.source,
        sequence_num=req.sequence_num,
    )
    return sanitize_for_json(evt.model_dump())


@streaming_router.get("/api/streaming/workers")
def get_workers_status():
    """Return operational status of the distributed paper simulation worker pool."""
    from backend.application.distributed_paper_worker import global_worker_pool
    status = global_worker_pool.get_status()
    return sanitize_for_json(status.model_dump())


@streaming_router.post("/api/streaming/workers/control")
def control_workers_endpoint(req: WorkerControlRequest):
    """Start, stop, or pause the distributed paper simulation worker pool."""
    from backend.application.distributed_paper_worker import global_worker_pool
    action = req.action.lower()
    if action == "start":
        res = global_worker_pool.start(symbols=req.symbols)
    elif action == "stop":
        res = global_worker_pool.stop()
    elif action == "pause":
        res = global_worker_pool.pause()
    elif action == "resume":
        res = global_worker_pool.resume()
    else:
        raise HTTPException(status_code=400, detail=f"Unknown worker control action '{req.action}'.")
    return sanitize_for_json(res.model_dump())
